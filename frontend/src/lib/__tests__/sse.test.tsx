import { renderHook, waitFor } from "@testing-library/react";
import type { AuthSession } from "@/lib/auth";
import { queryClient } from "@/lib/query";
import { useContainmentStream } from "@/lib/sse";
import { afterEach, beforeEach, vi } from "vitest";

const session: AuthSession = {
  token: "dev-merchant-token",
  label: "Merchant operator",
  role: "merchant",
  merchantId: "00000000-0000-0000-0000-000000000001",
  developmentOnly: true,
  devHeaders: {
    "X-Dev-Role": "merchant",
    "X-Dev-Merchant-Id": "00000000-0000-0000-0000-000000000001",
    "X-Dev-User-Id": "11111111-1111-1111-1111-111111111111",
  },
};

beforeEach(() => {
  window.sessionStorage.clear();
  queryClient.clear();
});

afterEach(() => {
  vi.restoreAllMocks();
  vi.unstubAllGlobals();
});

describe("useContainmentStream", () => {
  it("preserves adjacent server event IDs above JavaScript's safe integer range", async () => {
    const eventIds = ["1793803304911907601", "1793803304911907602"];
    const data = eventIds
      .map(
        (eventId, index) =>
          `id: ${eventId}\nevent: payout.changed\ndata: ${JSON.stringify({
            entity_type: "payout_requests",
            entity_id: `payout-${index}`,
            session_id: `session-${index}`,
            status: "completed",
          })}\n\n`,
      )
      .join("");
    const body = new ReadableStream<Uint8Array>({
      start(controller) {
        controller.enqueue(new TextEncoder().encode(data));
      },
    });
    vi.stubGlobal(
      "fetch",
      vi.fn(async () => new Response(body, { status: 200 })),
    );

    const { result, unmount } = renderHook(() => useContainmentStream(true, session));

    await waitFor(() => expect(result.current.events).toHaveLength(2));

    expect(result.current.events.map((event) => event.eventId)).toEqual([...eventIds].reverse());
    expect(result.current.lastEventId).toBe(eventIds[1]);
    expect(window.sessionStorage.getItem(`identitytwin.domain-events.${session.merchantId}`)).toBe(
      eventIds[1],
    );
    unmount();
  });

  it("deduplicates replayed IDs and invalidates matching frontend read models", async () => {
    const invalidate = vi.spyOn(queryClient, "invalidateQueries");
    const frame =
      `id: 42\nevent: incident.changed\ndata: ${JSON.stringify({
        entity_type: "incidents",
        entity_id: "incident-1",
        session_id: "session-1",
        severity: "HIGH",
        status: "OPEN",
      })}\n\n`;
    const body = new ReadableStream<Uint8Array>({
      start(controller) {
        controller.enqueue(new TextEncoder().encode(frame + frame));
        controller.close();
      },
    });
    vi.stubGlobal("fetch", vi.fn(async () => new Response(body, { status: 200 })));

    const { result, unmount } = renderHook(() => useContainmentStream(true, session));

    await waitFor(() => expect(result.current.events).toHaveLength(1));
    expect(invalidate).toHaveBeenCalledWith(
      expect.objectContaining({ queryKey: ["incidents"] }),
    );
    expect(invalidate).toHaveBeenCalledWith(
      expect.objectContaining({ queryKey: ["incident-timeline"] }),
    );
    unmount();
  });

  it("recovers its cursor from tenant-scoped session storage after remount", async () => {
    const eventId = "73";
    const firstBody = new ReadableStream<Uint8Array>({
      start(controller) {
        controller.enqueue(
          new TextEncoder().encode(
            `id: ${eventId}\nevent: session.changed\ndata: ${JSON.stringify({
              entity_type: "sessions",
              entity_id: "session-1",
              status: "active",
            })}\n\n`,
          ),
        );
        controller.close();
      },
    });
    const secondBody = new ReadableStream<Uint8Array>({
      start() {
        // Keep the reconnect open until the test unmounts the hook.
      },
    });
    const fetchMock = vi
      .fn()
      .mockResolvedValueOnce(new Response(firstBody, { status: 200 }))
      .mockResolvedValueOnce(new Response(secondBody, { status: 200 }));
    vi.stubGlobal("fetch", fetchMock);

    const first = renderHook(() => useContainmentStream(true, session));
    await waitFor(() => expect(first.result.current.lastEventId).toBe(eventId));
    first.unmount();

    const second = renderHook(() => useContainmentStream(true, session));
    await waitFor(() => expect(fetchMock).toHaveBeenCalledTimes(2));
    const reconnectOptions = fetchMock.mock.calls[1]?.[1] as RequestInit;
    expect(new Headers(reconnectOptions.headers).get("Last-Event-ID")).toBe(eventId);
    expect(String(fetchMock.mock.calls[1]?.[0])).toContain(`after_event_id=${eventId}`);
    second.unmount();
  });
});
