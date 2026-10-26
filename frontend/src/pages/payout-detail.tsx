import { useQuery } from "@tanstack/react-query";
import { ArrowLeft, ArrowUpRight, CircleDollarSign, FileLock2, RefreshCw, ShieldCheck } from "lucide-react";
import { Link, useParams } from "react-router-dom";
import { StatusBadge, TrustBadge } from "@/components/common/badges";
import { DataField } from "@/components/common/data-field";
import { ErrorState } from "@/components/common/error-state";
import { InfoNote } from "@/components/common/info-note";
import { DetailLoading } from "@/components/common/loading-state";
import { PageHeader } from "@/components/common/page-header";
import { RiskScoreRing } from "@/components/common/risk-score-ring";
import { Badge } from "@/components/ui/badge";
import { Button } from "@/components/ui/button";
import { Card, CardContent, CardDescription, CardHeader, CardTitle } from "@/components/ui/card";
import { api } from "@/lib/api";
import { useAuth } from "@/lib/auth";
import { formatDateTime, formatMoney, humanizeCode, titleCase } from "@/lib/format";
import { cn } from "@/lib/utils";

export function PayoutDetailPage() {
  const { payoutId = "" } = useParams();
  const { session } = useAuth();
  const query = useQuery({
    queryKey: ["payout", payoutId],
    queryFn: () => api.payout(session!, payoutId),
    enabled: Boolean(session && payoutId),
  });

  if (query.isLoading) return <DetailLoading />;
  if (query.isError) {
    return (
      <div className="space-y-4">
        <Button asChild variant="ghost" size="sm" className="-ml-2"><Link to="/payouts"><ArrowLeft className="h-4 w-4" /> Back to payouts</Link></Button>
        <ErrorState error={query.error} onRetry={() => void query.refetch()} />
      </div>
    );
  }
  if (!query.data) return null;
  const { payout, request, decision, provider, idempotency, session: payoutSession, incidents = [], evidence = { entries: [], seal: null }, step_up = { required: false, verified: false }, agent, timeline = [] } = query.data;
  const reasonCodes = decision.reason_codes ?? [];
  const riskSignals = decision.risk_signals ?? {};
  const signalWeights = decision.signal_weights ?? {};
  const evidenceEntries = evidence.entries ?? [];

  return (
    <div className="space-y-6">
      <div>
        <Button asChild variant="ghost" size="sm" className="-ml-2 mb-2"><Link to="/payouts"><ArrowLeft className="h-4 w-4" /> Back to ledger</Link></Button>
        <PageHeader
          eyebrow="Payout record"
          title={formatMoney(payout.amount, payout.currency)}
          description={
            <span className="flex flex-wrap items-center gap-2">
              <span className="font-mono text-xs">{payout.payout_id}</span>
              <StatusBadge status={payout.status} />
              <TrustBadge level={payout.trust_level} />
              {payout.reconciliation_required ? <Badge variant="warning">Reconciliation required</Badge> : null}
            </span>
          }
          actions={
            <Button variant="outline" size="sm" onClick={() => void query.refetch()} disabled={query.isFetching}>
              <RefreshCw className={cn("h-3.5 w-3.5", query.isFetching && "animate-spin")} /> Refresh
            </Button>
          }
        />
      </div>

      {payout.reconciliation_required ? (
        <InfoNote tone="danger" title="Execution outcome needs reconciliation">
          The gateway recorded that provider execution may have occurred without a confirmed response. Do not re-execute this payout from the console. Reconcile using the provider reference and idempotency record.
        </InfoNote>
      ) : null}

      <div className="grid gap-4 xl:grid-cols-3">
        <div className="space-y-4 xl:col-span-2">
          <Card>
            <CardHeader className="flex-row items-start justify-between gap-4 space-y-0">
              <div className="space-y-1.5">
                <CardTitle>Authoritative decision</CardTitle>
                <CardDescription>Persisted by the risk engine at evaluation time; not recomputed here.</CardDescription>
              </div>
              <RiskScoreRing score={decision.risk_score} size={96} label="Decision risk" className="shrink-0" />
            </CardHeader>
            <CardContent className="space-y-4">
              <div className="grid gap-4 sm:grid-cols-2 lg:grid-cols-4">
                <DataField label="Action"><StatusBadge status={decision.action} /></DataField>
                <DataField label="Routing">{humanizeCode(decision.routing_destination)}</DataField>
                <DataField label="Decision id" mono>{decision.decision_id}</DataField>
                <DataField label="Evaluated">{formatDateTime(decision.evaluated_at)}</DataField>
              </div>
              <div className="flex flex-wrap gap-1.5">
                {reasonCodes.length ? reasonCodes.map((code) => (
                  <span key={code} className="rounded-md border border-border bg-muted/50 px-1.5 py-0.5 font-mono text-[11px]">{code}</span>
                )) : <span className="text-sm text-muted-foreground">No reason codes recorded.</span>}
              </div>
              {Object.keys(riskSignals).length ? (
                <div className="rounded-lg border border-border">
                  <table className="w-full text-sm">
                    <caption className="sr-only">Risk signals for this decision</caption>
                    <thead><tr className="border-b border-border text-left text-[11px] uppercase tracking-wider text-muted-foreground"><th className="px-3 py-2 font-semibold">Signal</th><th className="px-3 py-2 font-semibold">Value</th><th className="px-3 py-2 text-right font-semibold">Weight</th></tr></thead>
                    <tbody>
                      {Object.entries(riskSignals).map(([name, value]) => (
                        <tr key={name} className="border-b border-border/60 last:border-0">
                          <td className="px-3 py-2 font-mono text-xs">{name}</td>
                          <td className="px-3 py-2 text-xs">{String(value)}</td>
                          <td className="px-3 py-2 text-right font-mono text-xs">{signalWeights[name] ?? "—"}</td>
                        </tr>
                      ))}
                    </tbody>
                  </table>
                </div>
              ) : null}
            </CardContent>
          </Card>

          <Card>
            <CardHeader>
              <CardTitle>Request & execution</CardTitle>
              <CardDescription>Provider data is the recorded gateway result.</CardDescription>
            </CardHeader>
            <CardContent className="space-y-5">
              <dl className="grid gap-4 sm:grid-cols-2">
                <DataField label="Recipient">{request.recipient_email}</DataField>
                <DataField label="Amount">{formatMoney(request.amount, request.currency)}</DataField>
                <DataField label="Reference">{request.reference_note ?? "—"}</DataField>
                <DataField label="Idempotency key" mono>{request.idempotency_key}</DataField>
                <DataField label="Provider">{humanizeCode(provider.name)}</DataField>
                <DataField label="Provider reference" mono>{provider.reference ?? "—"}</DataField>
                <DataField label="Executed at">{formatDateTime(provider.executed_at)}</DataField>
                <DataField label="Step-up">{step_up.required ? step_up.verified ? "Required and verified" : "Required, not verified" : "Not required"}</DataField>
              </dl>
              {Object.keys(provider.payload ?? {}).length ? (
                <details className="rounded-lg border border-border bg-muted/20">
                  <summary className="cursor-pointer px-3 py-2 text-xs font-medium">Recorded provider payload</summary>
                  <pre className="max-h-72 overflow-auto border-t border-border p-3 font-mono text-[11px] leading-5">{JSON.stringify(provider.payload ?? {}, null, 2)}</pre>
                </details>
              ) : null}
            </CardContent>
          </Card>

          {agent ? (
            <Card>
              <CardHeader>
                <CardTitle>Agent provenance</CardTitle>
                <CardDescription>This request was submitted through an AI agent authorization grant.</CardDescription>
              </CardHeader>
              <CardContent className="grid gap-4 sm:grid-cols-2">
                <DataField label="Agent">{agent.display_name}</DataField>
                <DataField label="Agent status"><StatusBadge status={agent.status} /></DataField>
                <DataField label="Grant" mono>{agent.grant_id ?? "—"}</DataField>
                <DataField label="Intent">{agent.intent ?? "—"}</DataField>
                <div className="sm:col-span-2"><Button asChild variant="outline" size="sm"><Link to={`/agents/${agent.agent_id}`}>Inspect agent registry <ArrowUpRight className="h-3.5 w-3.5" /></Link></Button></div>
              </CardContent>
            </Card>
          ) : null}
        </div>

        <div className="space-y-4">
          <Card>
            <CardHeader><CardTitle>Execution timeline</CardTitle><CardDescription>Derived from persisted gateway records.</CardDescription></CardHeader>
            <CardContent>
              <ol className="relative space-y-4 border-l border-border pl-5">
                {timeline.length ? timeline.map((item) => (
                  <li key={item.key} className="relative">
                    <span className="absolute -left-[1.45rem] top-1 h-2.5 w-2.5 rounded-full border-2 border-background bg-primary" aria-hidden="true" />
                    <p className="text-sm font-medium">{item.label}</p>
                    <div className="mt-0.5 flex flex-wrap items-center gap-2">
                      <StatusBadge status={item.status} />
                      <span className="text-[11px] text-muted-foreground">{formatDateTime(item.occurred_at)}</span>
                    </div>
                    {item.detail ? <p className="mt-1 text-xs text-muted-foreground">{item.detail}</p> : null}
                  </li>
                )) : <li className="text-sm text-muted-foreground">No timeline entries recorded.</li>}
              </ol>
            </CardContent>
          </Card>

          <Card>
            <CardHeader><CardTitle>Session snapshot</CardTitle></CardHeader>
            <CardContent className="space-y-4">
              <div className="flex items-center justify-between gap-2">
                <Link to={`/sessions/${payoutSession.session_id}`} className="font-mono text-xs text-primary hover:underline">{payoutSession.session_id}</Link>
                <TrustBadge level={payoutSession.trust_level} />
              </div>
              <dl className="grid grid-cols-2 gap-3">
                <DataField label="Status"><StatusBadge status={payoutSession.status} /></DataField>
                <DataField label="Risk score">{payoutSession.risk_score.toFixed(1)}</DataField>
                <DataField label="Device" mono>{payoutSession.device_fingerprint ?? "—"}</DataField>
                <DataField label="IP" mono>{payoutSession.ip_address ?? "—"}</DataField>
              </dl>
            </CardContent>
          </Card>

          <Card>
            <CardHeader><CardTitle className="flex items-center gap-2"><ShieldCheck className="h-4 w-4 text-primary" /> Evidence</CardTitle></CardHeader>
            <CardContent className="space-y-3">
              {evidence.seal ? (
                <div className="space-y-2">
                  <p className="text-sm">Sealed range <span className="font-mono text-xs">{evidence.seal.start_seq}–{evidence.seal.end_seq}</span></p>
                  <p className="text-[11px] text-muted-foreground">{formatDateTime(evidence.seal.sealed_at)}</p>
                  <Button asChild variant="outline" size="sm" className="w-full"><Link to={`/evidence/${evidence.seal.seal_id}`}><FileLock2 className="h-3.5 w-3.5" /> Open seal</Link></Button>
                </div>
              ) : <p className="text-sm text-muted-foreground">No evidence seal covers this payout.</p>}
              <p className="text-[11px] text-muted-foreground">{evidenceEntries.length} chain entries linked to this payout.</p>
            </CardContent>
          </Card>

          {incidents.length ? (
            <Card>
              <CardHeader><CardTitle>Related incidents</CardTitle></CardHeader>
              <CardContent className="space-y-2">
                {incidents.map((incident) => (
                  <Link key={incident.incident_id} to={`/incidents/${incident.incident_id}`} className="block rounded-lg border border-border p-3 hover:bg-accent/50">
                    <div className="flex items-center justify-between gap-2"><p className="truncate text-sm font-medium">{incident.title}</p><StatusBadge status={incident.severity} /></div>
                    <p className="mt-1 text-[11px] text-muted-foreground">{titleCase(incident.status)} · {formatDateTime(incident.created_at)}</p>
                  </Link>
                ))}
              </CardContent>
            </Card>
          ) : null}

          {idempotency ? (
            <Card>
              <CardHeader><CardTitle className="flex items-center gap-2"><CircleDollarSign className="h-4 w-4 text-primary" /> Idempotency</CardTitle></CardHeader>
              <CardContent className="space-y-3">
                <DataField label="Status"><StatusBadge status={idempotency.status} /></DataField>
                <DataField label="Request hash" mono>{idempotency.request_hash}</DataField>
                <DataField label="Response code" mono>{idempotency.response_code ?? "—"}</DataField>
                <DataField label="Expires">{formatDateTime(idempotency.expires_at)}</DataField>
              </CardContent>
            </Card>
          ) : null}
        </div>
      </div>
    </div>
  );
}
