import { useQuery } from "@tanstack/react-query";
import { ArrowLeft, RefreshCw, Search, ShieldAlert, X } from "lucide-react";
import { useState } from "react";
import { Link, useSearchParams } from "react-router-dom";
import { StatusBadge } from "@/components/common/badges";
import { EmptyState } from "@/components/common/empty-state";
import { ErrorState } from "@/components/common/error-state";
import { InfoNote } from "@/components/common/info-note";
import { TableLoading } from "@/components/common/loading-state";
import { PageHeader } from "@/components/common/page-header";
import { Pagination } from "@/components/common/pagination";
import { Button } from "@/components/ui/button";
import { Card, CardContent } from "@/components/ui/card";
import { Input } from "@/components/ui/input";
import { Select, SelectContent, SelectItem, SelectTrigger, SelectValue } from "@/components/ui/select";
import { Table, TableBody, TableCell, TableHead, TableHeader, TableRow } from "@/components/ui/table";
import { api } from "@/lib/api";
import { useAuth } from "@/lib/auth";
import { formatDateTime, formatMoney, relativeTime } from "@/lib/format";
import { cn } from "@/lib/utils";

const PAGE_SIZE = 25;

export function AgentAuditPage() {
  const { session } = useAuth();
  const [params] = useSearchParams();
  const [page, setPage] = useState(1);
  const [agentId, setAgentId] = useState(params.get("agent_id") ?? "");
  const [status, setStatus] = useState("all");
  const hasFilters = Boolean(agentId || status !== "all");
  const query = useQuery({
    queryKey: ["agent-audit", { agentId, status, page }],
    queryFn: () => api.listAgentAudit(session!, { agent_id: agentId || undefined, status: status === "all" ? undefined : status, page, page_size: PAGE_SIZE }),
    enabled: Boolean(session),
  });
  const reset = () => { setAgentId(""); setStatus("all"); setPage(1); };

  return (
    <div className="space-y-5">
      <Button asChild variant="ghost" size="sm" className="-ml-2"><Link to="/agents"><ArrowLeft className="h-4 w-4" /> Back to agents</Link></Button>
      <PageHeader eyebrow="Agentic commerce" title="Agent audit trail" description="Every agent attempt, including rejected and blocked authorization outcomes. Audit records are server-written and scoped to the authenticated merchant." actions={<Button variant="outline" size="sm" onClick={() => void query.refetch()} disabled={query.isFetching}><RefreshCw className={cn("h-3.5 w-3.5", query.isFetching && "animate-spin")} /> Refresh</Button>} />

      <InfoNote tone="info" title="Audit is not authorization">An accepted audit entry is not a trust decision made by this console. The gateway's authorization result and payout outcome remain authoritative.</InfoNote>

      <Card>
        <CardContent className="space-y-3 p-4">
          <div className="grid gap-2 sm:grid-cols-[minmax(0,2fr)_minmax(0,1fr)_auto]">
            <div className="relative"><Search className="pointer-events-none absolute left-2.5 top-1/2 h-3.5 w-3.5 -translate-y-1/2 text-muted-foreground" aria-hidden="true" /><Input value={agentId} onChange={(e) => { setAgentId(e.target.value); setPage(1); }} placeholder="Filter by agent UUID" className="pl-8 font-mono text-xs" aria-label="Filter audit by agent id" /></div>
            <Select value={status} onValueChange={(value) => { setStatus(value); setPage(1); }}><SelectTrigger aria-label="Filter audit by status"><SelectValue /></SelectTrigger><SelectContent><SelectItem value="all">All audit statuses</SelectItem><SelectItem value="accepted">Accepted</SelectItem><SelectItem value="rejected">Rejected</SelectItem><SelectItem value="blocked">Blocked</SelectItem></SelectContent></Select>
            <Button variant="ghost" size="sm" onClick={reset} disabled={!hasFilters}><X className="h-3.5 w-3.5" /> Clear</Button>
          </div>
          <p className="text-xs text-muted-foreground">{query.data ? `${query.data.total} audit attempts match` : "Loading audit attempts"}</p>
        </CardContent>

        {query.isError ? <div className="p-4"><ErrorState error={query.error} onRetry={() => void query.refetch()} /></div> : null}
        {query.isLoading ? <TableLoading rows={8} columns={6} /> : query.data?.items.length === 0 ? (
          <EmptyState icon={ShieldAlert} title={hasFilters ? "No audit entries match" : "No agent attempts recorded"} description={hasFilters ? "Adjust or clear the filters to inspect all agent audit attempts." : "Agent authorization attempts, including failures, appear here once the gateway records them."} action={hasFilters ? <Button variant="outline" onClick={reset}>Clear filters</Button> : undefined} />
        ) : (
          <>
            <Table><TableHeader><TableRow><TableHead>Attempt</TableHead><TableHead>Agent</TableHead><TableHead>Recipient / amount</TableHead><TableHead>Result</TableHead><TableHead>Links</TableHead><TableHead className="text-right">When</TableHead></TableRow></TableHeader><TableBody>
              {query.data?.items.map((item) => (
                <TableRow key={item.audit_id}>
                  <TableCell><span className="break-all font-mono text-[10px]">{item.idempotency_key}</span><p className="mt-0.5 text-[10px] text-muted-foreground">{item.audit_id.slice(0, 8)}…</p></TableCell>
                  <TableCell>{item.agent_display_name ? <Link to={`/agents/${item.agent_id}`} className="text-xs font-medium text-primary hover:underline">{item.agent_display_name}</Link> : <span className="font-mono text-[10px]">{item.agent_id}</span>}</TableCell>
                  <TableCell><p className="max-w-48 truncate text-xs">{item.recipient_email}</p><p className="font-mono text-[11px]">{formatMoney(item.amount, item.currency)}</p></TableCell>
                  <TableCell><StatusBadge status={item.status} /><p className="mt-0.5 break-all font-mono text-[10px] text-muted-foreground">{item.outcome ?? "No outcome field"}</p>{Object.keys(item.agent_context ?? {}).length ? <details className="mt-1"><summary className="cursor-pointer text-[10px] text-primary">Context</summary><pre className="mt-1 max-h-32 overflow-auto rounded bg-muted/40 p-2 font-mono text-[9px]">{JSON.stringify(item.agent_context, null, 2)}</pre></details> : null}</TableCell>
                  <TableCell><div className="space-y-0.5">{item.session_id ? <Link to={`/sessions/${item.session_id}`} className="block text-[10px] text-primary hover:underline">session {item.session_id.slice(0, 8)}…</Link> : null}{item.payout_id ? <Link to={`/payouts/${item.payout_id}`} className="block text-[10px] text-primary hover:underline">payout {item.payout_id.slice(0, 8)}…</Link> : null}{item.grant_id ? <Link to={`/agents/${item.agent_id}`} className="block font-mono text-[10px] text-muted-foreground hover:underline">grant {item.grant_id.slice(0, 8)}…</Link> : null}</div></TableCell>
                  <TableCell className="whitespace-nowrap text-right text-[11px] text-muted-foreground">{relativeTime(item.created_at)}<p className="text-[10px]">{formatDateTime(item.created_at)}</p></TableCell>
                </TableRow>
              ))}
            </TableBody></Table>
            <Pagination page={query.data!.page} pageSize={query.data!.page_size} total={query.data!.total} onPageChange={setPage} label="audit attempts" />
          </>
        )}
      </Card>
    </div>
  );
}
