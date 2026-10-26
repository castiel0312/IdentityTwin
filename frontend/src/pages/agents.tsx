import { useQuery } from "@tanstack/react-query";
import { Bot, BotIcon, KeyRound, Plus, RefreshCw, Search, ShieldCheck, X } from "lucide-react";
import { useDeferredValue, useState } from "react";
import { Link } from "react-router-dom";
import { StatusBadge } from "@/components/common/badges";
import { EmptyState } from "@/components/common/empty-state";
import { ErrorState } from "@/components/common/error-state";
import { InfoNote } from "@/components/common/info-note";
import { TableLoading } from "@/components/common/loading-state";
import { PageHeader } from "@/components/common/page-header";
import { Pagination } from "@/components/common/pagination";
import { AgenticPayoutDialog } from "@/features/agents/agentic-payout-dialog";
import { Button } from "@/components/ui/button";
import { Card, CardContent, CardDescription, CardHeader, CardTitle } from "@/components/ui/card";
import { Input } from "@/components/ui/input";
import { Select, SelectContent, SelectItem, SelectTrigger, SelectValue } from "@/components/ui/select";
import { Table, TableBody, TableCell, TableHead, TableHeader, TableRow } from "@/components/ui/table";
import { api } from "@/lib/api";
import { useAuth } from "@/lib/auth";
import { formatDateTime, formatMoney, humanizeCode, relativeTime } from "@/lib/format";
import { cn } from "@/lib/utils";

const PAGE_SIZE = 25;

