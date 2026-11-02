import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { Compass, Loader2, ShieldAlert, Sparkles } from "lucide-react";
import { toast } from "sonner";
import { ErrorState } from "@/components/common/error-state";
import { InfoNote } from "@/components/common/info-note";
import { Badge } from "@/components/ui/badge";
import { Button } from "@/components/ui/button";
import { Card, CardContent, CardDescription, CardHeader, CardTitle } from "@/components/ui/card";
import { api, ApiError } from "@/lib/api";
import { useAuth } from "@/lib/auth";
import { formatDateTime, humanizeCode } from "@/lib/format";

function confidenceVariant(confidence: string) {
  if (confidence === "HIGH") return "warning" as const;
  if (confidence === "MEDIUM") return "info" as const;
  if (confidence === "LOW") return "outline" as const;
  return "muted" as const;
}

export function IntentProfiler({ sessionId }: { sessionId: string }) {
  const { session } = useAuth();
  const queryClient = useQueryClient();
  const canRun = session?.role === "analyst" || session?.role === "admin";

  const query = useQuery({
    queryKey: ["session-intent-profiles", sessionId],
    queryFn: () => api.listSessionIntentProfiles(session!, sessionId),
    enabled: Boolean(session && sessionId),
  });

  const mutation = useMutation({
    mutationFn: () => api.createSessionIntentProfile(session!, sessionId, { use_llm: true }),
    onSuccess: (result) => {
      toast.success(
        result.status === "FALLBACK"
          ? "Intent profile recorded with deterministic fallback narrative."
          : "Intent profile recorded.",
      );
      void queryClient.invalidateQueries({ queryKey: ["session-intent-profiles", sessionId] });
    },
    onError: (cause) => {
      toast.error(
        cause instanceof ApiError
          ? `${cause.code}: ${cause.message}`
          : cause instanceof Error
            ? cause.message
            : "The intent profile could not be created.",
      );
    },
  });

  const latest = query.data?.items[0];
  const analysis = latest?.bundle.analysis;
  const confidenceBasis = analysis?.confidence_basis ?? [];
  const secondaryIntents = analysis?.secondary_intents ?? [];
  const evidence = analysis?.evidence ?? [];
  const limitations = analysis?.limitations ?? [];

  return (
    <Card>
      <CardHeader className="flex-row items-start justify-between gap-3 space-y-0">
        <div className="space-y-1.5">
          <CardTitle className="flex items-center gap-2">
            <Compass className="h-4 w-4 text-primary" /> Intent Profiler
          </CardTitle>
          <CardDescription>
            Advisory, ordinal intent hypotheses from bounded derived session evidence. It cannot
            score, route, approve or pay.
          </CardDescription>
        </div>
        {canRun ? (
          <Button
            size="sm"
            variant="outline"
            onClick={() => mutation.mutate()}
            disabled={mutation.isPending}
          >
            {mutation.isPending ? (
              <Loader2 className="h-3.5 w-3.5 animate-spin" />
            ) : (
              <Sparkles className="h-3.5 w-3.5" />
            )}
            Run intent profile
          </Button>
        ) : null}
      </CardHeader>
      <CardContent className="space-y-4">
        {query.isError ? (
          <ErrorState error={query.error} onRetry={() => void query.refetch()} />
        ) : query.isLoading ? (
          <div
            role="status"
            aria-label="Loading intent profile"
            className="h-24 animate-pulse rounded bg-muted"
          />
        ) : !latest || !analysis ? (
          <p className="text-sm text-muted-foreground">
            No intent profile has been recorded for this session.
            {canRun
              ? " Analysts can create an advisory profile."
              : " Analyst access is required."}
          </p>
        ) : (
          <>
            <div className="flex flex-wrap items-center gap-2">
              <Badge variant={confidenceVariant(analysis.confidence)}>
                {analysis.confidence} confidence
              </Badge>
              <Badge variant="outline">{latest.status}</Badge>
              <Badge variant={latest.ai_used ? "violet" : "muted"}>
                {latest.ai_used ? "LLM-assisted narrative" : "Deterministic narrative"}
              </Badge>
              {latest.model_name ? <Badge variant="outline">{latest.model_name}</Badge> : null}
              <span className="text-[11px] text-muted-foreground">
                {formatDateTime(latest.created_at)}
              </span>
            </div>

            <div className="rounded-lg border border-border bg-muted/20 p-3">
              <p className="text-sm font-semibold">{humanizeCode(analysis.primary_intent)}</p>
              <p className="mt-1 font-mono text-[11px] text-muted-foreground">
                {analysis.primary_intent}
              </p>
              <p className="mt-2 text-sm font-medium">{latest.bundle.narrative.headline}</p>
              <p className="mt-1 text-xs leading-5 text-muted-foreground">
                {latest.bundle.narrative.summary}
              </p>
              {latest.bundle.narrative.uncertainty_notes?.length ? (
                <ul className="mt-2 space-y-1 text-[11px] leading-5 text-muted-foreground">
                  {latest.bundle.narrative.uncertainty_notes.map((note, index) => (
                    <li key={`${note}-${index}`}>- {note}</li>
                  ))}
                </ul>
              ) : null}
            </div>

            <div className="grid gap-3 sm:grid-cols-2">
              <div>
                <p className="text-xs font-semibold uppercase tracking-wide text-muted-foreground">
                  Confidence basis
                </p>
                <div className="mt-1.5 flex flex-wrap gap-1">
                  {confidenceBasis.length ? (
                    confidenceBasis.map((reason) => (
                      <Badge key={reason} variant="outline" className="font-mono">
                        {reason}
                      </Badge>
                    ))
                  ) : (
                    <span className="text-sm text-muted-foreground">Not recorded</span>
                  )}
                </div>
              </div>
              <div>
                <p className="text-xs font-semibold uppercase tracking-wide text-muted-foreground">
                  Secondary hypotheses
                </p>
                <div className="mt-1.5 flex flex-wrap gap-1">
                  {secondaryIntents.length ? (
                    secondaryIntents.map((hypothesis) => (
                      <Badge key={hypothesis} variant="muted">
                        {humanizeCode(hypothesis)}
                      </Badge>
                    ))
                  ) : (
                    <span className="text-sm text-muted-foreground">None</span>
                  )}
                </div>
              </div>
            </div>

            <div className="space-y-2">
              <p className="text-xs font-semibold uppercase tracking-wide text-muted-foreground">
                Evidence references
              </p>
              <ul className="space-y-2">
                {evidence.map((reference, index) => (
                  <li
                    key={`${reference.source}-${reference.ref_id}-${index}`}
                    className="rounded-lg border border-border p-3"
                  >
                    <div className="flex flex-wrap items-center gap-2">
                      <ShieldAlert className="h-3.5 w-3.5 text-signal-restricted" />
                      <Badge variant="outline">{reference.source}</Badge>
                      <span className="font-mono text-[10px] text-muted-foreground">
                        {reference.ref_id}
                      </span>
                      <span className="text-[10px] text-muted-foreground">
                        {formatDateTime(reference.occurred_at)}
                      </span>
                    </div>
                    <p className="mt-1 text-[11px] leading-5 text-muted-foreground">
                      {reference.summary}
                    </p>
                    {reference.signal_codes?.length ? (
                      <div className="mt-1.5 flex flex-wrap gap-1">
                        {reference.signal_codes.map((code) => (
                          <span
                            key={code}
                            className="rounded bg-muted px-1.5 py-0.5 font-mono text-[10px]"
                          >
                            {code}
                          </span>
                        ))}
                      </div>
                    ) : null}
                  </li>
                ))}
              </ul>
            </div>

            <div className="space-y-1.5">
              <p className="text-xs font-semibold uppercase tracking-wide text-muted-foreground">
                Limitations
              </p>
              <ul className="space-y-1 text-[11px] leading-5 text-muted-foreground">
                {limitations.map((limitation, index) => (
                  <li key={`${limitation}-${index}`}>- {limitation}</li>
                ))}
              </ul>
            </div>

            <InfoNote tone="warning" title="Advisory only">
              This profile never changes risk scores, trust levels, routing, access or payment
              execution. Intent labels and confidence are ordinal and require human review.
            </InfoNote>
          </>
        )}
      </CardContent>
    </Card>
  );
}
