import { useQuery } from "@tanstack/react-query";
import { ArrowLeft, RefreshCw, ShieldCheck } from "lucide-react";
import { Link, useParams } from "react-router-dom";
import { StatusBadge, TrustBadge } from "@/components/common/badges";
import { DataField } from "@/components/common/data-field";
import { ErrorState } from "@/components/common/error-state";
import { Limitations } from "@/components/common/limitations";
import { DetailLoading } from "@/components/common/loading-state";
import { PageHeader } from "@/components/common/page-header";
import { RiskMeter } from "@/components/common/risk-meter";
import { RiskScoreRing } from "@/components/common/risk-score-ring";
import { Badge } from "@/components/ui/badge";
import { Button } from "@/components/ui/button";
import { Card, CardContent, CardDescription, CardHeader, CardTitle } from "@/components/ui/card";
import { api } from "@/lib/api";
import { useAuth } from "@/lib/auth";
import { formatDateTime, humanizeCode, relativeTime } from "@/lib/format";
import { cn } from "@/lib/utils";

export function RiskDecisionPage() {
  const { decisionId = "" } = useParams();
  const { session } = useAuth();
  const query = useQuery({ queryKey: ["risk-decision", decisionId], queryFn: () => api.riskDecision(session!, decisionId), enabled: Boolean(session && decisionId) });
  if (query.isLoading) return <DetailLoading />;
  if (query.isError) return <div className="space-y-4"><Button asChild variant="ghost" size="sm" className="-ml-2"><Link to="/risk"><ArrowLeft className="h-4 w-4" /> Back to risk</Link></Button><ErrorState error={query.error} onRetry={() => void query.refetch()} /></div>;
  if (!query.data) return null;
  const { decision, session: decisionSession, payout, contributions = [], sequence_markers = [], twin, limitations = [] } = query.data;
  return (
    <div className="space-y-6">
      <div>
        <Button asChild variant="ghost" size="sm" className="-ml-2 mb-2"><Link to="/risk"><ArrowLeft className="h-4 w-4" /> Back to decisions</Link></Button>
        <PageHeader eyebrow="Risk decision" title={decision.decision_id} description={<span className="flex flex-wrap items-center gap-2"><TrustBadge level={decision.trust_level} /><StatusBadge status={decision.action} /><RiskMeter score={decision.risk_score} /><span className="text-xs text-muted-foreground">{humanizeCode(decision.routing_destination)}</span></span>} actions={<Button variant="outline" size="sm" onClick={() => void query.refetch()} disabled={query.isFetching}><RefreshCw className={cn("h-3.5 w-3.5", query.isFetching && "animate-spin")} /> Refresh</Button>} />
      </div>

      <div className="grid gap-4 xl:grid-cols-3">
        <div className="space-y-4 xl:col-span-2">
          <Card>
            <CardHeader><CardTitle>Signal contributions</CardTitle><CardDescription>These are the stored contributions for this decision.</CardDescription></CardHeader>
            <CardContent>
              {contributions.length ? <ul className="divide-y divide-border">{contributions.map((item, index) => (
                <li key={`${item.name}-${index}`} className="flex items-start justify-between gap-4 py-3 first:pt-0 last:pb-0">
                  <div className="min-w-0"><div className="flex flex-wrap items-center gap-2"><p className="text-sm font-medium">{item.name}</p><Badge variant="outline" className="font-mono text-[10px]">{item.reason_code}</Badge></div><p className="mt-0.5 text-xs text-muted-foreground">{item.kind}{item.occurred_at ? ` · ${relativeTime(item.occurred_at)}` : ""}{Object.keys(item.detail ?? {}).length ? ` · ${JSON.stringify(item.detail)}` : ""}</p></div>
                  <span className="shrink-0 font-mono text-sm tabular-nums">+{item.points.toFixed(1)}</span>
                </li>
              ))}</ul> : <p className="text-sm text-muted-foreground">No contributions were persisted for this decision record.</p>}
            </CardContent>
          </Card>

          <Card>
            <CardHeader><CardTitle>Session at decision time</CardTitle></CardHeader>
            <CardContent className="grid gap-4 sm:grid-cols-2">
              <DataField label="Session"><Link className="font-mono text-xs text-primary hover:underline" to={`/sessions/${decisionSession.session_id}`}>{decisionSession.session_id}</Link></DataField>
              <DataField label="Status"><StatusBadge status={decisionSession.status} /></DataField>
              <DataField label="Trust"><TrustBadge level={decisionSession.trust_level} /></DataField>
              <DataField label="Risk score">{decisionSession.risk_score.toFixed(1)}</DataField>
              <DataField label="Device" mono>{decisionSession.device_fingerprint ?? "—"}</DataField>
              <DataField label="IP" mono>{decisionSession.ip_address ?? "—"}</DataField>
              <DataField label="Evaluated">{formatDateTime(decision.evaluated_at)}</DataField>
              <DataField label="Payout">{payout ? <Link className="font-mono text-xs text-primary hover:underline" to={`/payouts/${payout.payout_id}`}>{payout.payout_id}</Link> : "No payout linked"}</DataField>
            </CardContent>
          </Card>

          <Card>
            <CardHeader><CardTitle>Sequence markers</CardTitle><CardDescription>Observed ordering within the server's configured window.</CardDescription></CardHeader>
            <CardContent>{sequence_markers.length ? <div className="space-y-3">{sequence_markers.map((marker, index) => <div key={`${marker.sequence_type}-${index}`} className="rounded-lg border border-border p-3"><p className="text-sm font-medium">{marker.sequence_type}</p><p className="font-mono text-[10px] text-muted-foreground">{marker.occurred_at} · {marker.recipient_hash ?? "no recipient hash"}</p><p className="mt-1 text-xs text-muted-foreground">recipient {marker.recipient_hash ?? "not recorded"}</p></div>)}</div> : <p className="text-sm text-muted-foreground">No sequence markers were recorded.</p>}</CardContent>
          </Card>
        </div>

        <div className="space-y-4">
          <Card>
            <CardHeader className="flex-row items-start justify-between gap-3 space-y-0"><div className="space-y-1.5"><CardTitle>Decision facts</CardTitle><CardDescription>Stored at evaluation time.</CardDescription></div><RiskScoreRing score={decision.risk_score} size={92} label="Risk" className="shrink-0" /></CardHeader>
            <CardContent className="space-y-3">
              <DataField label="Action"><StatusBadge status={decision.action} /></DataField>
              <DataField label="Routing">{humanizeCode(decision.routing_destination)}</DataField>
              <DataField label="Reason codes"><div className="flex flex-wrap gap-1">{(decision.reason_codes ?? []).length ? (decision.reason_codes ?? []).map((code) => <span key={code} className="rounded bg-muted px-1.5 py-0.5 font-mono text-[10px]">{code}</span>) : "None"}</div></DataField>
              <DataField label="Risk signals"><div className="space-y-1">{Object.entries(decision.risk_signals ?? {}).map(([name, value]) => <div key={name} className="flex justify-between gap-2 text-xs"><span className="font-mono">{name}</span><span>{String(value)}</span></div>)}</div></DataField>
            </CardContent>
          </Card>
          {twin ? (
            <Card>
              <CardHeader><CardTitle className="flex items-center gap-2"><ShieldCheck className="h-4 w-4 text-primary" /> Twin comparison</CardTitle><CardDescription>{twin.is_provisional ? "Provisional baseline" : "Established baseline"} · {twin.sample_count} samples</CardDescription></CardHeader>
              <CardContent className="grid grid-cols-2 gap-3"><DataField label="Devices">{twin.confirmed_device_count}</DataField><DataField label="Locations">{twin.confirmed_location_count}</DataField><DataField label="Payees">{twin.confirmed_payee_count}</DataField><DataField label="Pending">{twin.pending_payee_count}</DataField></CardContent>
            </Card>
          ) : null}
          <Limitations notes={limitations} />
        </div>
      </div>
    </div>
  );
}
