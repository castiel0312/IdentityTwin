import { useCallback, useEffect, useRef, useState } from "react";
import type { AuthSession } from "@/lib/auth";
import { queryClient } from "@/lib/query";

export type StreamStatus =
  | "idle"
  | "connecting"
  | "open"
  | "reconnecting"
  | "unauthorized"
  | "error";

export interface ContainmentStreamEvent {
  eventId: string;
  event: string;
  entityType: string;
  entityId: string;
  incidentId: string;
  sessionId: string | null;
  severity: string;
  status: string;
  receivedAt: string;
}

export interface ContainmentStream {
  status: StreamStatus;
  events: ContainmentStreamEvent[];
  lastEventId: string;
  error: string | null;
  paused: boolean;
  setPaused: (paused: boolean) => void;
  clear: () => void;
}

const API_BASE = (import.meta.env.VITE_API_BASE_URL ?? "").replace(/\/$/, "");
const INITIAL_RETRY_MS = 1_000;
const MAX_RETRY_MS = 15_000;
const MAX_EVENTS = 50;
const QUERY_KEYS_BY_EVENT: Record<string, readonly (readonly unknown[])[]> = {
  "behavioral.event": [
    ["sessions"],
    ["session"],
    ["session-activity"],
    ["session-intent-profiles"],
    ["risk-decisions"],
    ["analytics-overview"],
  ],
  "risk.decision": [
    ["risk-decisions"],
    ["risk-decision"],
    ["sessions"],
    ["session"],
    ["payouts"],
    ["payout"],
    ["analytics-overview"],
  ],
  "session.changed": [
    ["sessions"],
    ["session"],
    ["session-activity"],
    ["session-intent-profiles"],
    ["identities"],
    ["identity"],
    ["analytics-overview"],
  ],
  "payout.changed": [["payouts"], ["payout"], ["risk-decisions"], ["analytics-overview"]],
  "incident.changed": [
    ["incidents"],
    ["incident"],
    ["incident-actions"],
    ["incident-timeline"],
    ["incident-seal"],
    ["incident-trace"],
    ["incident-investigations"],
    ["analytics-overview"],
  ],
  "vaccination.match": [
    ["vaccination-matches"],
    ["risk-decisions"],
    ["sessions"],
    ["session"],
    ["analytics-overview"],
  ],
  "vaccination.signature": [["vaccination-signatures"], ["vaccination-matches"]],
  "evidence.appended": [["evidence-seals"], ["evidence-verify"], ["incident-seal"]],
  "evidence.sealed": [["evidence-seals"], ["evidence-seal"], ["incident-seal"]],
  "investigation.changed": [
    ["incident-investigations"],
    ["incident"],
    ["incident-actions"],
    ["incident-timeline"],
  ],
  "analyst.workflow": [
    ["incidents"],
    ["incident"],
    ["incident-actions"],
    ["incident-timeline"],
    ["incident-investigations"],
    ["incident-trace"],
    ["analytics-overview"],
  ],
};

function cursorStorageKey(session: AuthSession): string {
  return `identitytwin.domain-events.${session.merchantId}`;
}

function readStoredCursor(session: AuthSession): string {
  try {
    const value = window.sessionStorage.getItem(cursorStorageKey(session));
    return value && /^\d{1,19}$/.test(value) ? value : "0";
  } catch {
    return "0";
  }
}

function storeCursor(session: AuthSession, value: string): void {
  try {
    window.sessionStorage.setItem(cursorStorageKey(session), value);
  } catch {
    // Streaming remains functional when browser storage is unavailable.
  }
}

function synchronizeQueries(eventName: string): void {
  if (eventName === "stream.reset") {
    void queryClient.invalidateQueries();
    return;
  }
  const keys = QUERY_KEYS_BY_EVENT[eventName] ?? [];
  for (const queryKey of keys) {
    void queryClient.cancelQueries({ queryKey: [...queryKey] });
    void queryClient.invalidateQueries({ queryKey: [...queryKey] });
  }
}

function isRecord(value: unknown): value is Record<string, unknown> {
  return typeof value === "object" && value !== null && !Array.isArray(value);
}

