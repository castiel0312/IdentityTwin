import { useQuery } from "@tanstack/react-query";
import {
  Activity,
  ArrowRight,
  BadgeCheck,
  Banknote,
  CircleDollarSign,
  RefreshCw,
  ShieldAlert,
  Siren,
  Users,
} from "lucide-react";
import { useState } from "react";
import { Link, useOutletContext } from "react-router-dom";
import {
  Area,
  AreaChart,
  Bar,
  BarChart,
  CartesianGrid,
  Cell,
  Legend,
  ResponsiveContainer,
  Tooltip as ChartTooltip,
  XAxis,
  YAxis,
} from "recharts";
import { RiskMeter } from "@/components/common/risk-meter";
import { InfoNote } from "@/components/common/info-note";
import { ErrorState } from "@/components/common/error-state";
import { CardsLoading, TableLoading } from "@/components/common/loading-state";
import { StatCard } from "@/components/common/stat-card";
import { TrustBadge, StatusBadge } from "@/components/common/badges";
import { LiveDomainEventStream } from "@/features/overview/live-stream";
import { Badge } from "@/components/ui/badge";
import { Button } from "@/components/ui/button";
import { Card, CardContent, CardDescription, CardHeader, CardTitle } from "@/components/ui/card";
import { Skeleton } from "@/components/ui/skeleton";
import { Table, TableBody, TableCell, TableHead, TableHeader, TableRow } from "@/components/ui/table";
import { api, type Schema } from "@/lib/api";
import { useAuth } from "@/lib/auth";
import { formatDateTime, formatMoney, formatNumber, humanizeCode, relativeTime } from "@/lib/format";
import { createOverviewRange, type OverviewRange } from "@/lib/overview-range";
import { cn } from "@/lib/utils";
import type { ContainmentStream } from "@/lib/sse";

type RangeKey = OverviewRange;

const RANGE_LABELS: Record<RangeKey, string> = {
  "24h": "Last 24 hours",
  "7d": "Last 7 days",
  "30d": "Last 30 days",
};

const CHART = {
  orange: "#FF4D2E",
  mint: "#D8EEEA",
  mintMuted: "#A7D8CE",
  red: "#FF8A7A",
  violet: "#C9ABFF",
  amber: "#F5C16C",
  green: "#7FE3BD",
  grid: "#292D2D",
  axis: "#929B9A",
  panel: "#1B1E1F",
} as const;

function activityHref(item: Schema<"RecentActivityItem">): string | null {
  if (item.payout_id) return `/payouts/${item.payout_id}`;
  if (item.incident_id) return `/incidents/${item.incident_id}`;
  if (item.session_id) return `/sessions/${item.session_id}`;
  return null;
}

function ChartEmpty({ label }: { label: string }) {
  return (
    <div className="flex h-56 items-center justify-center rounded-xl border border-dashed border-border bg-white/[0.015]">
      <p className="text-xs text-muted-foreground">{label}</p>
    </div>
  );
}

function chartTooltipStyle() {
  return {
    contentStyle: {
      borderRadius: 12,
      border: `1px solid ${CHART.grid}`,
      background: CHART.panel,
      color: "#E7F0EF",
      fontSize: 12,
      boxShadow: "0 20px 44px -24px rgb(0 0 0 / 0.9)",
    },
    labelStyle: { fontWeight: 600, color: "#E7F0EF" },
    itemStyle: { color: "#929B9A" },
    cursor: { fill: "rgba(255,255,255,0.035)" },
  } as const;
}

function riskBandColor(minScore: number): string {
  if (minScore >= 90) return CHART.red;
  if (minScore >= 60) return CHART.violet;
  if (minScore >= 30) return CHART.amber;
  return CHART.green;
}

