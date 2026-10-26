import { useQuery } from "@tanstack/react-query";
import { ArrowLeft, Fingerprint, KeyRound, Link2, RefreshCw, ShieldCheck, Sparkles } from "lucide-react";
import { Link, useParams } from "react-router-dom";
import { StatusBadge, TrustBadge } from "@/components/common/badges";
import { DataField } from "@/components/common/data-field";
import { ErrorState } from "@/components/common/error-state";
import { InfoNote } from "@/components/common/info-note";
import { DetailLoading } from "@/components/common/loading-state";
import { PageHeader } from "@/components/common/page-header";
import { RiskMeter } from "@/components/common/risk-meter";
import { RiskScoreRing } from "@/components/common/risk-score-ring";
import { Badge } from "@/components/ui/badge";
import { Button } from "@/components/ui/button";
import { Card, CardContent, CardDescription, CardHeader, CardTitle } from "@/components/ui/card";
import { Tabs, TabsContent, TabsList, TabsTrigger } from "@/components/ui/tabs";
import { api } from "@/lib/api";
import { useAuth } from "@/lib/auth";
import { formatDateTime, formatMoney, humanizeCode, relativeTime } from "@/lib/format";
import { cn } from "@/lib/utils";

export function SessionDetailPage() {
  const { sessionId = "" } = useParams();
  const { session } = useAuth();
  const query = useQuery({
    queryKey: ["session-activity", sessionId],
    queryFn: () => api.sessionActivity(session!, sessionId),
    enabled: Boolean(session && sessionId),
  });

  if (query.isLoading) return <DetailLoading />;
  if (query.isError) {
    return <div className="space-y-4"><Button asChild variant="ghost" size="sm" className="-ml-2"><Link to="/sessions"><ArrowLeft className="h-4 w-4" /> Back to sessions</Link></Button><ErrorState error={query.error} onRetry={() => void query.refetch()} /></div>;
  }
  if (!query.data) return null;
  const { session: identitySession, events = [], payouts = [], incidents = [], risk_ledger, sequences, canaries = [], devices = [], locations = [], twin } = query.data;
  const ledger = risk_ledger as NonNullable<typeof risk_ledger>;
  const contributions = ledger.contributions ?? [];
  const latchedSignals = ledger.latched_signals ?? [];
  const currentScore = ledger.current_score ?? 0;
  const rawPoints = ledger.raw_points_sum ?? 0;
  const decayedPoints = ledger.decay_points_total ?? 0;
  const canaryPoints = ledger.canary_points ?? 0;
  const markers = sequences?.markers ?? [];

  return (
    <div className="space-y-6">
      <div>
        <Button asChild variant="ghost" size="sm" className="-ml-2 mb-2"><Link to="/sessions"><ArrowLeft className="h-4 w-4" /> Back to sessions</Link></Button>
        <PageHeader
          eyebrow="Session investigation"
          title={identitySession.session_id}
          description={<span className="flex flex-wrap items-center gap-2"><TrustBadge level={identitySession.trust_level} /><StatusBadge status={identitySession.status} /><RiskMeter score={identitySession.risk_score} /><Link to={`/identities/${identitySession.user_id}`} className="text-xs text-primary hover:underline">Identity {identitySession.user_id.slice(0, 8)}…</Link></span>}
          actions={<Button variant="outline" size="sm" onClick={() => void query.refetch()} disabled={query.isFetching}><RefreshCw className={cn("h-3.5 w-3.5", query.isFetching && "animate-spin")} /> Refresh</Button>}
        />
      </div>

      <div className="grid gap-4 sm:grid-cols-2 xl:grid-cols-4">
        <Card className="p-4"><p className="text-[11px] uppercase tracking-wider text-muted-foreground">Device</p><p className="mt-1 break-all font-mono text-xs">{identitySession.device_fingerprint ?? "Not recorded"}</p></Card>
        <Card className="p-4"><p className="text-[11px] uppercase tracking-wider text-muted-foreground">IP address</p><p className="mt-1 font-mono text-xs">{identitySession.ip_address ?? "Not recorded"}</p></Card>
        <Card className="p-4"><p className="text-[11px] uppercase tracking-wider text-muted-foreground">Last activity</p><p className="mt-1 text-sm">{relativeTime(identitySession.last_activity_at)}</p><p className="text-[10px] text-muted-foreground">{formatDateTime(identitySession.last_activity_at)}</p></Card>
        <Card className="p-4"><p className="text-[11px] uppercase tracking-wider text-muted-foreground">Risk score</p><p className="mt-1 text-xl font-semibold">{identitySession.risk_score.toFixed(1)}</p><RiskMeter score={identitySession.risk_score} className="mt-1" /></Card>
      </div>

      <Tabs defaultValue="activity">
        <TabsList className="flex h-auto flex-wrap"><TabsTrigger value="activity">Activity</TabsTrigger><TabsTrigger value="risk">Risk ledger</TabsTrigger><TabsTrigger value="sequences">Sequences</TabsTrigger><TabsTrigger value="twin">Twin & canaries</TabsTrigger></TabsList>

        <TabsContent value="activity" className="space-y-4">
          <div className="grid gap-4 xl:grid-cols-3">
            <Card className="xl:col-span-2">
              <CardHeader><CardTitle>Recorded events</CardTitle><CardDescription>Newest first, bounded by the investigation projection.</CardDescription></CardHeader>
              <CardContent>
                {events.length === 0 ? <p className="py-8 text-center text-sm text-muted-foreground">No events recorded for this session.</p> : (
                  <ol className="relative space-y-4 border-l border-border pl-5">
                    {events.map((event) => (
                      <li key={event.event_id} className="relative">
                        <span className="absolute -left-[1.45rem] top-1 h-2.5 w-2.5 rounded-full border-2 border-background bg-primary" aria-hidden="true" />
                        <div className="flex flex-wrap items-center gap-2"><p className="text-sm font-medium">{humanizeCode(event.event_type)}</p><Badge variant="outline" className="font-mono text-[10px]">{event.action}</Badge></div>
                        <p className="text-[11px] text-muted-foreground">{formatDateTime(event.occurred_at)} · server received {relativeTime(event.server_received_at)}</p>
                        <p className="mt-1 font-mono text-[10px] text-muted-foreground">{event.device_id ?? "no device"} · {event.ip_address ?? "no ip"}</p>
                        {Object.keys(event.metadata ?? {}).length ? <details className="mt-1"><summary className="cursor-pointer text-[11px] text-primary">Metadata</summary><pre className="mt-1 overflow-auto rounded bg-muted/40 p-2 font-mono text-[10px]">{JSON.stringify(event.metadata ?? {}, null, 2)}</pre></details> : null}
                      </li>
                    ))}
                  </ol>
                )}
              </CardContent>
            </Card>
            <div className="space-y-4">
              <Card>
                <CardHeader><CardTitle>Related payouts</CardTitle></CardHeader>
                <CardContent className="space-y-2">
                  {payouts.length ? payouts.map((payout) => (
                    <Link key={payout.payout_id} to={`/payouts/${payout.payout_id}`} className="block rounded-lg border border-border p-2.5 hover:bg-accent/50">
                      <div className="flex items-center justify-between gap-2"><span className="font-mono text-[11px]">{formatMoney(payout.amount, payout.currency)}</span><StatusBadge status={payout.status} /></div>
                      <p className="mt-1 truncate text-[11px] text-muted-foreground">{payout.recipient_email}</p>
                    </Link>
                  )) : <p className="text-sm text-muted-foreground">No payouts.</p>}
                </CardContent>
              </Card>
              <Card>
                <CardHeader><CardTitle>Incidents</CardTitle></CardHeader>
                <CardContent className="space-y-2">
                  {incidents.length ? incidents.map((incident) => (
                    <Link key={incident.incident_id} to={`/incidents/${incident.incident_id}`} className="block rounded-lg border border-border p-2.5 hover:bg-accent/50"><div className="flex items-center justify-between gap-2"><p className="truncate text-xs font-medium">{incident.title}</p><StatusBadge status={incident.severity} /></div><p className="mt-1 text-[10px] text-muted-foreground">{incident.status} · {relativeTime(incident.created_at)}</p></Link>
                  )) : <p className="text-sm text-muted-foreground">No incidents linked.</p>}
                </CardContent>
              </Card>
            </div>
          </div>
        </TabsContent>

        <TabsContent value="risk" className="space-y-4">
          <div className="grid gap-4 xl:grid-cols-[minmax(0,19rem)_minmax(0,1fr)]">
            <Card className="flex items-center justify-center p-5">
              <RiskScoreRing score={currentScore} size={132} label="Stored ledger score" />
            </Card>
            <div className="grid gap-4 sm:grid-cols-3">
              <Card className="p-4"><p className="text-[11px] uppercase tracking-wider text-muted-foreground">Raw points</p><p className="mt-2 font-mono text-2xl font-medium tabular-nums">{rawPoints.toFixed(1)}</p><p className="mt-1 text-[10px] text-muted-foreground">Before decay</p></Card>
              <Card className="p-4"><p className="text-[11px] uppercase tracking-wider text-muted-foreground">Decayed</p><p className="mt-2 font-mono text-2xl font-medium tabular-nums">{decayedPoints.toFixed(1)}</p><p className="mt-1 text-[10px] text-muted-foreground">Points removed by time</p></Card>
              <Card className="p-4"><p className="text-[11px] uppercase tracking-wider text-muted-foreground">Canary points</p><p className={cn("mt-2 font-mono text-2xl font-medium tabular-nums", canaryPoints > 0 && "text-signal-isolated")}>{canaryPoints.toFixed(1)}</p><p className="mt-1 text-[10px] text-muted-foreground">Interaction penalties</p></Card>
            </div>
          </div>
          <div className="grid gap-4 xl:grid-cols-2">
            <Card>
              <CardHeader><CardTitle>Contributions</CardTitle><CardDescription>Server-persisted score contributions.</CardDescription></CardHeader>
              <CardContent>
                {contributions.length ? <ul className="divide-y divide-border">{contributions.map((item, index) => (
                  <li key={`${item.name}-${index}`} className="flex items-start justify-between gap-3 py-2.5 first:pt-0 last:pb-0"><div><p className="text-sm font-medium">{item.name}</p><p className="font-mono text-[10px] text-muted-foreground">{item.reason_code} · {item.kind}{item.occurred_at ? ` · ${relativeTime(item.occurred_at)}` : ""}</p></div><Badge variant="outline" className="font-mono tabular-nums">+{item.points.toFixed(1)}</Badge></li>
                ))}</ul> : <p className="text-sm text-muted-foreground">No contributions recorded.</p>}
              </CardContent>
            </Card>
            <Card>
              <CardHeader><CardTitle>Latched signals & surface</CardTitle></CardHeader>
              <CardContent className="space-y-4">
                <div><p className="text-[11px] uppercase tracking-wider text-muted-foreground">Latched signals</p><div className="mt-1.5 flex flex-wrap gap-1">{latchedSignals.length ? latchedSignals.map((signal) => <Badge key={signal} variant="warning" className="font-mono">{signal}</Badge>) : <span className="text-sm text-muted-foreground">None</span>}</div></div>
                <div><p className="text-[11px] uppercase tracking-wider text-muted-foreground">Devices observed</p><div className="mt-1 flex flex-wrap gap-1">{devices.length ? devices.map((device) => <span key={device} className="rounded bg-muted px-1.5 py-0.5 font-mono text-[10px]">{device}</span>) : <span className="text-sm text-muted-foreground">None</span>}</div></div>
                <div><p className="text-[11px] uppercase tracking-wider text-muted-foreground">Locations observed</p><div className="mt-1 flex flex-wrap gap-1">{locations.length ? locations.map((location) => <span key={location} className="rounded bg-muted px-1.5 py-0.5 font-mono text-[10px]">{location}</span>) : <span className="text-sm text-muted-foreground">None</span>}</div></div>
                <DataField label="Last evaluated">{formatDateTime(ledger.last_evaluated_at)}</DataField>
                <InfoNote tone="info">The score shown is the stored session state. Decision-time scores may differ after later events.</InfoNote>
              </CardContent>
            </Card>
          </div>
        </TabsContent>

        <TabsContent value="sequences" className="space-y-4">
          <Card>
            <CardHeader><CardTitle>Sequence markers</CardTitle><CardDescription>Server window: {sequences?.window_seconds ?? "—"} seconds. Markers are evidence of observed ordering, not proof of intent.</CardDescription></CardHeader>
            <CardContent>
              {markers.length ? <div className="space-y-4">{markers.map((marker) => (
                <div key={marker.marker_id} className="rounded-lg border border-border p-4"><div className="flex flex-wrap items-center justify-between gap-2"><div><p className="text-sm font-medium">{marker.sequence_type}</p><p className="font-mono text-[10px] text-muted-foreground">{marker.marker_id} · {marker.recipient_hash ?? "no recipient hash"}</p></div><Badge variant="outline">{relativeTime(marker.occurred_at)}</Badge></div><ol className="mt-3 space-y-2 border-l border-border pl-4">{marker.events?.map((event) => <li key={event.event_id} className="relative text-xs"><span className="absolute -left-[1.19rem] top-1 h-2 w-2 rounded-full bg-primary" aria-hidden="true" /><span className="font-medium">{humanizeCode(event.event_type)}</span> · {event.action} <span className="text-muted-foreground">(+{event.elapsed_seconds.toFixed(0)}s)</span></li>)}</ol></div>
              ))}</div> : <p className="py-8 text-center text-sm text-muted-foreground">No sequence markers recorded for this session.</p>}
            </CardContent>
          </Card>
        </TabsContent>

        <TabsContent value="twin" className="space-y-4">
          <div className="grid gap-4 xl:grid-cols-2">
            <Card>
              <CardHeader><CardTitle className="flex items-center gap-2"><Fingerprint className="h-4 w-4 text-primary" /> Behavioural twin</CardTitle><CardDescription>{twin?.is_provisional ? "Provisional — not enough samples for full baseline." : "Established baseline."}</CardDescription></CardHeader>
              <CardContent>
                {twin ? <dl className="grid grid-cols-2 gap-4"><DataField label="Samples">{twin.sample_count}</DataField><DataField label="Confirmed devices">{twin.confirmed_device_count}</DataField><DataField label="Confirmed locations">{twin.confirmed_location_count}</DataField><DataField label="Confirmed payees">{twin.confirmed_payee_count}</DataField><DataField label="Pending payees">{twin.pending_payee_count}</DataField><DataField label="Amount samples">{twin.amount_count}</DataField><DataField label="Active hours" className="col-span-2">{(twin.active_hours ?? []).length ? (twin.active_hours ?? []).join(", ") : "Not established"}</DataField><DataField label="Last updated" className="col-span-2">{formatDateTime(twin.last_updated_at)}</DataField></dl> : <p className="text-sm text-muted-foreground">No behavioural twin exists for this identity.</p>}
              </CardContent>
            </Card>
            <Card>
              <CardHeader><CardTitle className="flex items-center gap-2"><Sparkles className="h-4 w-4 text-signal-decoy" /> Canaries</CardTitle><CardDescription>Metadata only. Secret values are never exposed by the operator projection.</CardDescription></CardHeader>
              <CardContent>
                {canaries.length ? <ul className="divide-y divide-border">{canaries.map((canary) => <li key={canary.canary_id} className="flex items-center justify-between gap-2 py-2.5 first:pt-0 last:pb-0"><div><p className="text-sm font-medium">{canary.kind}</p><p className="font-mono text-[10px] text-muted-foreground">{canary.tag} · {canary.canary_id.slice(0, 8)}…</p></div><div className="text-right"><Badge variant={canary.triggered_at ? "danger" : canary.armed ? "warning" : "muted"}>{canary.triggered_at ? "Triggered" : canary.armed ? "Armed" : "Disarmed"}</Badge><p className="mt-1 text-[10px] text-muted-foreground">{canary.triggered_at ? relativeTime(canary.triggered_at) : "no trigger"}</p></div></li>)}</ul> : <p className="text-sm text-muted-foreground">No canaries scoped to this session.</p>}
                <div className="mt-3 flex gap-2"><Button asChild variant="outline" size="sm"><Link to={`/honey/${identitySession.session_id}`}><KeyRound className="h-3.5 w-3.5" /> Honey workspace</Link></Button><Button asChild variant="ghost" size="sm"><Link to="/evidence"><ShieldCheck className="h-3.5 w-3.5" /> Evidence</Link></Button></div>
              </CardContent>
            </Card>
          </div>
        </TabsContent>
      </Tabs>

      <div className="flex flex-wrap gap-2 text-xs">
        <Button asChild variant="outline" size="sm"><Link to={`/identities/${identitySession.user_id}`}><Fingerprint className="h-3.5 w-3.5" /> Identity detail</Link></Button>
        <Button asChild variant="outline" size="sm"><Link to={`/honey/${identitySession.session_id}`}><Sparkles className="h-3.5 w-3.5" /> Honey workspace</Link></Button>
        <Button asChild variant="outline" size="sm"><Link to={`/risk?session_id=${identitySession.session_id}`}><Link2 className="h-3.5 w-3.5" /> Risk decisions</Link></Button>
      </div>
    </div>
  );
}
