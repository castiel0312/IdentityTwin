import { useQuery } from "@tanstack/react-query";
import { Hexagon, RefreshCw, Sparkles, TriangleAlert } from "lucide-react";
import { useState } from "react";
import { Link } from "react-router-dom";
import { StatusBadge } from "@/components/common/badges";
import { EmptyState } from "@/components/common/empty-state";
import { ErrorState } from "@/components/common/error-state";
import { InfoNote } from "@/components/common/info-note";
import { CardsLoading, TableLoading } from "@/components/common/loading-state";
import { PageHeader } from "@/components/common/page-header";
import { Pagination } from "@/components/common/pagination";
import { Badge } from "@/components/ui/badge";
import { Button } from "@/components/ui/button";
import { Card, CardContent, CardDescription, CardHeader, CardTitle } from "@/components/ui/card";
import { api } from "@/lib/api";
import { useAuth } from "@/lib/auth";
import { formatDateTime, formatMoney, relativeTime } from "@/lib/format";
import { cn } from "@/lib/utils";

const PAGE_SIZE = 25;

export function HoneyPage() {
  const { session } = useAuth();
  const [page, setPage] = useState(1);
  const workspaces = useQuery({ queryKey: ["honey-workspaces", page], queryFn: () => api.listHoneyWorkspaces(session!, { page, page_size: PAGE_SIZE }), enabled: Boolean(session) });
  const canaries = useQuery({ queryKey: ["honey-canaries"], queryFn: () => api.listCanaries(session!), enabled: Boolean(session) });
  const totalTriggered = canaries.data?.items.filter((item) => item.triggered_at).length ?? 0;

  return (
    <div className="space-y-5">
      <PageHeader
        eyebrow="Synthetic environment"
        title="Honey workspace"
        description="Operator-safe projections of decoy merchant worlds. These records are synthetic, scoped to the authenticated merchant and never expose canary secret values."
        actions={<Button variant="outline" size="sm" onClick={() => { void workspaces.refetch(); void canaries.refetch(); }} disabled={workspaces.isFetching || canaries.isFetching}><RefreshCw className={cn("h-3.5 w-3.5", (workspaces.isFetching || canaries.isFetching) && "animate-spin")} /> Refresh</Button>}
      />

      <InfoNote tone="warning" title="Synthetic data boundary">
        The honey world is an isolated decoy plane. Its balances, payees and transactions are fabricated for containment. They are not real customer funds and must not be reconciled against the production ledger. This console only reads the operator projection; it cannot trigger synthetic payouts or touch attacker-facing honey routes.
      </InfoNote>

      <div className="grid gap-4 sm:grid-cols-3">
        <Card className="p-4"><p className="text-[11px] uppercase tracking-wider text-muted-foreground">Workspaces</p><p className="mt-1 text-2xl font-semibold">{workspaces.data?.total ?? "—"}</p><p className="text-[11px] text-muted-foreground">Synthetic decoy worlds</p></Card>
        <Card className="p-4"><p className="text-[11px] uppercase tracking-wider text-muted-foreground">Canary inventory</p><p className="mt-1 text-2xl font-semibold">{canaries.data?.total ?? "—"}</p><p className="text-[11px] text-muted-foreground">Metadata only; secrets redacted</p></Card>
        <Card className="p-4"><p className="text-[11px] uppercase tracking-wider text-muted-foreground">Triggered canaries</p><p className={cn("mt-1 text-2xl font-semibold", totalTriggered > 0 && "text-signal-isolated")}>{canaries.isLoading ? "—" : totalTriggered}</p><p className="text-[11px] text-muted-foreground">Observed interaction requires containment</p></Card>
      </div>

      <div className="grid gap-4 xl:grid-cols-3">
        <div className="space-y-4 xl:col-span-2">
          <Card>
            <CardHeader><CardTitle className="flex items-center gap-2"><Sparkles className="h-4 w-4 text-signal-decoy" /> Synthetic workspaces</CardTitle><CardDescription>Each workspace is bound to a decoy or isolated session.</CardDescription></CardHeader>
            {workspaces.isError ? <div className="p-4"><ErrorState error={workspaces.error} onRetry={() => void workspaces.refetch()} /></div> : null}
            {workspaces.isLoading ? <CardsLoading count={4} className="p-4" /> : workspaces.data?.items.length === 0 ? (
              <EmptyState icon={Hexagon} title="No honey workspaces" description="Decoy worlds are created when a decoy or isolated session touches the honey plane." className="border-0" />
            ) : (
              <CardContent className="grid gap-3 sm:grid-cols-2">
                {workspaces.data?.items.map((workspace) => (
                  <Link key={workspace.session_id} to={`/honey/${workspace.session_id}`} className="group rounded-xl border border-border p-4 transition-colors hover:border-signal-decoy/35 hover:bg-signal-decoy/[0.04]">
                    <div className="flex items-start justify-between gap-2"><div><p className="text-[10px] font-semibold uppercase tracking-wider text-signal-decoy">Synthetic world</p><h3 className="mt-0.5 font-medium">{workspace.merchant_name}</h3></div><Badge variant="violet">Decoy</Badge></div>
                    <p className="mt-2 font-mono text-lg font-semibold tabular-nums">{formatMoney(workspace.balance.amount, workspace.balance.currency)}</p>
                    <div className="mt-2 flex flex-wrap gap-1.5 text-[10px] text-muted-foreground"><span>{workspace.payee_count} payees</span><span>·</span><span>{workspace.transaction_count} transactions</span><span>·</span><span>{workspace.payout_count} synthetic payouts</span></div>
                    <div className="mt-3 flex items-center justify-between gap-2"><StatusBadge status={workspace.session_status} />{workspace.canaries_triggered > 0 ? <span className="flex items-center gap-1 text-[10px] font-medium text-signal-isolated"><TriangleAlert className="h-3 w-3" /> {workspace.canaries_triggered} triggered</span> : <span className="text-[10px] text-muted-foreground">{workspace.canary_count} canaries</span>}</div>
                    <p className="mt-2 truncate text-[10px] text-muted-foreground">session {workspace.session_id} · updated {relativeTime(workspace.updated_at)}</p>
                  </Link>
                ))}
              </CardContent>
            )}
            {workspaces.data && workspaces.data.total > PAGE_SIZE ? <Pagination page={workspaces.data.page} pageSize={workspaces.data.page_size} total={workspaces.data.total} onPageChange={setPage} label="workspaces" /> : null}
          </Card>
        </div>

        <Card>
          <CardHeader><CardTitle>Canary inventory</CardTitle><CardDescription>No secret value, token or HMAC material is returned to the console.</CardDescription></CardHeader>
          {canaries.isError ? <div className="p-4"><ErrorState error={canaries.error} onRetry={() => void canaries.refetch()} /></div> : null}
          {canaries.isLoading ? <TableLoading rows={4} columns={3} /> : canaries.data?.items.length === 0 ? <p className="px-5 pb-5 text-sm text-muted-foreground">No canaries issued.</p> : (
            <CardContent className="space-y-2">
              {canaries.data?.items.slice(0, 20).map((canary) => (
                <div key={canary.canary_id} className="rounded-lg border border-border p-3">
                  <div className="flex items-center justify-between gap-2"><p className="text-sm font-medium">{canary.kind}</p><Badge variant={canary.triggered_at ? "danger" : canary.armed ? "warning" : "muted"}>{canary.triggered_at ? "Triggered" : canary.armed ? "Armed" : "Disarmed"}</Badge></div>
                  <p className="mt-1 truncate font-mono text-[10px] text-muted-foreground">{canary.tag} · {canary.canary_id}</p>
                  {canary.session_id ? <Link to={`/honey/${canary.session_id}`} className="mt-1 block text-[10px] text-primary hover:underline">session {canary.session_id.slice(0, 8)}…</Link> : null}
                  {canary.triggered_at ? <p className="mt-1 text-[10px] text-signal-isolated">Triggered {formatDateTime(canary.triggered_at)} · {canary.containment_status ?? "containment status unavailable"}</p> : <p className="mt-1 text-[10px] text-muted-foreground">No interaction recorded</p>}
                </div>
              ))}
              <p className="text-[11px] leading-5 text-muted-foreground">Displaying metadata for {Math.min(canaries.data?.items.length ?? 0, 20)} of {canaries.data?.total ?? 0} canaries. Synthetic values cannot be exported from this view.</p>
            </CardContent>
          )}
        </Card>
      </div>
      <p className="text-[11px] text-muted-foreground">Honey data is isolated from the real ledger by backend design. The console routes only through read-only operator endpoints.</p>
    </div>
  );
}
