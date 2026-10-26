import { useQuery } from "@tanstack/react-query";
import { ArrowLeft, ArrowUpRight, RefreshCw, Sparkles, TriangleAlert } from "lucide-react";
import { Link, useParams } from "react-router-dom";
import { StatusBadge } from "@/components/common/badges";
import { DataField } from "@/components/common/data-field";
import { ErrorState } from "@/components/common/error-state";
import { InfoNote } from "@/components/common/info-note";
import { DetailLoading } from "@/components/common/loading-state";
import { PageHeader } from "@/components/common/page-header";
import { Badge } from "@/components/ui/badge";
import { Button } from "@/components/ui/button";
import { Card, CardContent, CardDescription, CardHeader, CardTitle } from "@/components/ui/card";
import { Table, TableBody, TableCell, TableHead, TableHeader, TableRow } from "@/components/ui/table";
import { api } from "@/lib/api";
import { useAuth } from "@/lib/auth";
import { formatDateTime, formatMoney, humanizeCode, relativeTime } from "@/lib/format";
import { cn } from "@/lib/utils";

export function HoneyDetailPage() {
  const { sessionId = "" } = useParams();
  const { session } = useAuth();
  const query = useQuery({ queryKey: ["honey-workspace", sessionId], queryFn: () => api.honeyWorkspace(session!, sessionId), enabled: Boolean(session && sessionId) });

  if (query.isLoading) return <DetailLoading />;
  if (query.isError) return <div className="space-y-4"><Button asChild variant="ghost" size="sm" className="-ml-2"><Link to="/honey"><ArrowLeft className="h-4 w-4" /> Back to honey</Link></Button><ErrorState error={query.error} onRetry={() => void query.refetch()} /></div>;
  if (!query.data) return null;
  const { workspace, merchant, balance, payees = [], transactions = [], payouts = [], recent_activity = [], canaries = [], containment_notes = [] } = query.data;
  const triggered = canaries.filter((canary) => canary.triggered_at).length;

  return (
    <div className="space-y-6">
      <div>
        <Button asChild variant="ghost" size="sm" className="-ml-2 mb-2"><Link to="/honey"><ArrowLeft className="h-4 w-4" /> Back to honey</Link></Button>
        <PageHeader
          eyebrow="Synthetic honey workspace"
          title={merchant.name}
          description={<span className="flex flex-wrap items-center gap-2"><Badge variant="violet">Synthetic decoy</Badge><StatusBadge status={workspace.session_status} /><span className="font-mono text-[11px]">{workspace.session_id}</span><span className="text-xs text-muted-foreground">{merchant.country ?? "unknown country"}</span></span>}
          actions={<Button variant="outline" size="sm" onClick={() => void query.refetch()} disabled={query.isFetching}><RefreshCw className={cn("h-3.5 w-3.5", query.isFetching && "animate-spin")} /> Refresh</Button>}
        />
      </div>

      <InfoNote tone="warning" title="This is not real money">
        Every merchant, balance, payee, transaction and payout in this workspace is synthetic. Do not reconcile it with the real payout ledger. Raw world metadata and canary secrets are intentionally not rendered.
      </InfoNote>

      <div className="grid gap-4 sm:grid-cols-2 xl:grid-cols-4">
        <Card className="p-4"><p className="text-[11px] uppercase tracking-wider text-muted-foreground">Synthetic balance</p><p className="mt-1 text-2xl font-semibold tabular-nums">{formatMoney(balance.amount, balance.currency)}</p><p className="text-[10px] text-muted-foreground">decoy value only</p></Card>
        <Card className="p-4"><p className="text-[11px] uppercase tracking-wider text-muted-foreground">Payees / transactions</p><p className="mt-1 text-2xl font-semibold">{payees.length} / {transactions.length}</p><p className="text-[10px] text-muted-foreground">fabricated world state</p></Card>
        <Card className="p-4"><p className="text-[11px] uppercase tracking-wider text-muted-foreground">Canaries</p><p className={cn("mt-1 text-2xl font-semibold", triggered > 0 && "text-signal-isolated")}>{canaries.length} / {triggered}</p><p className="text-[10px] text-muted-foreground">issued / triggered</p></Card>
        <Card className="p-4"><p className="text-[11px] uppercase tracking-wider text-muted-foreground">Containment</p>{workspace.containment_incident_id ? <Link to={`/incidents/${workspace.containment_incident_id}`} className="mt-1 flex items-center gap-1 text-sm font-medium text-primary hover:underline">Incident {workspace.containment_incident_id.slice(0, 8)}… <ArrowUpRight className="h-3.5 w-3.5" /></Link> : <p className="mt-1 text-sm text-muted-foreground">No incident linked</p>}<p className="text-[10px] text-muted-foreground">updated {relativeTime(workspace.updated_at)}</p></Card>
      </div>

      <div className="grid gap-4 xl:grid-cols-3">
        <div className="space-y-4 xl:col-span-2">
          <Card>
            <CardHeader><CardTitle>Synthetic payouts</CardTitle><CardDescription>Provider responses fabricated inside the honey plane. These did not execute real payments.</CardDescription></CardHeader>
            <CardContent className="p-0">
              {payouts.length ? <Table><TableHeader><TableRow><TableHead>Batch</TableHead><TableHead>Recipient</TableHead><TableHead>Amount</TableHead><TableHead>Status</TableHead><TableHead className="text-right">Transaction</TableHead></TableRow></TableHeader><TableBody>{payouts.map((payout) => <TableRow key={payout.payout_batch_id}><TableCell><p className="font-mono text-xs">{payout.payout_batch_id}</p></TableCell><TableCell><p className="max-w-48 truncate text-xs">{payout.recipient ?? "synthetic recipient"}</p></TableCell><TableCell className="font-mono text-xs">{formatMoney(payout.amount, payout.currency)}</TableCell><TableCell><Badge variant="violet">{humanizeCode(payout.batch_status)}</Badge></TableCell><TableCell className="text-right font-mono text-[10px] text-muted-foreground">{payout.transaction_id ?? "—"}</TableCell></TableRow>)}</TableBody></Table> : <p className="px-5 pb-5 text-sm text-muted-foreground">No synthetic payouts recorded.</p>}
            </CardContent>
          </Card>

          <Card>
            <CardHeader><CardTitle>Recent honey activity</CardTitle><CardDescription>Attacker-facing requests observed in the synthetic plane.</CardDescription></CardHeader>
            <CardContent className="p-0">
              {recent_activity.length ? <Table><TableHeader><TableRow><TableHead>Method</TableHead><TableHead>Path</TableHead><TableHead className="text-right">When</TableHead></TableRow></TableHeader><TableBody>{recent_activity.map((activity) => <TableRow key={activity.id}><TableCell><Badge variant="outline" className="font-mono">{activity.method}</Badge></TableCell><TableCell className="max-w-72 truncate font-mono text-xs">{activity.path}</TableCell><TableCell className="text-right text-[11px] text-muted-foreground">{relativeTime(activity.occurred_at)}</TableCell></TableRow>)}</TableBody></Table> : <p className="px-5 pb-5 text-sm text-muted-foreground">No activity recorded in this workspace.</p>}
            </CardContent>
          </Card>

          <Card>
            <CardHeader><CardTitle>Payees & transactions</CardTitle></CardHeader>
            <CardContent className="grid gap-4 sm:grid-cols-2">
              <div><h3 className="text-[11px] font-semibold uppercase tracking-wider text-muted-foreground">Payees</h3>{payees.length ? <ul className="mt-2 divide-y divide-border">{payees.map((payee) => <li key={payee.id} className="py-2"><p className="text-sm">{payee.name}</p><p className="text-[11px] text-muted-foreground">{payee.email}</p></li>)}</ul> : <p className="mt-2 text-sm text-muted-foreground">None.</p>}</div>
              <div><h3 className="text-[11px] font-semibold uppercase tracking-wider text-muted-foreground">Transactions</h3>{transactions.length ? <ul className="mt-2 divide-y divide-border">{transactions.map((txn) => <li key={txn.id} className="flex items-center justify-between gap-2 py-2"><div><p className="text-sm">{humanizeCode(txn.type)}</p><p className="font-mono text-[10px] text-muted-foreground">{txn.id} · {txn.date ?? "no date"}</p></div><span className="font-mono text-xs">{formatMoney(txn.amount, txn.currency)}</span></li>)}</ul> : <p className="mt-2 text-sm text-muted-foreground">None.</p>}</div>
            </CardContent>
          </Card>
        </div>

        <div className="space-y-4">
          <Card>
            <CardHeader><CardTitle className="flex items-center gap-2"><Sparkles className="h-4 w-4 text-signal-decoy" /> Canaries</CardTitle><CardDescription>Secret values are never sent to this view.</CardDescription></CardHeader>
            <CardContent className="space-y-2">
              {canaries.length ? canaries.map((canary) => <div key={canary.canary_id} className="rounded-lg border border-border p-3"><div className="flex items-center justify-between gap-2"><p className="text-sm font-medium">{canary.kind}</p><Badge variant={canary.triggered_at ? "danger" : canary.armed ? "warning" : "muted"}>{canary.triggered_at ? "Triggered" : canary.armed ? "Armed" : "Disarmed"}</Badge></div><p className="mt-1 break-all font-mono text-[10px] text-muted-foreground">{canary.tag}</p>{canary.triggered_at ? <p className="mt-1 flex items-center gap-1 text-[10px] text-signal-isolated"><TriangleAlert className="h-3 w-3" /> {formatDateTime(canary.triggered_at)}</p> : null}{canary.containment_incident_id ? <Link to={`/incidents/${canary.containment_incident_id}`} className="mt-1 block text-[10px] text-primary hover:underline">containment incident</Link> : null}</div>) : <p className="text-sm text-muted-foreground">No canaries in this workspace.</p>}
            </CardContent>
          </Card>

          <Card>
            <CardHeader><CardTitle>Containment notes</CardTitle></CardHeader>
            <CardContent>{containment_notes.length ? <ul className="space-y-2 text-sm text-muted-foreground">{containment_notes.map((note) => <li key={note} className="flex gap-2"><span className="mt-2 h-1 w-1 shrink-0 rounded-full bg-muted-foreground/50" aria-hidden="true" />{note}</li>)}</ul> : <p className="text-sm text-muted-foreground">No containment notes were provided.</p>}</CardContent>
          </Card>

          <Card>
            <CardHeader><CardTitle>Workspace facts</CardTitle></CardHeader>
            <CardContent className="space-y-3">
              <DataField label="Workspace session"><Link to={`/sessions/${workspace.session_id}`} className="font-mono text-xs text-primary hover:underline">{workspace.session_id}</Link></DataField>
              <DataField label="Synthetic">{workspace.synthetic ? "Yes — decoy plane" : "No"}</DataField>
              <DataField label="Merchant country">{workspace.merchant_country ?? "Unknown"}</DataField>
              <DataField label="Updated">{formatDateTime(workspace.updated_at)}</DataField>
              <DataField label="Operator access">Read-only projection</DataField>
            </CardContent>
          </Card>
        </div>
      </div>
    </div>
  );
}
