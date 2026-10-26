import { useQuery } from "@tanstack/react-query";
import { ArrowLeft, Fingerprint, RefreshCw } from "lucide-react";
import { Link, useParams } from "react-router-dom";
import { StatusBadge, TrustBadge } from "@/components/common/badges";
import { DataField } from "@/components/common/data-field";
import { ErrorState } from "@/components/common/error-state";
import { Limitations } from "@/components/common/limitations";
import { DetailLoading } from "@/components/common/loading-state";
import { PageHeader } from "@/components/common/page-header";
import { RiskMeter } from "@/components/common/risk-meter";
import { Button } from "@/components/ui/button";
import { Card, CardContent, CardDescription, CardHeader, CardTitle } from "@/components/ui/card";
import { Table, TableBody, TableCell, TableHead, TableHeader, TableRow } from "@/components/ui/table";
import { api } from "@/lib/api";
import { useAuth } from "@/lib/auth";
import { formatDateTime, relativeTime } from "@/lib/format";
import { cn } from "@/lib/utils";

export function IdentityDetailPage() {
  const { userId = "" } = useParams();
  const { session } = useAuth();
  const query = useQuery({
    queryKey: ["identity", userId],
    queryFn: () => api.identity(session!, userId),
    enabled: Boolean(session && userId),
  });

  if (query.isLoading) return <DetailLoading />;
  if (query.isError) return <div className="space-y-4"><Button asChild variant="ghost" size="sm" className="-ml-2"><Link to="/sessions"><ArrowLeft className="h-4 w-4" /> Back to sessions</Link></Button><ErrorState error={query.error} onRetry={() => void query.refetch()} /></div>;
  if (!query.data) return null;
  const { identity, sessions = [], limitations = [] } = query.data;

  return (
    <div className="space-y-6">
      <div>
        <Button asChild variant="ghost" size="sm" className="-ml-2 mb-2"><Link to="/sessions"><ArrowLeft className="h-4 w-4" /> Back to identities</Link></Button>
        <PageHeader
          eyebrow="Identity detail"
          title={identity.email}
          description={<span className="flex flex-wrap items-center gap-2"><StatusBadge status={identity.is_active ? "active" : "expired"} /><span className="font-mono text-xs">{identity.user_id}</span><span className="text-xs capitalize">{identity.role}</span></span>}
          actions={<Button variant="outline" size="sm" onClick={() => void query.refetch()} disabled={query.isFetching}><RefreshCw className={cn("h-3.5 w-3.5", query.isFetching && "animate-spin")} /> Refresh</Button>}
        />
      </div>

      <div className="grid gap-4 sm:grid-cols-2 xl:grid-cols-4">
        <Card className="p-4"><p className="text-[11px] uppercase tracking-wider text-muted-foreground">Sessions</p><p className="mt-1 text-xl font-semibold">{identity.active_sessions} active</p><p className="text-[11px] text-muted-foreground">{identity.sessions_total} historical</p></Card>
        <Card className="p-4"><p className="text-[11px] uppercase tracking-wider text-muted-foreground">Max session risk</p><p className="mt-1 text-xl font-semibold">{identity.max_risk_score.toFixed(1)}</p><RiskMeter score={identity.max_risk_score} className="mt-1" /></Card>
        <Card className="p-4"><p className="text-[11px] uppercase tracking-wider text-muted-foreground">Last activity</p><p className="mt-1 text-sm">{relativeTime(identity.last_activity_at)}</p><p className="text-[10px] text-muted-foreground">{formatDateTime(identity.last_activity_at)}</p></Card>
        <Card className="p-4"><p className="text-[11px] uppercase tracking-wider text-muted-foreground">Twin status</p><p className="mt-1 text-sm">{identity.twin ? identity.twin.is_provisional ? "Provisional" : "Established" : "Not established"}</p><p className="text-[10px] text-muted-foreground">{identity.twin ? `${identity.twin.sample_count} samples` : "No baseline samples"}</p></Card>
      </div>

      <div className="grid gap-4 xl:grid-cols-3">
        <Card className="xl:col-span-2">
          <CardHeader><CardTitle>Sessions</CardTitle><CardDescription>Session records resolved from authoritative trust state.</CardDescription></CardHeader>
          <CardContent className="p-0">
            {sessions.length === 0 ? <p className="px-5 pb-5 text-sm text-muted-foreground">No sessions recorded for this identity.</p> : (
              <Table>
                <TableHeader><TableRow><TableHead>Session</TableHead><TableHead>Trust</TableHead><TableHead>Status</TableHead><TableHead>Device</TableHead><TableHead className="text-right">Last activity</TableHead></TableRow></TableHeader>
                <TableBody>{sessions.map((item) => (
                  <TableRow key={item.session_id}>
                    <TableCell><Link to={`/sessions/${item.session_id}`} className="font-mono text-xs text-primary hover:underline">{item.session_id.slice(0, 8)}…</Link><p className="text-[10px] text-muted-foreground">{formatDateTime(item.created_at)}</p></TableCell>
                    <TableCell><div className="space-y-1"><TrustBadge level={item.trust_level} /><RiskMeter score={item.risk_score} /></div></TableCell>
                    <TableCell><StatusBadge status={item.status} /></TableCell>
                    <TableCell><p className="max-w-36 truncate text-xs">{item.device_fingerprint ?? "—"}</p><p className="font-mono text-[10px] text-muted-foreground">{item.ip_address ?? "—"}</p></TableCell>
                    <TableCell className="text-right text-[11px] text-muted-foreground">{relativeTime(item.last_activity_at)}</TableCell>
                  </TableRow>
                ))}</TableBody>
              </Table>
            )}
          </CardContent>
        </Card>
        <Card>
          <CardHeader><CardTitle className="flex items-center gap-2"><Fingerprint className="h-4 w-4 text-primary" /> Behavioural twin</CardTitle><CardDescription>Observed baseline summary.</CardDescription></CardHeader>
          <CardContent>
            {identity.twin ? <dl className="grid grid-cols-2 gap-4"><DataField label="Samples">{identity.twin.sample_count}</DataField><DataField label="Devices">{identity.twin.confirmed_device_count}</DataField><DataField label="Locations">{identity.twin.confirmed_location_count}</DataField><DataField label="Payees">{identity.twin.confirmed_payee_count}</DataField><DataField label="Pending payees">{identity.twin.pending_payee_count}</DataField><DataField label="Amount samples">{identity.twin.amount_count}</DataField><DataField label="Active hours" className="col-span-2">{(identity.twin.active_hours ?? []).length ? (identity.twin.active_hours ?? []).join(", ") : "Not established"}</DataField><DataField label="Updated" className="col-span-2">{formatDateTime(identity.twin.last_updated_at)}</DataField></dl> : <p className="text-sm text-muted-foreground">No behavioural twin is available. The identity remains usable, but the baseline is not established.</p>}
          </CardContent>
        </Card>
      </div>

      <Limitations notes={limitations} />
    </div>
  );
}
