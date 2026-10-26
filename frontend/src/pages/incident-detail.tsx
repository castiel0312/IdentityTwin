import { useQuery } from "@tanstack/react-query";
import { ArrowLeft, FileLock2, GitBranch, RefreshCw, Siren } from "lucide-react";
import { Link, useParams } from "react-router-dom";
import { SeverityBadge, StatusBadge } from "@/components/common/badges";
import { DataField } from "@/components/common/data-field";
import { ErrorState } from "@/components/common/error-state";
import { InfoNote } from "@/components/common/info-note";
import { DetailLoading } from "@/components/common/loading-state";
import { PageHeader } from "@/components/common/page-header";
import { RiskMeter } from "@/components/common/risk-meter";
import { RiskScoreRing } from "@/components/common/risk-score-ring";
import { IncidentActions } from "@/features/incidents/incident-actions";
import { Badge } from "@/components/ui/badge";
import { Button } from "@/components/ui/button";
import { Card, CardContent, CardDescription, CardHeader, CardTitle } from "@/components/ui/card";
import { api } from "@/lib/api";
import { useAuth } from "@/lib/auth";
import { formatDateTime, humanizeCode, relativeTime } from "@/lib/format";
import { cn } from "@/lib/utils";

export function IncidentDetailPage() {
  const { incidentId = "" } = useParams();
  const { session } = useAuth();
  const incidentQuery = useQuery({ queryKey: ["incident", incidentId], queryFn: () => api.incident(session!, incidentId), enabled: Boolean(session && incidentId) });
  const sealQuery = useQuery({ queryKey: ["incident-seal", incidentId], queryFn: () => api.incidentSeal(session!, incidentId), enabled: Boolean(session && incidentId) });
  const timelineQuery = useQuery({ queryKey: ["incident-timeline", incidentId], queryFn: () => api.incidentTimeline(session!, incidentId), enabled: Boolean(session && incidentId) });
  const traceQuery = useQuery({ queryKey: ["incident-trace", incidentId], queryFn: () => api.incidentAttackTrace(session!, incidentId), enabled: Boolean(session && incidentId) });

  if (incidentQuery.isLoading) return <DetailLoading />;
  if (incidentQuery.isError) return <div className="space-y-4"><Button asChild variant="ghost" size="sm" className="-ml-2"><Link to="/incidents"><ArrowLeft className="h-4 w-4" /> Back to incidents</Link></Button><ErrorState error={incidentQuery.error} onRetry={() => void incidentQuery.refetch()} /></div>;
  if (!incidentQuery.data) return null;
  const incident = incidentQuery.data;
  const seal = sealQuery.data?.seal ?? null;

  return (
    <div className="space-y-6">
      <div>
        <Button asChild variant="ghost" size="sm" className="-ml-2 mb-2"><Link to="/incidents"><ArrowLeft className="h-4 w-4" /> Back to incidents</Link></Button>
        <PageHeader
          eyebrow="Incident review"
          title={incident.title}
          description={<span className="flex flex-wrap items-center gap-2"><SeverityBadge severity={incident.severity} /><StatusBadge status={incident.status} /><RiskMeter score={incident.risk_score} /><span className="font-mono text-[11px] text-muted-foreground">{incident.incident_id}</span></span>}
          actions={<Button variant="outline" size="sm" onClick={() => { void incidentQuery.refetch(); void sealQuery.refetch(); void timelineQuery.refetch(); void traceQuery.refetch(); }} disabled={incidentQuery.isFetching || sealQuery.isFetching}><RefreshCw className={cn("h-3.5 w-3.5", incidentQuery.isFetching && "animate-spin")} /> Refresh</Button>}
        />
      </div>

      <div className="grid gap-4 xl:grid-cols-3">
        <div className="space-y-4 xl:col-span-2">
          <Card>
            <CardHeader><CardTitle>Incident summary</CardTitle><CardDescription>Recorded at detection; not recalculated by the console.</CardDescription></CardHeader>
            <CardContent className="space-y-4">
              <p className="text-sm leading-6 text-muted-foreground">{incident.description}</p>
              <dl className="grid gap-4 sm:grid-cols-2">
                <DataField label="Trigger reason"><Badge variant="outline" className="font-mono">{incident.trigger_reason}</Badge></DataField>
                <DataField label="Severity"><SeverityBadge severity={incident.severity} /></DataField>
                <DataField label="Opened">{formatDateTime(incident.created_at)}</DataField>
                <DataField label="Updated">{formatDateTime(incident.updated_at)}</DataField>
                <DataField label="Resolved">{formatDateTime(incident.resolved_at)}</DataField>
                <DataField label="Session">{incident.session_id ? <Link className="font-mono text-xs text-primary hover:underline" to={`/sessions/${incident.session_id}`}>{incident.session_id}</Link> : "No session bound"}</DataField>
              </dl>
              {Object.keys(incident.evidence_summary).length ? (
                <details className="rounded-lg border border-border bg-muted/20"><summary className="cursor-pointer px-3 py-2 text-xs font-medium">Recorded evidence summary</summary><pre className="max-h-72 overflow-auto border-t border-border p-3 font-mono text-[11px] leading-5">{JSON.stringify(incident.evidence_summary, null, 2)}</pre></details>
              ) : null}
            </CardContent>
          </Card>

          <IncidentActions incidentId={incidentId} />

          <Card>
            <CardHeader><CardTitle>Evidence timeline</CardTitle><CardDescription>Chain entries linked to this incident's session. Timestamps and hashes are as recorded.</CardDescription></CardHeader>
            <CardContent>
              {timelineQuery.isError ? <ErrorState error={timelineQuery.error} onRetry={() => void timelineQuery.refetch()} /> : timelineQuery.isLoading ? <div className="h-32 animate-pulse rounded bg-muted" /> : !timelineQuery.data?.timeline.length ? <p className="py-8 text-center text-sm text-muted-foreground">No evidence-linked timeline entries were found.</p> : (
                <ol className="relative space-y-4 border-l border-border pl-5">
                  {timelineQuery.data.timeline.map((item, index) => (
                    <li key={`${item.evidence_seq}-${index}`} className="relative">
                      <span className="absolute -left-[1.45rem] top-1 h-2.5 w-2.5 rounded-full border-2 border-background bg-primary" aria-hidden="true" />
                      <div className="flex flex-wrap items-center gap-2"><p className="text-sm font-medium">{humanizeCode(item.type)}</p><Badge variant={item.plane === "honey" ? "violet" : "muted"}>{item.plane === "honey" ? "Synthetic honey plane" : "Real plane"}</Badge>{item.trust_level ? <StatusBadge status={item.trust_level} /> : null}</div>
                      <p className="mt-0.5 text-xs text-muted-foreground">{item.summary}</p>
                      <p className="mt-1 font-mono text-[10px] text-muted-foreground">seq {item.evidence_seq} · {item.evidence_hash.slice(0, 16)}… · {formatDateTime(item.ts)}</p>
                    </li>
                  ))}
                </ol>
              )}
            </CardContent>
          </Card>

          <Card>
            <CardHeader><CardTitle className="flex items-center gap-2"><GitBranch className="h-4 w-4 text-primary" /> Attack trace</CardTitle><CardDescription>Derived from evidence payloads. Absence of a node does not prove absence of activity.</CardDescription></CardHeader>
            <CardContent>
              {traceQuery.isError ? <ErrorState error={traceQuery.error} onRetry={() => void traceQuery.refetch()} /> : traceQuery.isLoading ? <div className="h-32 animate-pulse rounded bg-muted" /> : !traceQuery.data?.nodes.length ? <p className="text-sm text-muted-foreground">No trace nodes were available.</p> : (
                <div className="space-y-4">
                  <div className="flex flex-wrap gap-2">{traceQuery.data.nodes.map((node) => <div key={node.id} className="rounded-lg border border-border bg-muted/20 p-2.5"><p className="text-[10px] font-semibold uppercase tracking-wider text-muted-foreground">{node.type}</p><p className="mt-0.5 max-w-48 break-all text-xs">{node.label}</p></div>)}</div>
                  <ul className="space-y-1.5 border-t border-border pt-3 text-xs text-muted-foreground">{traceQuery.data.edges.map((edge, index) => <li key={`${edge.from}-${edge.to}-${index}`} className="flex flex-wrap items-center gap-1.5"><span className="rounded bg-muted px-1 py-0.5 font-mono text-[10px]">{edge.from}</span><span>—{edge.relation}→</span><span className="rounded bg-muted px-1 py-0.5 font-mono text-[10px]">{edge.to}</span></li>)}</ul>
                </div>
              )}
            </CardContent>
          </Card>
        </div>

        <div className="space-y-4">
          <Card>
            <CardHeader className="flex-row items-start justify-between gap-3 space-y-0"><div className="space-y-1.5"><CardTitle>Status & containment</CardTitle><CardDescription>Current recorded state.</CardDescription></div><RiskScoreRing score={incident.risk_score} size={92} label="Risk" className="shrink-0" /></CardHeader>
            <CardContent className="space-y-3">
              <DataField label="Current status"><StatusBadge status={incident.status} /></DataField>
              <DataField label="Severity"><SeverityBadge severity={incident.severity} /></DataField>
              <p className="text-[11px] leading-5 text-muted-foreground">Containment may already have revoked the session. No action on this page can restore a session or execute a payout.</p>
            </CardContent>
          </Card>

          <Card>
            <CardHeader><CardTitle className="flex items-center gap-2"><FileLock2 className="h-4 w-4 text-primary" /> Evidence seal</CardTitle><CardDescription>Seal status as reported by the backend.</CardDescription></CardHeader>
            <CardContent className="space-y-3">
              {sealQuery.isError ? <ErrorState error={sealQuery.error} onRetry={() => void sealQuery.refetch()} /> : sealQuery.isLoading ? <div className="h-16 animate-pulse rounded bg-muted" /> : seal ? (
                <>
                  <p className="text-sm">Sealed sequence range <span className="font-mono text-xs">{seal.start_seq}–{seal.end_seq}</span></p>
                  <p className="break-all font-mono text-[10px] text-muted-foreground">{seal.head_hash}</p>
                  <p className="text-[11px] text-muted-foreground">{formatDateTime(seal.sealed_at)}</p>
                  <Button asChild variant="outline" size="sm" className="w-full"><Link to={`/evidence/${seal.seal_id}`}>Verify seal range</Link></Button>
                </>
              ) : sealQuery.data ? <InfoNote tone="warning">This incident has no seal. Absence of a seal is not evidence of tampering; it means no sealed range covers it yet.</InfoNote> : null}
            </CardContent>
          </Card>

          <Card>
            <CardHeader><CardTitle className="flex items-center gap-2"><Siren className="h-4 w-4 text-signal-isolated" /> Response guidance</CardTitle></CardHeader>
            <CardContent className="space-y-2 text-xs leading-5 text-muted-foreground">
              <p>1. Confirm tenant scope and session linkage.</p>
              <p>2. Review evidence timeline and attack trace.</p>
              <p>3. Record an authorization-gated action with notes.</p>
              <p>4. Verify the evidence seal separately; it proves range consistency, not database immutability.</p>
            </CardContent>
          </Card>
          <p className="text-[11px] text-muted-foreground">Opened {relativeTime(incident.created_at)} · Last updated {relativeTime(incident.updated_at)}</p>
        </div>
      </div>
    </div>
  );
}
