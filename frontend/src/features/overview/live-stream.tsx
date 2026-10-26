import { Activity, Pause, Play, Radio, Trash2, WifiOff } from "lucide-react";
import { useState } from "react";
import { Link } from "react-router-dom";
import { StatusBadge } from "@/components/common/badges";
import { Badge } from "@/components/ui/badge";
import { Button } from "@/components/ui/button";
import { Card, CardContent, CardDescription, CardHeader, CardTitle } from "@/components/ui/card";
import { Tooltip, TooltipContent, TooltipTrigger } from "@/components/ui/tooltip";
import { useAuth } from "@/lib/auth";
import { relativeTime } from "@/lib/format";
import { useContainmentStream, type StreamStatus } from "@/lib/sse";
import { cn } from "@/lib/utils";

const statusCopy: Record<StreamStatus, { label: string; variant: "success" | "warning" | "danger" | "muted" | "info" }> = {
  idle: { label: "Paused", variant: "muted" },
  connecting: { label: "Connecting", variant: "info" },
  open: { label: "Live", variant: "success" },
  reconnecting: { label: "Reconnecting", variant: "warning" },
  unauthorized: { label: "Permission denied", variant: "danger" },
  error: { label: "Disconnected", variant: "danger" },
};

export function LiveContainmentStream() {
  const { session } = useAuth();
  const [paused, setPaused] = useState(false);
  const stream = useContainmentStream(!paused, session);
  const copy = statusCopy[stream.status];

  return (
    <Card className="overflow-hidden">
      <CardHeader className="flex-row items-start justify-between space-y-0">
        <div className="space-y-1">
          <CardTitle className="flex items-center gap-2">
            <Radio className="h-4 w-4 text-primary" aria-hidden="true" />
            Containment stream
          </CardTitle>
          <CardDescription>
            Authenticated SSE fan-out of incident containment events. No token is placed in the URL.
          </CardDescription>
        </div>
        <Badge variant={copy.variant} className={cn(stream.status === "open" && "animate-pulse-ring")}>
          {stream.status === "open" ? <span className="h-1.5 w-1.5 rounded-full bg-signal-normal" aria-hidden="true" /> : null}
          {copy.label}
        </Badge>
      </CardHeader>
      <CardContent className="space-y-3">
        <div className="flex items-center justify-between gap-2">
          <p className="text-xs text-muted-foreground">
            {stream.lastEventId > 0 ? `Last event id ${stream.lastEventId}` : "Waiting for a new containment event."}
          </p>
          <div className="flex items-center gap-1">
            <Tooltip>
              <TooltipTrigger asChild>
                <Button
                  variant="ghost"
                  size="icon"
                  onClick={() => setPaused((value) => !value)}
                  aria-label={paused ? "Resume live stream" : "Pause live stream"}
                >
                  {paused ? <Play className="h-4 w-4" /> : <Pause className="h-4 w-4" />}
                </Button>
              </TooltipTrigger>
              <TooltipContent>{paused ? "Resume stream" : "Pause stream"}</TooltipContent>
            </Tooltip>
            <Tooltip>
              <TooltipTrigger asChild>
                <Button
                  variant="ghost"
                  size="icon"
                  onClick={stream.clear}
                  disabled={!stream.events.length}
                  aria-label="Clear stream events"
                >
                  <Trash2 className="h-4 w-4" />
                </Button>
              </TooltipTrigger>
              <TooltipContent>Clear this view</TooltipContent>
            </Tooltip>
          </div>
        </div>

        {stream.error && stream.status !== "idle" ? (
          <div role="alert" className="flex gap-2 rounded-xl border border-signal-restricted/25 bg-signal-restricted/[0.05] p-3 text-xs text-signal-restricted">
            <WifiOff className="mt-0.5 h-3.5 w-3.5 shrink-0" aria-hidden="true" />
            <span>{stream.error} The console retries with backoff; duplicate event ids are not replayed.</span>
          </div>
        ) : null}

        {stream.events.length === 0 ? (
          <div className="flex flex-col items-center justify-center gap-2 rounded-xl border border-dashed border-border bg-white/[0.015] py-9 text-center">
            <Activity className="h-4 w-4 text-muted-foreground" aria-hidden="true" />
            <p className="text-xs text-muted-foreground">
              {paused ? "Stream paused by this operator." : "Listening for canary containment events."}
            </p>
          </div>
        ) : (
          <ul className="divide-y divide-border/70 overflow-hidden rounded-xl border border-border/80">
            {stream.events.slice(0, 6).map((event) => (
              <li key={`${event.eventId}-${event.receivedAt}`} className="flex items-center justify-between gap-3 px-3 py-2.5">
                <div className="min-w-0">
                  <div className="flex flex-wrap items-center gap-2">
                    <StatusBadge status={event.severity} />
                    <span className="text-xs font-medium">{event.event}</span>
                  </div>
                  <p className="mt-0.5 text-[11px] text-muted-foreground">
                    Incident{" "}
                    <Link to={`/incidents/${event.incidentId}`} className="font-mono text-primary hover:underline">
                      {event.incidentId.slice(0, 8)}…
                    </Link>{" "}
                    · Session {event.sessionId.slice(0, 8)}…
                  </p>
                </div>
                <span className="shrink-0 text-[11px] text-muted-foreground">{relativeTime(event.receivedAt)}</span>
              </li>
            ))}
          </ul>
        )}
        <p className="text-[11px] leading-5 text-muted-foreground">
          Best-effort in-process stream. Durable incidents and evidence are the source of truth after a reconnect.
        </p>
      </CardContent>
    </Card>
  );
}