export function useContainmentStream(
  enabled: boolean,
  session: AuthSession | null,
): ContainmentStream {
  const [status, setStatus] = useState<StreamStatus>("idle");
  const [events, setEvents] = useState<ContainmentStreamEvent[]>([]);
  const [lastEventId, setLastEventId] = useState(() => (session ? readStoredCursor(session) : "0"));
  const [error, setError] = useState<string | null>(null);
  const [paused, setPaused] = useState(false);
  const lastEventIdRef = useRef(lastEventId);
  const seenRef = useRef<Set<string>>(new Set());
  const previousSessionRef = useRef<AuthSession | null>(session);

  const clear = useCallback(() => {
    setEvents([]);
    setError(null);
  }, []);

  useEffect(() => {
    if (!session) return;
    const storedCursor = readStoredCursor(session);
    lastEventIdRef.current = storedCursor;
    // Only update state if session actually changed (avoids redundant setState on mount
    // and satisfies react-hooks/set-state-in-effect lint rule).
    if (previousSessionRef.current !== session) {
      previousSessionRef.current = session;
      setLastEventId(storedCursor);
    }
    if (!enabled || paused) return;

    let cancelled = false;
    let controller: AbortController | null = null;
    let retryTimer: ReturnType<typeof setTimeout> | null = null;
    let retryCount = 0;

    const handleBlock = (block: string) => {
      let eventName = "message";
      let eventId = "";
      let data = "";

      for (const line of block.split("\n")) {
        if (!line || line.startsWith(":")) continue;
        const separator = line.indexOf(":");
        const field = separator === -1 ? line : line.slice(0, separator);
        const raw = separator === -1 ? "" : line.slice(separator + 1);
        const value = raw.startsWith(" ") ? raw.slice(1) : raw;
        if (field === "event") eventName = value;
        else if (field === "id") eventId = value;
        else if (field === "data") data = data ? `${data}\n${value}` : value;
      }

      if (!data) return;
      let payload: unknown;
      try {
        payload = JSON.parse(data);
      } catch {
        return;
      }
      if (!isRecord(payload) || !/^\d{1,19}$/.test(eventId)) return;
      if (eventName === "stream.reset") {
        seenRef.current.clear();
        lastEventIdRef.current = eventId;
        storeCursor(session, eventId);
        setLastEventId(eventId);
        synchronizeQueries(eventName);
        return;
      }
      if (seenRef.current.has(eventId)) return;
      seenRef.current.add(eventId);
      if (BigInt(eventId) > BigInt(lastEventIdRef.current)) {
        lastEventIdRef.current = eventId;
        setLastEventId(eventId);
        storeCursor(session, eventId);
      }

      const nextEvent: ContainmentStreamEvent = {
        eventId,
        event: eventName,
        entityType: typeof payload.entity_type === "string" ? payload.entity_type : "",
        entityId: typeof payload.entity_id === "string" ? payload.entity_id : "",
        incidentId:
          typeof payload.incident_id === "string"
            ? payload.incident_id
            : eventName.startsWith("incident.") && typeof payload.entity_id === "string"
              ? payload.entity_id
              : "",
        sessionId: typeof payload.session_id === "string" ? payload.session_id : null,
        severity: typeof payload.severity === "string" ? payload.severity : "UNKNOWN",
        status: typeof payload.status === "string" ? payload.status : "UNKNOWN",
        receivedAt: new Date().toISOString(),
      };
      setEvents((current) => [nextEvent, ...current].slice(0, MAX_EVENTS));
      synchronizeQueries(eventName);
    };

    const connect = async () => {
      if (cancelled) return;
      setStatus(retryCount === 0 ? "connecting" : "reconnecting");
      controller = new AbortController();

      try {
        const params = new URLSearchParams();
        if (lastEventIdRef.current !== "0") {
          params.set("after_event_id", lastEventIdRef.current);
        }
        const query = params.toString();
        const headers: Record<string, string> = {
          Accept: "text/event-stream",
          Authorization: `Bearer ${session.token}`,
          ...session.devHeaders,
        };
        if (lastEventIdRef.current !== "0") {
          headers["Last-Event-ID"] = lastEventIdRef.current;
        }

        const response = await fetch(
          `${API_BASE}/v1/events/stream${query ? `?${query}` : ""}`,
          { headers, signal: controller.signal, cache: "no-store" },
        );

        if (!response.ok) {
          if (response.status === 401 || response.status === 403) {
            if (!cancelled) {
              setStatus("unauthorized");
              setError("The containment stream rejected this session.");
            }
            return;
          }
          throw new Error(`Stream request failed with status ${response.status}.`);
        }
        if (!response.body) throw new Error("The stream response had no body.");
        if (cancelled) return;

        retryCount = 0;
        setStatus("open");
        setError(null);

        const reader = response.body.getReader();
        const decoder = new TextDecoder();
        let buffer = "";

        while (!cancelled) {
          const { value, done } = await reader.read();
          if (done) break;
          buffer += decoder.decode(value, { stream: true }).replace(/\r\n/g, "\n");
          let boundary = buffer.indexOf("\n\n");
          while (boundary >= 0) {
            handleBlock(buffer.slice(0, boundary));
            buffer = buffer.slice(boundary + 2);
            boundary = buffer.indexOf("\n\n");
          }
        }

        if (!cancelled) throw new Error("The containment stream ended.");
      } catch (cause) {
        if (cancelled) return;
        if (cause instanceof DOMException && cause.name === "AbortError") return;
        setError(cause instanceof Error ? cause.message : "The containment stream failed.");
        setStatus("reconnecting");
        const delay = Math.min(MAX_RETRY_MS, INITIAL_RETRY_MS * 2 ** retryCount);
        retryCount += 1;
        retryTimer = setTimeout(() => {
          void connect();
        }, delay);
      }
    };

    void connect();

    return () => {
      cancelled = true;
      controller?.abort();
      if (retryTimer) clearTimeout(retryTimer);
    };
  }, [enabled, paused, session]);

  const active = enabled && !paused && session !== null;
  return {
    status: active ? status : "idle",
    events,
    lastEventId,
    error: active ? error : null,
    paused,
    setPaused,
    clear,
  };
}
