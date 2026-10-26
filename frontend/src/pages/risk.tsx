import { useQuery } from "@tanstack/react-query";
import { Activity, Filter, RefreshCw, ShieldCheck, SlidersHorizontal, X } from "lucide-react";
import { useState } from "react";
import { Link, useSearchParams } from "react-router-dom";
import { StatusBadge, TrustBadge } from "@/components/common/badges";
import { EmptyState } from "@/components/common/empty-state";
import { ErrorState } from "@/components/common/error-state";
import { InfoNote } from "@/components/common/info-note";
import { CardsLoading, TableLoading } from "@/components/common/loading-state";
import { PageHeader } from "@/components/common/page-header";
import { Pagination } from "@/components/common/pagination";
import { RiskMeter } from "@/components/common/risk-meter";
import { Badge } from "@/components/ui/badge";
import { Button } from "@/components/ui/button";
import { Card, CardContent, CardDescription, CardHeader, CardTitle } from "@/components/ui/card";
import { Input } from "@/components/ui/input";
import { Select, SelectContent, SelectItem, SelectTrigger, SelectValue } from "@/components/ui/select";
import { Table, TableBody, TableCell, TableHead, TableHeader, TableRow } from "@/components/ui/table";
import { api } from "@/lib/api";
import { useAuth } from "@/lib/auth";
import { formatDateTime } from "@/lib/format";
import { cn } from "@/lib/utils";

const PAGE_SIZE = 25;