export function OverviewPage() {
  const { session } = useAuth();
  const stream = useOutletContext<ContainmentStream>();
  const [range, setRange] = useState<RangeKey>("24h");

  const query = useQuery({
    queryKey: ["analytics-overview", range],
    queryFn: () => api.overview(session!, createOverviewRange(range)),
    enabled: Boolean(session),
    refetchInterval: 60_000,
  });

  const data = query.data;
  const totals = data?.totals;
  const tooltip = chartTooltipStyle();

  return (
    <div className="space-y-6">
      <section className="relative overflow-hidden rounded-3xl border border-border/80 bg-card px-6 py-8 sm:px-8 sm:py-10 lg:px-10">
        <div className="absolute inset-0 bg-grid opacity-[0.045]" aria-hidden="true" />
        <div
          className="pointer-events-none absolute -right-20 -top-28 h-[24rem] w-[24rem] rounded-full border border-white/[0.06]"
          aria-hidden="true"
        />
        <div
          className="pointer-events-none absolute right-10 -top-6 h-[13rem] w-[13rem] rounded-full border border-primary/25 sm:right-24"
          aria-hidden="true"
        />
        <div className="pointer-events-none absolute right-16 top-10 h-10 w-10 rounded-full bg-primary sm:right-32" aria-hidden="true" />
        <div
          className="pointer-events-none absolute -bottom-20 left-1/3 h-56 w-56 rounded-full bg-mint/[0.035] blur-2xl"
          aria-hidden="true"
        />

        <div className="relative grid gap-8 lg:grid-cols-[minmax(0,1.6fr)_minmax(0,0.9fr)] lg:items-end">
          <div className="space-y-5 min-w-0">
            <p className="editorial-eyebrow">
              <span className="h-1.5 w-1.5 rounded-full bg-primary" aria-hidden="true" />
              Operations pulse · {RANGE_LABELS[range]}
            </p>
            <h1 className="editorial-title min-w-0 text-[clamp(2.25rem,8vw,5rem)]">
              <span className="sr-only">Trust overview — </span>
              Detect.
              <br />
              Deceive.
              <br />
              <span className="text-primary">Defend.</span>
            </h1>
            <p className="max-w-xl text-[clamp(0.875rem,1vw,0.9375rem)] leading-6 text-muted-foreground">
              Server-derived payout, incident and identity metrics for the authenticated merchant. Charts are computed from
              the complete bounded range — never from one paginated page.
            </p>
            <div className="flex flex-wrap items-center gap-2 pt-1">
              <div
                className="flex items-center rounded-full border border-border/80 bg-elevated p-1"
                role="group"
                aria-label="Analytics range"
              >
                {(Object.keys(RANGE_LABELS) as RangeKey[]).map((key) => (
                  <button
                    key={key}
                    type="button"
                    onClick={() => setRange(key)}
                    aria-pressed={range === key}
                    className={cn(
                      "rounded-full px-3 py-1.5 text-xs font-medium transition-colors duration-200",
                      range === key
                        ? "bg-primary text-primary-foreground"
                        : "text-muted-foreground hover:text-foreground",
                    )}
                  >
                    {key}
                  </button>
                ))}
              </div>
              <Button variant="outline" size="sm" onClick={() => void query.refetch()} disabled={query.isFetching}>
                <RefreshCw className={cn("h-3.5 w-3.5", query.isFetching && "animate-spin")} aria-hidden="true" />
                Refresh
              </Button>
              <Button asChild size="sm">
                <Link to="/payouts">
                  Open ledger
                  <ArrowRight className="h-3.5 w-3.5" aria-hidden="true" />
                </Link>
              </Button>
            </div>
          </div>

          <div className="relative">
            {totals ? (
              <dl className="grid grid-cols-2 gap-px overflow-hidden rounded-2xl border border-border/70 bg-border/60">
                {[
                  ["Payouts", formatNumber(totals.payouts_total)],
                  ["Open incidents", formatNumber(totals.incidents_open)],
                  ["Decoy routed", formatNumber(totals.decoy_routed)],
                  ["Sealed evidence", formatNumber(totals.evidence_seals)],
                ].map(([label, value]) => (
                  <div key={label} className="bg-card/95 px-4 py-3.5">
                    <dt className="text-2xs font-semibold uppercase tracking-[0.14em] text-muted-foreground">{label}</dt>
                    <dd className="mt-1.5 font-mono text-xl font-medium tabular-nums text-foreground">{value}</dd>
                  </div>
                ))}
              </dl>
            ) : (
              <div className="grid grid-cols-2 gap-3" aria-busy="true" aria-label="Loading range summary">
                {Array.from({ length: 4 }).map((_, index) => (
                  <Skeleton key={index} className="h-20 rounded-xl" />
                ))}
              </div>
            )}
            <p className="mt-3 flex items-center justify-between gap-3 font-mono text-2xs uppercase tracking-[0.14em] text-muted-foreground">
              <span>{data?.range.bucket ? `Bucket · ${data.range.bucket}` : "Range summary"}</span>
              <span>{data ? `Generated ${formatDateTime(data.generated_at)}` : "Awaiting server"}</span>
            </p>
          </div>
        </div>
      </section>

      {query.isError ? <ErrorState error={query.error} onRetry={() => void query.refetch()} /> : null}

      {query.isLoading ? (
        <CardsLoading />
      ) : totals ? (
        <div className="grid gap-4 sm:grid-cols-2 xl:grid-cols-4">
          <StatCard
            label="Payout volume"
            value={formatNumber(totals.payouts_total)}
            hint={`${formatMoney(totals.amount_total)} attempted`}
            icon={Banknote}
          />
          <StatCard
            label="Open incidents"
            value={formatNumber(totals.incidents_open)}
            hint={`${formatNumber(totals.incidents_in_range)} opened in range`}
            icon={Siren}
            tone={totals.incidents_open > 0 ? "danger" : "success"}
          />
          <StatCard
            label="Active sessions"
            value={formatNumber(totals.sessions_active)}
            hint={`${formatNumber(totals.payouts_requiring_step_up)} required step-up`}
            icon={Users}
          />
          <StatCard
            label="Decoy / isolated"
            value={`${formatNumber(totals.decoy_routed)} / ${formatNumber(totals.isolated_actions)}`}
            hint={`${formatNumber(totals.reconciliation_required)} need reconciliation`}
            icon={ShieldAlert}
            tone={totals.isolated_actions > 0 ? "violet" : "default"}
          />
        </div>
      ) : null}

      {data?.truncated ? (
        <InfoNote tone="warning" title="Range was truncated by the server scan cap">
          Metrics cover only the bounded server range. Do not present these values as all-time totals.
        </InfoNote>
      ) : null}

      <div className="grid gap-4 xl:grid-cols-3">
        <Card className="xl:col-span-2">
          <CardHeader className="flex-row items-start justify-between space-y-0">
            <div className="space-y-1">
              <CardTitle>Operational timeline</CardTitle>
              <CardDescription>{RANGE_LABELS[range]} · server bucket resolution</CardDescription>
            </div>
            <Badge variant="outline" className="font-mono">
              {data?.range.bucket ?? "—"}
            </Badge>
          </CardHeader>
          <CardContent>
            {query.isLoading ? (
              <TableLoading rows={4} columns={3} />
            ) : !(data?.timeline ?? []).length ? (
              <ChartEmpty label="No operational activity in this range." />
            ) : (
              <>
                <div className="h-64 w-full" role="img" aria-label={`Payout and incident timeline for ${RANGE_LABELS[range]}`}>
                  <ResponsiveContainer width="100%" height="100%">
                    <AreaChart data={data?.timeline ?? []} margin={{ top: 8, right: 8, left: -16, bottom: 0 }}>
                      <defs>
                        <linearGradient id="payoutFill" x1="0" y1="0" x2="0" y2="1">
                          <stop offset="0%" stopColor={CHART.orange} stopOpacity={0.34} />
                          <stop offset="100%" stopColor={CHART.orange} stopOpacity={0.02} />
                        </linearGradient>
                        <linearGradient id="incidentFill" x1="0" y1="0" x2="0" y2="1">
                          <stop offset="0%" stopColor={CHART.red} stopOpacity={0.26} />
                          <stop offset="100%" stopColor={CHART.red} stopOpacity={0.02} />
                        </linearGradient>
                      </defs>
                      <CartesianGrid strokeDasharray="3 3" stroke={CHART.grid} strokeOpacity={0.7} vertical={false} />
                      <XAxis
                        dataKey="label"
                        tick={{ fontSize: 10, fill: CHART.axis }}
                        tickLine={false}
                        axisLine={false}
                        minTickGap={24}
                      />
                      <YAxis
                        tick={{ fontSize: 10, fill: CHART.axis }}
                        tickLine={false}
                        axisLine={false}
                        allowDecimals={false}
                      />
                      <ChartTooltip {...tooltip} />
                      <Legend wrapperStyle={{ fontSize: 11, color: CHART.axis }} />
                      <Area
                        type="monotone"
                        dataKey="payouts"
                        name="Payouts"
                        stroke={CHART.orange}
                        strokeWidth={2}
                        fill="url(#payoutFill)"
                      />
                      <Area
                        type="monotone"
                        dataKey="incidents"
                        name="Incidents"
                        stroke={CHART.red}
                        strokeWidth={2}
                        fill="url(#incidentFill)"
                      />
                    </AreaChart>
                  </ResponsiveContainer>
                </div>
                <p className="sr-only">
                  {(data?.timeline ?? []).map((b) => `${b.label}: ${b.payouts} payouts and ${b.incidents} incidents.`).join(" ")}
                </p>
              </>
            )}
          </CardContent>
        </Card>

        <Card>
          <CardHeader className="space-y-1">
            <CardTitle>Risk distribution</CardTitle>
            <CardDescription>Session decisions by score band</CardDescription>
          </CardHeader>
          <CardContent>
            {query.isLoading ? (
              <TableLoading rows={4} columns={2} />
            ) : !(data?.risk_histogram ?? []).length ? (
              <ChartEmpty label="No risk decisions in range." />
            ) : (
              <>
                <div className="h-64 w-full" role="img" aria-label="Risk score distribution">
                  <ResponsiveContainer width="100%" height="100%">
                    <BarChart data={data?.risk_histogram ?? []} margin={{ top: 8, right: 4, left: -20, bottom: 0 }}>
                      <CartesianGrid strokeDasharray="3 3" stroke={CHART.grid} strokeOpacity={0.7} vertical={false} />
                      <XAxis
                        dataKey="bucket"
                        tick={{ fontSize: 10, fill: CHART.axis }}
                        tickLine={false}
                        axisLine={false}
                      />
                      <YAxis
                        tick={{ fontSize: 10, fill: CHART.axis }}
                        tickLine={false}
                        axisLine={false}
                        allowDecimals={false}
                      />
                      <ChartTooltip {...tooltip} />
                      <Bar dataKey="count" name="Decisions" radius={[5, 5, 0, 0]}>
                        {(data?.risk_histogram ?? []).map((entry) => (
                          <Cell key={entry.bucket} fill={riskBandColor(entry.min_score)} />
                        ))}
                      </Bar>
                    </BarChart>
                  </ResponsiveContainer>
                </div>
                <div className="mt-3 flex flex-wrap gap-x-4 gap-y-1.5 border-t border-border/60 pt-3">
                  {[
                    ["Normal", CHART.green],
                    ["Guarded", CHART.amber],
                    ["Elevated", CHART.violet],
                    ["Isolated", CHART.red],
                  ].map(([label, color]) => (
                    <span key={label} className="flex items-center gap-1.5 text-2xs uppercase tracking-[0.12em] text-muted-foreground">
                      <span className="h-1.5 w-1.5 rounded-full" style={{ background: color }} aria-hidden="true" />
                      {label}
                    </span>
                  ))}
                </div>
                <p className="sr-only">
                  {(data?.risk_histogram ?? []).map((bucket) => `${bucket.bucket}: ${bucket.count} decisions.`).join(" ")}
                </p>
              </>
            )}
          </CardContent>
        </Card>
      </div>

      <div className="grid gap-4 xl:grid-cols-[minmax(0,1.25fr)_minmax(0,0.75fr)]">
        <Card className="overflow-hidden">
          <CardHeader className="flex-row items-center justify-between space-y-0">
            <div className="space-y-1">
              <CardTitle>Recent activity</CardTitle>
              <CardDescription>Latest events, payouts and incidents</CardDescription>
            </div>
            <Button asChild variant="ghost" size="sm">
              <Link to="/sessions">Investigate</Link>
            </Button>
          </CardHeader>
          <CardContent className="p-0">
            {query.isLoading ? (
              <TableLoading />
            ) : !(data?.recent_activity ?? []).length ? (
              <div className="px-5 pb-5">
                <ChartEmpty label="No recent activity." />
              </div>
            ) : (
              <Table>
                <TableHeader>
                  <TableRow>
                    <TableHead>Activity</TableHead>
                    <TableHead>Trust</TableHead>
                    <TableHead className="text-right">When</TableHead>
                  </TableRow>
                </TableHeader>
                <TableBody>
                  {(data?.recent_activity ?? []).slice(0, 8).map((item) => {
                    const href = activityHref(item);
                    return (
                      <TableRow key={item.activity_id}>
                        <TableCell>
                          <div className="flex min-w-0 items-start gap-2.5">
                            {item.kind === "incident" ? (
                              <Siren className="mt-0.5 h-3.5 w-3.5 shrink-0 text-signal-isolated" aria-hidden="true" />
                            ) : item.kind === "payout" ? (
                              <CircleDollarSign className="mt-0.5 h-3.5 w-3.5 shrink-0 text-primary" aria-hidden="true" />
                            ) : (
                              <Activity className="mt-0.5 h-3.5 w-3.5 shrink-0 text-mint-muted" aria-hidden="true" />
                            )}
                            <div className="min-w-0">
                              <p className="truncate text-sm font-medium text-foreground">{item.title}</p>
                              <p className="truncate text-[11px] text-muted-foreground">
                                {item.summary ?? humanizeCode(item.event_type ?? item.kind)}
                              </p>
                            </div>
                          </div>
                        </TableCell>
                        <TableCell>
                          <div className="flex flex-col items-start gap-1.5">
                            {item.trust_level ? (
                              <TrustBadge level={item.trust_level} />
                            ) : (
                              <StatusBadge status={item.severity ?? item.kind} />
                            )}
                            {typeof item.risk_score === "number" ? <RiskMeter score={item.risk_score} /> : null}
                          </div>
                        </TableCell>
                        <TableCell className="text-right">
                          {href ? (
                            <Link to={href} className="text-xs text-primary hover:underline">
                              {relativeTime(item.occurred_at)}
                            </Link>
                          ) : (
                            <span className="text-xs text-muted-foreground">{relativeTime(item.occurred_at)}</span>
                          )}
                        </TableCell>
                      </TableRow>
                    );
                  })}
                </TableBody>
              </Table>
            )}
          </CardContent>
        </Card>

        <div className="space-y-4">
          <LiveDomainEventStream stream={stream} />
          <Card>
            <CardHeader className="space-y-1">
              <CardTitle>Provider outcomes</CardTitle>
              <CardDescription>Recorded execution status by provider adapter</CardDescription>
            </CardHeader>
            <CardContent>
              {query.isLoading ? (
                <TableLoading rows={3} columns={3} />
              ) : !(data?.provider_outcomes ?? []).length ? (
                <p className="py-6 text-center text-xs text-muted-foreground">No provider outcomes in this range.</p>
              ) : (
                <ul className="divide-y divide-border/70">
                  {(data?.provider_outcomes ?? []).map((outcome) => (
                    <li
                      key={`${outcome.provider}-${outcome.status}`}
                      className="flex items-center justify-between gap-3 py-2.5 first:pt-0 last:pb-0"
                    >
                      <div>
                        <p className="text-sm font-medium text-foreground">{humanizeCode(outcome.provider)}</p>
                        <p className="text-[11px] text-muted-foreground">{humanizeCode(outcome.status)}</p>
                      </div>
                      <Badge variant="outline" className="font-mono tabular-nums text-foreground">
                        {formatNumber(outcome.count)}
                      </Badge>
                    </li>
                  ))}
                </ul>
              )}
            </CardContent>
          </Card>
          <Card>
            <CardHeader className="space-y-1">
              <CardTitle className="flex items-center gap-2">
                <BadgeCheck className="h-4 w-4 text-mint-muted" aria-hidden="true" />
                Evidence posture
              </CardTitle>
              <CardDescription>Seals, failures and agent-initiated activity</CardDescription>
            </CardHeader>
            <CardContent className="space-y-2.5 text-sm">
              <div className="flex items-center justify-between border-b border-border/50 pb-2">
                <span className="text-muted-foreground">Sealed incidents</span>
                <span className="font-mono tabular-nums text-foreground">{formatNumber(totals?.evidence_seals ?? 0)}</span>
              </div>
              <div className="flex items-center justify-between border-b border-border/50 pb-2">
                <span className="text-muted-foreground">Provider failures</span>
                <span className="font-mono tabular-nums text-foreground">{formatNumber(totals?.provider_failures ?? 0)}</span>
              </div>
              <div className="flex items-center justify-between border-b border-border/50 pb-2">
                <span className="text-muted-foreground">Agent-initiated</span>
                <span className="font-mono tabular-nums text-foreground">{formatNumber(totals?.agent_initiated ?? 0)}</span>
              </div>
              <p className="pt-1 text-[11px] leading-5 text-muted-foreground">
                Generated {data ? formatDateTime(data.generated_at) : "—"} · counts are range-specific.
              </p>
            </CardContent>
          </Card>
        </div>
      </div>
    </div>
  );
}
