import { useCallback, useEffect, useRef, useState } from "react";
import type { AuthSession } from "@/lib/auth";

export type StreamStatus =
  | "idle"
  | "connecting"
  | "open"
  | "reconnecting"
  | "unauthorized"
  | "error";

export interface ContainmentStreamEvent {
  eventId: number;
  event: string;
  incidentId: string;
  sessionId: string;
  severity: string;
  status: string;
  receivedAt: string;
}

export interface ContainmentStream {
  status: StreamStatus;
  events: ContainmentStreamEvent[];
  lastEventId: number;
  error: string | null;
  clear: () => void;
}

const API_BASE = (import.meta.env.VITE_API_BASE_URL ?? "").replace(/\/$/, "");
const INITIAL_RETRY_MS = 1_000;
const MAX_RETRY_MS = 15_000;
const MAX_EVENTS = 50;

function isRecord(value: unknown): value is Record<string, unknown> {
  return typeof value === "object" && value !== null && !Array.isArray(value);
}

export function useContainmentStream(
  enabled: boolean,
  session: AuthSession | null,
): ContainmentStream {
  const [status, setStatus] = useState<StreamStatus>("idle");
  const [events, setEvents] = useState<ContainmentStreamEvent[]>([]);
  const [lastEventId, setLastEventId] = useState(0);
  const [error, setError] = useState<string | null>(null);
  const lastEventIdRef = useRef(0);
  const seenRef = useRef<Set<number>>(new Set());

  const clear = useCallback(() => {
    setEvents([]);
    setError(null);
  }, []);

  useEffect(() => {
    if (!enabled || !session) return;

    let cancelled = false;
    let controller: AbortController | null = null;
    let retryTimer: ReturnType<typeof setTimeout> | null = null;
    let retryCount = 0;

    const handleBlock = (block: string) => {
      let eventName = "message";
      let eventId = 0;
      let data = "";

      for (const line of block.split("\n")) {
        if (!line || line.startsWith(":")) continue;
        const separator = line.indexOf(":");
        const field = separator === -1 ? line : line.slice(0, separator);
        const raw = separator === -1 ? "" : line.slice(separator + 1);
        const value = raw.startsWith(" ") ? raw.slice(1) : raw;
        if (field === "event") eventName = value;
        else if (field === "id") eventId = Number(value);
        else if (field === "data") data = data ? `${data}\n${value}` : value;
      }

      if (!data) return;
      let payload: unknown;
      try {
        payload = JSON.parse(data);
      } catch {
        return;
      }
      if (!isRecord(payload)) return;

      const resolvedId = Number.isFinite(eventId) ? eventId : Date.now();
      if (seenRef.current.has(resolvedId)) return;
      seenRef.current.add(resolvedId);
      if (resolvedId > lastEventIdRef.current) {
        lastEventIdRef.current = resolvedId;
        setLastEventId(resolvedId);
      }

      const nextEvent: ContainmentStreamEvent = {
        eventId: resolvedId,
        event: eventName,
        incidentId: typeof payload.incident_id === "string" ? payload.incident_id : "",
        sessionId: typeof payload.session_id === "string" ? payload.session_id : "",
        severity: typeof payload.severity === "string" ? payload.severity : "UNKNOWN",
        status: typeof payload.status === "string" ? payload.status : "UNKNOWN",
        receivedAt: new Date().toISOString(),
      };
      setEvents((current) => [nextEvent, ...current].slice(0, MAX_EVENTS));
    };

    const connect = async () => {
      if (cancelled) return;
      setStatus(retryCount === 0 ? "connecting" : "reconnecting");
      controller = new AbortController();

      try {
        const params = new URLSearchParams();
        if (lastEventIdRef.current > 0) {
          params.set("after_event_id", String(lastEventIdRef.current));
        }
        const query = params.toString();
        const headers: Record<string, string> = {
          Accept: "text/event-stream",
          Authorization: `Bearer ${session.token}`,
          ...session.devHeaders,
        };
        if (lastEventIdRef.current > 0) {
          headers["Last-Event-ID"] = String(lastEventIdRef.current);
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
  }, [enabled, session]);

  const active = enabled && session !== null;
  return {
    status: active ? status : "idle",
    events,
    lastEventId,
    error: active ? error : null,
    clear,
  };
}