export function RiskPage() {
  const { session } = useAuth();
  const [params] = useSearchParams();
  const [page, setPage] = useState(1);
  const [sessionId, setSessionId] = useState(params.get("session_id") ?? "");
  const [trust, setTrust] = useState("all");
  const [minScore, setMinScore] = useState("");
  const [maxScore, setMaxScore] = useState("");
  const [start, setStart] = useState("");
  const [end, setEnd] = useState("");

  const configQuery = useQuery({ queryKey: ["risk-config"], queryFn: () => api.riskConfig(session!), enabled: Boolean(session) });
  const decisionsQuery = useQuery({
    queryKey: ["risk-decisions", { sessionId, trust, minScore, maxScore, start, end, page }],
    queryFn: () => api.listRiskDecisions(session!, {
      session_id: sessionId || undefined,
      trust_level: trust === "all" ? undefined : trust,
      min_score: minScore ? Number(minScore) : undefined,
      max_score: maxScore ? Number(maxScore) : undefined,
      start: start ? new Date(`${start}T00:00:00`).toISOString() : undefined,
      end: end ? new Date(`${end}T23:59:59`).toISOString() : undefined,
      page, page_size: PAGE_SIZE,
    }),
    enabled: Boolean(session),
  });
  const config = configQuery.data;
  const hasFilters = Boolean(sessionId || trust !== "all" || minScore || maxScore || start || end);
  const reset = () => { setSessionId(""); setTrust("all"); setMinScore(""); setMaxScore(""); setStart(""); setEnd(""); setPage(1); };
  const bandConfig =
    config &&
    typeof config.thresholds.restricted === "number" &&
    typeof config.thresholds.decoy === "number" &&
    typeof config.thresholds.isolated === "number"
      ? {
          restricted: config.thresholds.restricted,
          decoy: config.thresholds.decoy,
          isolated: config.thresholds.isolated,
        }
      : null;
  const bands = bandConfig
    ? [
        { key: "normal", label: "Normal", from: 0, to: bandConfig.restricted, tone: "bg-signal-normal" },
        { key: "restricted", label: "Restricted", from: bandConfig.restricted, to: bandConfig.decoy, tone: "bg-signal-restricted" },
        { key: "decoy", label: "Decoy", from: bandConfig.decoy, to: bandConfig.isolated, tone: "bg-signal-decoy" },
        { key: "isolated", label: "Isolated", from: bandConfig.isolated, to: 100, tone: "bg-signal-isolated" },
      ]
    : [];

  return (
    <div className="space-y-5">
      <PageHeader
        eyebrow="Risk intelligence"
        title="Authoritative risk configuration"
        description="Read the live thresholds, weights and sequence window supplied by the backend, then inspect persisted decisions. The console never re-scores an event."
        actions={<Button variant="outline" size="sm" onClick={() => { void configQuery.refetch(); void decisionsQuery.refetch(); }} disabled={configQuery.isFetching || decisionsQuery.isFetching}><RefreshCw className={cn("h-3.5 w-3.5", (configQuery.isFetching || decisionsQuery.isFetching) && "animate-spin")} /> Refresh</Button>}
      />

      {configQuery.isError ? <ErrorState error={configQuery.error} onRetry={() => void configQuery.refetch()} /> : configQuery.isLoading ? <CardsLoading count={4} /> : config ? (
        <>
          <div className="grid gap-4 xl:grid-cols-3">
            <Card className="relative overflow-hidden p-5 sm:p-6 xl:col-span-2">
              <div className="pointer-events-none absolute -right-20 -top-24 h-56 w-56 rounded-full border border-white/[0.05]" aria-hidden="true" />
              <div className="pointer-events-none absolute -bottom-24 left-1/4 h-40 w-40 rounded-full bg-primary/[0.05] blur-2xl" aria-hidden="true" />
              <div className="flex flex-wrap items-start justify-between gap-3">
                <div>
                  <p className="editorial-eyebrow"><span className="h-1.5 w-1.5 rounded-full bg-primary" aria-hidden="true" />Runtime band thresholds</p>
                  <p className="mt-3 max-w-xl text-sm leading-6 text-muted-foreground">Bands are served by the running engine. Crossing a boundary changes routing; this console never interpolates or re-scores a value.</p>
                </div>
                <Badge variant="mint">Server config</Badge>
              </div>
              <div className="mt-7">
                {bandConfig ? (
                  <>
                    <div
                      className="flex h-2.5 w-full overflow-hidden rounded-full ring-1 ring-inset ring-white/10"
                      role="img"
                      aria-label={`Risk bands: normal below ${bandConfig.restricted}, restricted from ${bandConfig.restricted}, decoy from ${bandConfig.decoy}, isolated from ${bandConfig.isolated}`}
                    >
                      {bands.map((band) => (
                        <span
                          key={band.key}
                          className={cn("h-full border-r border-background/50 last:border-r-0", band.tone)}
                          style={{ width: `${Math.max(0, band.to - band.from)}%` }}
                        />
                      ))}
                    </div>
                    <div className="mt-3 grid grid-cols-2 gap-2 sm:grid-cols-4">
                      {bands.map((band) => (
                        <div key={band.key}>
                          <p className="flex items-center gap-1.5 text-2xs font-semibold uppercase tracking-[0.14em] text-foreground">
                            <span className={cn("h-1.5 w-1.5 rounded-full", band.tone)} aria-hidden="true" />
                            {band.label}
                          </p>
                          <p className="mt-1 font-mono text-[11px] text-muted-foreground">from {band.from}</p>
                        </div>
                      ))}
                    </div>
                  </>
                ) : (
                  <p className="rounded-xl border border-dashed border-border px-4 py-6 text-sm text-muted-foreground">
                    The backend did not return a complete threshold set, so the band ladder cannot be drawn.
                  </p>
                )}
              </div>
              <dl className="mt-6 grid gap-px overflow-hidden rounded-xl border border-border/70 bg-border/50 sm:grid-cols-3">
                <div className="bg-card px-4 py-3"><dt className="text-2xs uppercase tracking-[0.14em] text-muted-foreground">Restricted payout limit</dt><dd className="mt-1 font-mono text-sm tabular-nums">{config.thresholds.restricted_payout_limit?.toFixed(2) ?? "—"}</dd></div>
                <div className="bg-card px-4 py-3"><dt className="text-2xs uppercase tracking-[0.14em] text-muted-foreground">Sequence window</dt><dd className="mt-1 font-mono text-sm tabular-nums">{config.sequence_window_seconds}s</dd></div>
                <div className="bg-card px-4 py-3"><dt className="text-2xs uppercase tracking-[0.14em] text-muted-foreground">Signals in service</dt><dd className="mt-1 font-mono text-sm tabular-nums">{config.signals.length}</dd></div>
              </dl>
            </Card>

            <Card>
              <CardHeader><CardTitle className="flex items-center gap-2"><SlidersHorizontal className="h-4 w-4 text-primary" /> Runtime policy</CardTitle><CardDescription>Served with the live configuration.</CardDescription></CardHeader>
              <CardContent className="space-y-3 text-sm">
                <div className="flex justify-between gap-3"><span className="text-muted-foreground">Minimum samples</span><span className="font-mono">{config.min_samples}</span></div>
                <div className="flex justify-between gap-3"><span className="text-muted-foreground">Provisional factor</span><span className="font-mono">{config.provisional_factor}</span></div>
                <div className="flex justify-between gap-3"><span className="text-muted-foreground">Decay per event</span><span className="font-mono">{config.decay_points_per_event}</span></div>
                <div className="flex justify-between gap-3"><span className="text-muted-foreground">Default timezone</span><span className="font-mono">{config.default_timezone}</span></div>
              </CardContent>
            </Card>
          </div>

          <div className="grid gap-4 xl:grid-cols-3">
            <Card className="xl:col-span-2">
              <CardHeader><CardTitle className="flex items-center gap-2"><Activity className="h-4 w-4 text-primary" /> Signal weights</CardTitle><CardDescription>Weights actually used by the running engine. Inactive signals may exist in configuration.</CardDescription></CardHeader>
              <CardContent className="p-0">
                <Table><TableHeader><TableRow><TableHead>Signal</TableHead><TableHead>Weight</TableHead><TableHead>Description</TableHead></TableRow></TableHeader><TableBody>{config.signals.map((signal) => <TableRow key={signal.name}><TableCell className="font-mono text-xs">{signal.name}</TableCell><TableCell><Badge variant="outline" className="tabular-nums">{signal.weight.toFixed(1)}</Badge></TableCell><TableCell className="text-xs text-muted-foreground">{signal.description}</TableCell></TableRow>)}</TableBody></Table>
              </CardContent>
            </Card>
            <Card><CardHeader><CardTitle>Protected actions</CardTitle><CardDescription>Actions routed through the gateway.</CardDescription></CardHeader><CardContent><div className="flex flex-wrap gap-1.5">{(config.protected_actions ?? []).length ? (config.protected_actions ?? []).map((action) => <Badge key={action} variant="muted" className="font-mono">{action}</Badge>) : <span className="text-sm text-muted-foreground">None listed.</span>}</div></CardContent></Card>
          </div>
        </>
      ) : null}

      <Card>
        <CardHeader><CardTitle>Decision history</CardTitle><CardDescription>Persisted decisions, filterable by session, band and time.</CardDescription></CardHeader>
        <CardContent className="space-y-3 border-b border-border">
          <div className="grid gap-2 md:grid-cols-2 xl:grid-cols-6">
            <Input value={sessionId} onChange={(e) => { setSessionId(e.target.value); setPage(1); }} placeholder="Session UUID" aria-label="Filter by session id" className="font-mono text-xs xl:col-span-2" />
            <Select value={trust} onValueChange={(value) => { setTrust(value); setPage(1); }}><SelectTrigger aria-label="Filter by trust"><SelectValue /></SelectTrigger><SelectContent><SelectItem value="all">All bands</SelectItem><SelectItem value="NORMAL">Normal</SelectItem><SelectItem value="RESTRICTED">Restricted</SelectItem><SelectItem value="DECOY">Decoy</SelectItem><SelectItem value="ISOLATED">Isolated</SelectItem></SelectContent></Select>
            <div className="flex gap-2"><Input value={minScore} onChange={(e) => { setMinScore(e.target.value); setPage(1); }} type="number" min="0" max="100" placeholder="Min score" aria-label="Minimum risk score" /><Input value={maxScore} onChange={(e) => { setMaxScore(e.target.value); setPage(1); }} type="number" min="0" max="100" placeholder="Max score" aria-label="Maximum risk score" /></div>
            <div className="flex gap-2"><Input value={start} onChange={(e) => { setStart(e.target.value); setPage(1); }} type="date" aria-label="Start date" /><Input value={end} onChange={(e) => { setEnd(e.target.value); setPage(1); }} type="date" aria-label="End date" /></div>
            <Button variant="ghost" size="sm" onClick={reset} disabled={!hasFilters} className="justify-start"><X className="h-3.5 w-3.5" /> Clear filters</Button>
          </div>
          <p className="flex items-center gap-1.5 text-xs text-muted-foreground"><Filter className="h-3.5 w-3.5" /> {decisionsQuery.data ? `${decisionsQuery.data.total} decisions match` : "Loading decisions"}</p>
        </CardContent>
        {decisionsQuery.isError ? <div className="p-4"><ErrorState error={decisionsQuery.error} onRetry={() => void decisionsQuery.refetch()} /></div> : null}
        {decisionsQuery.isLoading ? <TableLoading rows={7} columns={6} /> : decisionsQuery.data?.items.length === 0 ? (
          <EmptyState icon={ShieldCheck} title={hasFilters ? "No decisions match these filters" : "No risk decisions recorded"} description={hasFilters ? "Clear or adjust the filters to inspect stored decisions." : "Decisions appear after the gateway evaluates a protected action."} action={hasFilters ? <Button variant="outline" onClick={reset}>Clear filters</Button> : undefined} />
        ) : (
          <>
            <Table><TableHeader><TableRow><TableHead>Decision</TableHead><TableHead>Session</TableHead><TableHead>Risk</TableHead><TableHead>Action / routing</TableHead><TableHead>Reason codes</TableHead><TableHead className="text-right">Evaluated</TableHead></TableRow></TableHeader><TableBody>
              {decisionsQuery.data?.items.map((decision) => (
                <TableRow key={decision.decision_id}>
                  <TableCell><Link to={`/risk/decisions/${decision.decision_id}`} className="font-mono text-xs text-primary hover:underline">{decision.decision_id.slice(0, 8)}…</Link>{decision.payout_id ? <Link to={`/payouts/${decision.payout_id}`} className="mt-0.5 block text-[10px] text-muted-foreground hover:underline">payout {decision.payout_id.slice(0, 8)}…</Link> : null}</TableCell>
                  <TableCell><Link to={`/sessions/${decision.session_id}`} className="font-mono text-[11px] text-primary hover:underline">{decision.session_id.slice(0, 8)}…</Link></TableCell>
                  <TableCell><div className="space-y-1"><TrustBadge level={decision.trust_level} /><RiskMeter score={decision.risk_score} /></div></TableCell>
                  <TableCell><div className="space-y-1"><StatusBadge status={decision.action} /><p className="font-mono text-[10px] text-muted-foreground">{decision.routing_destination}</p></div></TableCell>
                  <TableCell><div className="flex max-w-52 flex-wrap gap-1">{(decision.reason_codes ?? []).length ? (decision.reason_codes ?? []).map((code) => <span key={code} className="rounded bg-muted px-1 py-0.5 font-mono text-[10px]">{code}</span>) : <span className="text-xs text-muted-foreground">None</span>}</div></TableCell>
                  <TableCell className="whitespace-nowrap text-right text-[11px] text-muted-foreground">{formatDateTime(decision.evaluated_at)}</TableCell>
                </TableRow>
              ))}
            </TableBody></Table>
            <Pagination page={decisionsQuery.data!.page} pageSize={decisionsQuery.data!.page_size} total={decisionsQuery.data!.total} onPageChange={setPage} label="decisions" />
          </>
        )}
      </Card>
      <InfoNote tone="info">Configuration is displayed exactly as served. If the running service changes a weight or threshold, refresh this page; documentation may lag runtime configuration.</InfoNote>
    </div>
  );
}
