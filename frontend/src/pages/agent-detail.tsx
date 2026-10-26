import { useQuery } from "@tanstack/react-query";
import { AlertCircle, ArrowLeft, ArrowUpRight, Bot, KeyRound, Play, RefreshCw, ShieldCheck } from "lucide-react";
import { useState } from "react";
import { Link, useParams } from "react-router-dom";
import { StatusBadge } from "@/components/common/badges";
import { DataField } from "@/components/common/data-field";
import { ErrorState } from "@/components/common/error-state";
import { InfoNote } from "@/components/common/info-note";
import { DetailLoading } from "@/components/common/loading-state";
import { PageHeader } from "@/components/common/page-header";
import { AgenticPayoutDialog } from "@/features/agents/agentic-payout-dialog";
import { Badge } from "@/components/ui/badge";
import { Button } from "@/components/ui/button";
import { Card, CardContent, CardDescription, CardHeader, CardTitle } from "@/components/ui/card";
import { Table, TableBody, TableCell, TableHead, TableHeader, TableRow } from "@/components/ui/table";
import { api } from "@/lib/api";
import { useAuth } from "@/lib/auth";
import { formatDateTime, formatMoney, humanizeCode, relativeTime } from "@/lib/format";
import { cn } from "@/lib/utils";

export function AgentDetailPage() {
  const { agentId = "" } = useParams();
  const { session } = useAuth();
  const [dialogOpen, setDialogOpen] = useState(false);
  const query = useQuery({ queryKey: ["agent", agentId], queryFn: () => api.agent(session!, agentId), enabled: Boolean(session && agentId) });
  const catalog = useQuery({ queryKey: ["agent-error-catalog"], queryFn: () => api.agentErrorCatalog(session!), enabled: Boolean(session) });

  if (query.isLoading) return <DetailLoading />;
  if (query.isError) return <div className="space-y-4"><Button asChild variant="ghost" size="sm" className="-ml-2"><Link to="/agents"><ArrowLeft className="h-4 w-4" /> Back to agents</Link></Button><ErrorState error={query.error} onRetry={() => void query.refetch()} /></div>;
  if (!query.data) return null;
  const { agent, grants = [], recent_audit = [], recent_payouts = [] } = query.data;
  const errors = catalog.data?.errors ?? [];

  return (
    <div className="space-y-6">
      <div>
        <Button asChild variant="ghost" size="sm" className="-ml-2 mb-2"><Link to="/agents"><ArrowLeft className="h-4 w-4" /> Back to agents</Link></Button>
        <PageHeader
          eyebrow="Agent detail"
          title={agent.display_name}
          description={<span className="flex flex-wrap items-center gap-2"><StatusBadge status={agent.status} /><span className="text-xs">{humanizeCode(agent.agent_type)}</span>{agent.vendor ? <span className="text-xs text-muted-foreground">· {agent.vendor}</span> : null}<span className="font-mono text-[11px] text-muted-foreground">{agent.agent_id}</span></span>}
          actions={<div className="flex flex-wrap gap-2"><Button variant="outline" size="sm" onClick={() => void query.refetch()} disabled={query.isFetching}><RefreshCw className={cn("h-3.5 w-3.5", query.isFetching && "animate-spin")} /> Refresh</Button><Button size="sm" onClick={() => setDialogOpen(true)} disabled={!agent.is_active}><Play className="h-3.5 w-3.5" /> Agent payout</Button></div>}
        />
      </div>

      <div className="grid gap-4 sm:grid-cols-2 xl:grid-cols-4">
        <Card className="p-4"><p className="text-[11px] uppercase tracking-wider text-muted-foreground">Scopes</p><p className="mt-1 text-lg font-semibold">{agent.scopes?.length ?? 0}</p><div className="mt-1 flex flex-wrap gap-1">{agent.scopes?.map((scope) => <span key={scope} className="rounded bg-muted px-1 py-0.5 font-mono text-[9px]">{scope}</span>)}</div></Card>
        <Card className="p-4"><p className="text-[11px] uppercase tracking-wider text-muted-foreground">Payout ceiling</p><p className="mt-1 text-lg font-semibold">{agent.max_payout_amount != null ? formatMoney(agent.max_payout_amount, "USD") : "Unbounded"}</p><p className="text-[10px] text-muted-foreground">server-enforced, local UI does not authorize</p></Card>
        <Card className="p-4"><p className="text-[11px] uppercase tracking-wider text-muted-foreground">Grants</p><p className="mt-1 text-lg font-semibold">{agent.active_grants} active</p><p className="text-[10px] text-muted-foreground">{agent.total_grants} issued in total</p></Card>
        <Card className="p-4"><p className="text-[11px] uppercase tracking-wider text-muted-foreground">Audit attempts</p><p className="mt-1 text-lg font-semibold">{agent.audit_attempts}</p><p className="text-[10px] text-muted-foreground">last {agent.last_activity_at ? relativeTime(agent.last_activity_at) : "never"}</p></Card>
      </div>

      {!agent.is_active ? <InfoNote tone="warning" title="Agent is not active">The server will fail closed for an inactive agent. The payment action is unavailable; this console does not activate agents.</InfoNote> : null}

      <div className="grid gap-4 xl:grid-cols-3">
        <div className="space-y-4 xl:col-span-2">
          <Card>
            <CardHeader><CardTitle className="flex items-center gap-2"><KeyRound className="h-4 w-4 text-primary" /> Authorization grants</CardTitle><CardDescription>Server-issued delegations. Expired, consumed and revoked grants remain visible for audit.</CardDescription></CardHeader>
            <CardContent className="p-0">
              {grants.length ? <Table><TableHeader><TableRow><TableHead>Grant</TableHead><TableHead>Scopes</TableHead><TableHead>Limit</TableHead><TableHead>Status</TableHead><TableHead>Expires</TableHead><TableHead className="text-right">Session</TableHead></TableRow></TableHeader><TableBody>{grants.map((grant) => (
                <TableRow key={grant.grant_id}>
                  <TableCell><span className="font-mono text-[11px]">{grant.grant_id.slice(0, 12)}…</span><p className="text-[10px] text-muted-foreground">issued {formatDateTime(grant.issued_at)}</p></TableCell>
                  <TableCell><div className="flex flex-wrap gap-1">{grant.scopes?.map((scope) => <span key={scope} className="rounded bg-muted px-1 py-0.5 font-mono text-[9px]">{scope}</span>)}</div></TableCell>
                  <TableCell className="font-mono text-xs">{grant.max_amount != null ? formatMoney(grant.max_amount, "USD") : "—"}</TableCell>
                  <TableCell><StatusBadge status={grant.status} />{grant.revoked_at ? <p className="text-[10px] text-signal-isolated">revoked {relativeTime(grant.revoked_at)}</p> : grant.consumed_at ? <p className="text-[10px] text-muted-foreground">consumed {relativeTime(grant.consumed_at)}</p> : null}</TableCell>
                  <TableCell className="whitespace-nowrap text-[11px] text-muted-foreground">{formatDateTime(grant.expires_at)}</TableCell>
                  <TableCell className="text-right">{grant.session_id ? <Link to={`/sessions/${grant.session_id}`} className="font-mono text-[10px] text-primary hover:underline">{grant.session_id.slice(0, 8)}…</Link> : <span className="text-[10px] text-muted-foreground">unbound</span>}</TableCell>
                </TableRow>
              ))}</TableBody></Table> : <p className="px-5 pb-5 pt-4 text-sm text-muted-foreground">No grants recorded for this agent.</p>}
            </CardContent>
          </Card>

          <Card>
            <CardHeader><CardTitle>Recent authorization audit</CardTitle><CardDescription>Fail-closed outcomes are recorded here, including rejected attempts.</CardDescription></CardHeader>
            <CardContent className="p-0">
              {recent_audit.length ? <Table><TableHeader><TableRow><TableHead>Attempt</TableHead><TableHead>Recipient</TableHead><TableHead>Amount</TableHead><TableHead>Status / outcome</TableHead><TableHead className="text-right">When</TableHead></TableRow></TableHeader><TableBody>{recent_audit.map((item) => (
                <TableRow key={item.audit_id}>
                  <TableCell><span className="font-mono text-[10px]">{item.idempotency_key}</span><p className="text-[10px] text-muted-foreground">{item.grant_id ? `grant ${item.grant_id.slice(0, 8)}…` : "no grant"}</p></TableCell>
                  <TableCell className="max-w-44 truncate text-xs">{item.recipient_email}</TableCell>
                  <TableCell className="font-mono text-xs">{formatMoney(item.amount, item.currency)}</TableCell>
                  <TableCell><StatusBadge status={item.status} /><p className="mt-0.5 text-[10px] text-muted-foreground">{item.outcome ?? "no outcome recorded"}</p>{item.payout_id ? <Link to={`/payouts/${item.payout_id}`} className="text-[10px] text-primary hover:underline">payout</Link> : null}</TableCell>
                  <TableCell className="whitespace-nowrap text-right text-[11px] text-muted-foreground">{relativeTime(item.created_at)}</TableCell>
                </TableRow>
              ))}</TableBody></Table> : <p className="px-5 pb-5 pt-4 text-sm text-muted-foreground">No audit attempts recorded.</p>}
              <div className="border-t border-border p-3"><Button asChild variant="ghost" size="sm"><Link to={`/agents/audit?agent_id=${agent.agent_id}`}>Open full audit trail <ArrowUpRight className="h-3.5 w-3.5" /></Link></Button></div>
            </CardContent>
          </Card>

          <Card>
            <CardHeader><CardTitle>Recent agent payouts</CardTitle><CardDescription>Recorded payouts attributed to this agent.</CardDescription></CardHeader>
            <CardContent className="p-0">
              {recent_payouts.length ? <Table><TableHeader><TableRow><TableHead>Payout</TableHead><TableHead>Recipient</TableHead><TableHead>Amount</TableHead><TableHead>Status</TableHead><TableHead className="text-right">Created</TableHead></TableRow></TableHeader><TableBody>{recent_payouts.map((payout) => (
                <TableRow key={payout.payout_id}><TableCell><Link to={`/payouts/${payout.payout_id}`} className="font-mono text-[11px] text-primary hover:underline">{payout.payout_id.slice(0, 8)}…</Link></TableCell><TableCell className="max-w-44 truncate text-xs">{payout.recipient_email}</TableCell><TableCell className="font-mono text-xs">{formatMoney(payout.amount, payout.currency)}</TableCell><TableCell><StatusBadge status={payout.status} /></TableCell><TableCell className="text-right text-[11px] text-muted-foreground">{relativeTime(payout.created_at)}</TableCell></TableRow>
              ))}</TableBody></Table> : <p className="px-5 pb-5 pt-4 text-sm text-muted-foreground">No payouts attributed to this agent.</p>}
            </CardContent>
          </Card>
        </div>

        <div className="space-y-4">
          <Card>
            <CardHeader><CardTitle>Registration</CardTitle></CardHeader>
            <CardContent className="space-y-3">
              <DataField label="Description">{agent.description ?? "No description provided."}</DataField>
              <DataField label="Type">{humanizeCode(agent.agent_type)}</DataField>
              <DataField label="Vendor">{agent.vendor ?? "Not specified"}</DataField>
              <DataField label="Status"><StatusBadge status={agent.status} /></DataField>
              <DataField label="Active">{agent.is_active ? "Yes" : "No"}</DataField>
              <DataField label="Last activity">{formatDateTime(agent.last_activity_at)}</DataField>
            </CardContent>
          </Card>

          <Card>
            <CardHeader><CardTitle className="flex items-center gap-2"><ShieldCheck className="h-4 w-4 text-primary" /> Scopes</CardTitle><CardDescription>Narrowed server-side; the grant must also contain the scope.</CardDescription></CardHeader>
            <CardContent><div className="flex flex-wrap gap-1.5">{agent.scopes?.length ? agent.scopes.map((scope) => <Badge key={scope} variant="outline" className="font-mono">{scope}</Badge>) : <span className="text-sm text-muted-foreground">No scopes.</span>}</div></CardContent>
          </Card>

          <Card>
            <CardHeader><CardTitle className="flex items-center gap-2"><AlertCircle className="h-4 w-4 text-signal-restricted" /> Authorization errors</CardTitle><CardDescription>Fail-closed codes the gateway may return.</CardDescription></CardHeader>
            <CardContent>
              {catalog.isError ? <ErrorState error={catalog.error} onRetry={() => void catalog.refetch()} /> : catalog.isLoading ? <div className="h-20 animate-pulse rounded bg-muted" /> : errors.length ? (
                <details className="rounded-lg border border-border bg-muted/20"><summary className="cursor-pointer px-3 py-2 text-xs font-medium">View {errors.length} error definitions</summary><ul className="max-h-96 divide-y divide-border overflow-auto border-t border-border">{errors.map((error) => <li key={error.code} className="p-3"><div className="flex items-center justify-between gap-2"><span className="font-mono text-[10px]">{error.code}</span><Badge variant="muted">{error.http_status}</Badge></div><p className="mt-1 text-xs font-medium">{error.title}</p><p className="mt-0.5 text-[11px] leading-5 text-muted-foreground">{error.explanation}</p></li>)}</ul></details>
              ) : <p className="text-sm text-muted-foreground">No catalog returned.</p>}
            </CardContent>
          </Card>
          <Button asChild variant="outline" size="sm" className="w-full"><Link to="/agents/audit"><Bot className="h-3.5 w-3.5" /> Inspection audit</Link></Button>
        </div>
      </div>

      <AgenticPayoutDialog open={dialogOpen} onOpenChange={setDialogOpen} initialAgentId={agentId} />
    </div>
  );
}
