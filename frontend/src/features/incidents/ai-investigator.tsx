import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { Bot, Loader2, ShieldAlert, Sparkles } from "lucide-react";
import { toast } from "sonner";
import { ErrorState } from "@/components/common/error-state";
import { InfoNote } from "@/components/common/info-note";
import { Badge } from "@/components/ui/badge";
import { Button } from "@/components/ui/button";
import { Card, CardContent, CardDescription, CardHeader, CardTitle } from "@/components/ui/card";
import { api, ApiError } from "@/lib/api";
import { useAuth } from "@/lib/auth";
import { formatDateTime, humanizeCode } from "@/lib/format";

export function AiInvestigator({ incidentId }: { incidentId: string }) {
  const { session } = useAuth();
  const queryClient = useQueryClient();
  const canRun = session?.role === "analyst" || session?.role === "admin";

  const query = useQuery({
    queryKey: ["incident-investigations", incidentId],
    queryFn: () => api.listIncidentInvestigations(session!, incidentId),
    enabled: Boolean(session && incidentId),
  });

  const mutation = useMutation({
    mutationFn: () => api.createIncidentInvestigation(session!, incidentId, { use_llm: true }),
    onSuccess: (result) => {
      toast.success(
        result.status === "FALLBACK"
          ? "Investigation recorded with deterministic fallback narrative."
          : "Investigation recorded.",
      );
      void queryClient.invalidateQueries({ queryKey: ["incident-investigations", incidentId] });
    },
    onError: (cause) => {
      toast.error(
        cause instanceof ApiError
          ? `${cause.code}: ${cause.message}`
          : cause instanceof Error
            ? cause.message
            : "The investigation could not be created.",
      );
    },
  });

  const latest = query.data?.items[0];

  return (
    <Card>
      <CardHeader className="flex-row items-start justify-between gap-3 space-y-0">
        <div className="space-y-1.5">
          <CardTitle className="flex items-center gap-2">
            <Bot className="h-4 w-4 text-primary" /> AI Investigator
          </CardTitle>
          <CardDescription>
            Read-only advisory analysis over redacted deterministic evidence. It cannot score,
            route, approve or pay.
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
            Run investigation
          </Button>
        ) : null}
      </CardHeader>
      <CardContent className="space-y-4">
        {query.isError ? (
          <ErrorState error={query.error} onRetry={() => void query.refetch()} />
        ) : query.isLoading ? (
          <div
            role="status"
            aria-label="Loading investigation"
            className="h-24 animate-pulse rounded bg-muted"
          />
        ) : !latest ? (
          <p className="text-sm text-muted-foreground">
            No investigation has been run for this incident.
            {canRun ? " Analysts can run a read-only investigation." : " Analyst access is required."}
          </p>
        ) : (
          <>
            <div className="flex flex-wrap items-center gap-2">
              <Badge variant={latest.ai_used ? "violet" : "muted"}>
                {latest.ai_used ? "LLM-assisted narrative" : "Deterministic narrative"}
              </Badge>
              <Badge variant="outline">{latest.status}</Badge>
              {latest.model_name ? <Badge variant="outline">{latest.model_name}</Badge> : null}
              <span className="text-[11px] text-muted-foreground">
                {formatDateTime(latest.created_at)}
              </span>
            </div>

            <div className="rounded-lg border border-border bg-muted/20 p-3">
              <p className="text-sm font-semibold">{latest.bundle.narrative.headline}</p>
              <p className="mt-1 text-xs leading-5 text-muted-foreground">
                {latest.bundle.narrative.summary}
              </p>
              <p className="mt-2 text-xs leading-5">{latest.bundle.narrative.why_suspicious}</p>
            </div>

            <div className="space-y-2">
              <p className="text-xs font-semibold uppercase tracking-wide text-muted-foreground">
                Findings
              </p>
              <ul className="space-y-2">
                {(latest.bundle.findings ?? []).map((finding) => (
                  <li key={finding.finding_id} className="rounded-lg border border-border p-3">
                    <div className="flex flex-wrap items-center gap-2">
                      <ShieldAlert className="h-3.5 w-3.5 text-signal-isolated" />
                      <p className="text-xs font-medium">{finding.title}</p>
                      <Badge variant="outline">{finding.severity}</Badge>
                      <span className="font-mono text-[10px] text-muted-foreground">
                        {humanizeCode(finding.finding_type)}
                      </span>
                    </div>
                    <p className="mt-1 text-[11px] leading-5 text-muted-foreground">
                      {finding.explanation}
                    </p>
                  </li>
                ))}
              </ul>
            </div>

            <div className="space-y-2">
              <p className="text-xs font-semibold uppercase tracking-wide text-muted-foreground">
                Advisory recommendations
              </p>
              <ul className="space-y-1.5 text-xs">
                {(latest.bundle.recommendations ?? []).map((item, index) => (
                  <li key={`${item.action}-${index}`} className="flex gap-2">
                    <Badge variant="muted">{item.priority}</Badge>
                    <span>
                      <span className="font-medium">{item.action}</span>{" "}
                      <span className="text-muted-foreground">{item.rationale}</span>
                    </span>
                  </li>
                ))}
              </ul>
            </div>

            <InfoNote tone="warning" title="Advisory only">
              Every recommendation requires human approval. This report never changes risk scores,
              trust levels, routing, access or payment execution.
            </InfoNote>
          </>
        )}
      </CardContent>
    </Card>
  );
}