export function AgentsPage() {
  const { session } = useAuth();
  const [page, setPage] = useState(1);
  const [search, setSearch] = useState("");
  const deferredSearch = useDeferredValue(search);
  const [status, setStatus] = useState("all");
  const [dialogOpen, setDialogOpen] = useState(false);
  const hasFilters = Boolean(search || status !== "all");
  const query = useQuery({
    queryKey: ["agents", { deferredSearch, status, page }],
    queryFn: () => api.listAgents(session!, { q: deferredSearch || undefined, status: status === "all" ? undefined : status, page, page_size: PAGE_SIZE }),
    enabled: Boolean(session),
  });
  const reset = () => { setSearch(""); setStatus("all"); setPage(1); };
  const activeOnPage = query.data?.items.filter((agent) => agent.is_active).length ?? 0;

  return (
    <div className="space-y-5">
      <PageHeader
        eyebrow="Agentic commerce"
        title="Agent registry"
        description="Registered AI agents, their delegated scopes and payout limits. Every agent initiated request is authorized and audited server-side; the console cannot grant scopes or bypass limits."
        actions={<div className="flex flex-wrap gap-2"><Button variant="outline" size="sm" onClick={() => void query.refetch()} disabled={query.isFetching}><RefreshCw className={cn("h-3.5 w-3.5", query.isFetching && "animate-spin")} /> Refresh</Button><Button size="sm" onClick={() => setDialogOpen(true)}><Plus className="h-3.5 w-3.5" /> Agent payout</Button></div>}
      />

      <div className="grid gap-4 sm:grid-cols-3">
        <Card className="p-4"><p className="text-[11px] uppercase tracking-wider text-muted-foreground">Registered agents</p><p className="mt-1 text-2xl font-semibold">{query.data?.total ?? "—"}</p><p className="text-[11px] text-muted-foreground">Tenant scope only</p></Card>
        <Card className="p-4"><p className="text-[11px] uppercase tracking-wider text-muted-foreground">Active on this page</p><p className="mt-1 text-2xl font-semibold">{query.isLoading ? "—" : activeOnPage}</p><p className="text-[11px] text-muted-foreground">of {query.data?.items.length ?? 0} listed</p></Card>
        <Card className="p-4"><p className="text-[11px] uppercase tracking-wider text-muted-foreground">Authorization</p><p className="mt-1 flex items-center gap-1.5 text-sm font-medium"><ShieldCheck className="h-4 w-4 text-primary" /> Server resolved</p><p className="text-[11px] text-muted-foreground">Agent identity cannot be claimed by request body</p></Card>
      </div>

      <InfoNote tone="info" title="No self-asserted identity">
        Agent requests must present an agent id and an authorization grant id. The server resolves identity, scopes, amount ceilings and session binding from its registry and fails closed. The console does not display or accept arbitrary trust claims.
      </InfoNote>

      <Card>
        <CardHeader className="pb-3"><CardTitle>Agents</CardTitle><CardDescription>Select an agent to inspect grants, audit history and recent payouts.</CardDescription></CardHeader>
        <CardContent className="space-y-3 border-t border-border p-4">
          <div className="grid gap-2 sm:grid-cols-[minmax(0,2fr)_minmax(0,1fr)_auto]">
            <div className="relative"><Search className="pointer-events-none absolute left-2.5 top-1/2 h-3.5 w-3.5 -translate-y-1/2 text-muted-foreground" aria-hidden="true" /><Input value={search} onChange={(e) => { setSearch(e.target.value); setPage(1); }} placeholder="Search agent name, vendor, type…" className="pl-8" aria-label="Search agents" /></div>
            <Select value={status} onValueChange={(value) => { setStatus(value); setPage(1); }}><SelectTrigger aria-label="Filter by agent status"><SelectValue /></SelectTrigger><SelectContent><SelectItem value="all">All statuses</SelectItem><SelectItem value="active">Active</SelectItem><SelectItem value="suspended">Suspended</SelectItem><SelectItem value="revoked">Revoked</SelectItem></SelectContent></Select>
            <Button variant="ghost" size="sm" onClick={reset} disabled={!hasFilters}><X className="h-3.5 w-3.5" /> Clear</Button>
          </div>
          <div className="flex items-center justify-between gap-2"><p className="text-xs text-muted-foreground">{query.data ? `${query.data.total} agents match` : "Loading agents"}</p><Button asChild variant="ghost" size="sm"><Link to="/agents/audit"><KeyRound className="h-3.5 w-3.5" /> Full audit trail</Link></Button></div>
        </CardContent>
        {query.isError ? <div className="p-4"><ErrorState error={query.error} onRetry={() => void query.refetch()} /></div> : null}
        {query.isLoading ? <TableLoading rows={5} columns={6} /> : query.data?.items.length === 0 ? (
          <EmptyState icon={BotIcon} title={hasFilters ? "No agents match these filters" : "No agents registered"} description={hasFilters ? "Adjust or clear the filters to inspect all agents in tenant scope." : "Agents appear after they are registered and granted by the backend. The console cannot create them."} action={hasFilters ? <Button variant="outline" onClick={reset}>Clear filters</Button> : undefined} />
        ) : (
          <>
            <Table><TableHeader><TableRow><TableHead>Agent</TableHead><TableHead>Status</TableHead><TableHead>Scopes</TableHead><TableHead>Limit</TableHead><TableHead>Grants / audits</TableHead><TableHead className="text-right">Last activity</TableHead></TableRow></TableHeader><TableBody>
              {query.data?.items.map((agent) => (
                <TableRow key={agent.agent_id}>
                  <TableCell><Link to={`/agents/${agent.agent_id}`} className="flex items-center gap-2 text-sm font-medium text-primary hover:underline"><span className="flex h-7 w-7 items-center justify-center rounded-md bg-muted"><Bot className="h-4 w-4" /></span>{agent.display_name}</Link><p className="mt-0.5 text-[10px] text-muted-foreground">{humanizeCode(agent.agent_type)}{agent.vendor ? ` · ${agent.vendor}` : ""}</p></TableCell>
                  <TableCell><StatusBadge status={agent.status} /></TableCell>
                  <TableCell><div className="flex max-w-52 flex-wrap gap-1">{agent.scopes?.length ? agent.scopes.map((scope) => <span key={scope} className="rounded bg-muted px-1.5 py-0.5 font-mono text-[10px]">{scope}</span>) : <span className="text-xs text-muted-foreground">None</span>}</div></TableCell>
                  <TableCell><span className="font-mono text-xs">{agent.max_payout_amount != null ? formatMoney(agent.max_payout_amount, "USD") : "No ceiling"}</span></TableCell>
                  <TableCell><p className="text-xs">{agent.active_grants} active / {agent.total_grants} total</p><p className="text-[10px] text-muted-foreground">{agent.audit_attempts} audited attempts</p></TableCell>
                  <TableCell className="whitespace-nowrap text-right text-[11px] text-muted-foreground">{agent.last_activity_at ? relativeTime(agent.last_activity_at) : "Never"}<p className="text-[10px]">{agent.last_activity_at ? formatDateTime(agent.last_activity_at) : ""}</p></TableCell>
                </TableRow>
              ))}
            </TableBody></Table>
            <Pagination page={query.data!.page} pageSize={query.data!.page_size} total={query.data!.total} onPageChange={setPage} label="agents" />
          </>
        )}
      </Card>
      <AgenticPayoutDialog open={dialogOpen} onOpenChange={setDialogOpen} />
    </div>
  );
}
