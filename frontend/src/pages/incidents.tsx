import { useQuery } from "@tanstack/react-query";
import { RefreshCw, Search, Siren, X } from "lucide-react";
import { useDeferredValue, useState } from "react";
import { Link } from "react-router-dom";
import { SeverityBadge, StatusBadge } from "@/components/common/badges";
import { EmptyState } from "@/components/common/empty-state";
import { ErrorState } from "@/components/common/error-state";
import { TableLoading } from "@/components/common/loading-state";
import { MetaStrip } from "@/components/common/meta-strip";
import { PageHeader } from "@/components/common/page-header";
import { Pagination } from "@/components/common/pagination";
import { RiskMeter } from "@/components/common/risk-meter";
import { Badge } from "@/components/ui/badge";
import { Button } from "@/components/ui/button";
import { Card, CardContent } from "@/components/ui/card";
import { Input } from "@/components/ui/input";
import { Select, SelectContent, SelectItem, SelectTrigger, SelectValue } from "@/components/ui/select";
import { Table, TableBody, TableCell, TableHead, TableHeader, TableRow } from "@/components/ui/table";
import { api } from "@/lib/api";
import { useAuth } from "@/lib/auth";
import { formatDateTime, relativeTime, titleCase } from "@/lib/format";
import { cn } from "@/lib/utils";

const PAGE_SIZE = 25;

export function IncidentsPage() {
  const { session } = useAuth();
  const [page, setPage] = useState(1);
  const [search, setSearch] = useState("");
  const deferredSearch = useDeferredValue(search);
  const [status, setStatus] = useState("all");
  const [severity, setSeverity] = useState("all");
  const [start, setStart] = useState("");
  const [end, setEnd] = useState("");
  const [sort, setSort] = useState("-created_at");
  const hasFilters = Boolean(search || status !== "all" || severity !== "all" || start || end);
  const reset = () => { setSearch(""); setStatus("all"); setSeverity("all"); setStart(""); setEnd(""); setSort("-created_at"); setPage(1); };
  const query = useQuery({
    queryKey: ["incidents", { deferredSearch, status, severity, start, end, sort, page }],
    queryFn: () => api.listIncidents(session!, {
      q: deferredSearch || undefined,
      status: status === "all" ? undefined : status,
      severity: severity === "all" ? undefined : severity,
      start: start ? new Date(`${start}T00:00:00`).toISOString() : undefined,
      end: end ? new Date(`${end}T23:59:59`).toISOString() : undefined,
      sort, page, page_size: PAGE_SIZE,
    }),
    enabled: Boolean(session),
  });
  const pageItems = query.data?.items ?? [];
  const totalPages = query.data ? Math.max(1, Math.ceil(query.data.total / query.data.page_size)) : null;
  const openOnPage = pageItems.filter((incident) => incident.status?.toUpperCase() === "OPEN").length;
  const severityRank: Record<string, number> = { CRITICAL: 4, HIGH: 3, MEDIUM: 2, LOW: 1 };
  const highestSeverity = pageItems.reduce<string | null>((highest, incident) => {
    const candidate = incident.severity?.toUpperCase();
    if (!candidate) return highest;
    if (!highest || (severityRank[candidate] ?? 0) > (severityRank[highest] ?? 0)) return candidate;
    return highest;
  }, null);

  return (
    <div className="space-y-5">
      <PageHeader eyebrow="Incident response" title="Security incidents" description="Review server-opened incidents, then use authorization-aware actions. Approval never re-enables a session or re-executes a payout." actions={<Button variant="outline" size="sm" onClick={() => void query.refetch()} disabled={query.isFetching}><RefreshCw className={cn("h-3.5 w-3.5", query.isFetching && "animate-spin")} /> Refresh</Button>} />

      <MetaStrip
        items={[
          {
            label: "Incidents in scope",
            value: query.data ? query.data.total.toLocaleString() : "—",
            hint: "Tenant-scoped server projection",
          },
          {
            label: "Open · this page",
            value: query.data ? openOnPage : "—",
            hint: "Page-level reading, not a tenant total",
          },
          {
            label: "Highest severity · this page",
            value: highestSeverity ? <SeverityBadge severity={highestSeverity} /> : "—",
            hint: "Ordered critical → low",
          },
          {
            label: "Filter state",
            value: <Badge variant={hasFilters ? "warning" : "muted"}>{hasFilters ? "Filtered" : "Unfiltered"}</Badge>,
            hint: `Page ${query.data?.page ?? "—"} of ${totalPages ?? "—"}`,
          },
        ]}
      />

      <Card>
        <CardContent className="space-y-3 p-4">
          <div className="grid gap-2 md:grid-cols-2 xl:grid-cols-[minmax(0,2fr)_repeat(2,minmax(0,1fr))_minmax(0,1.4fr)_auto]">
            <div className="relative"><Search className="pointer-events-none absolute left-2.5 top-1/2 h-3.5 w-3.5 -translate-y-1/2 text-muted-foreground" aria-hidden="true" /><Input value={search} onChange={(e) => { setSearch(e.target.value); setPage(1); }} placeholder="Search title, description, trigger…" className="pl-8" aria-label="Search incidents" /></div>
            <Select value={status} onValueChange={(value) => { setStatus(value); setPage(1); }}><SelectTrigger aria-label="Filter by incident status"><SelectValue /></SelectTrigger><SelectContent><SelectItem value="all">All statuses</SelectItem><SelectItem value="OPEN">Open</SelectItem><SelectItem value="UNDER_REVIEW">Under review</SelectItem><SelectItem value="APPROVED">Approved</SelectItem><SelectItem value="RESOLVED">Resolved</SelectItem><SelectItem value="REJECTED">Rejected</SelectItem></SelectContent></Select>
            <Select value={severity} onValueChange={(value) => { setSeverity(value); setPage(1); }}><SelectTrigger aria-label="Filter by severity"><SelectValue /></SelectTrigger><SelectContent><SelectItem value="all">All severities</SelectItem><SelectItem value="LOW">Low</SelectItem><SelectItem value="MEDIUM">Medium</SelectItem><SelectItem value="HIGH">High</SelectItem><SelectItem value="CRITICAL">Critical</SelectItem></SelectContent></Select>
            <div className="flex gap-2"><Input value={start} onChange={(e) => { setStart(e.target.value); setPage(1); }} type="date" aria-label="Opened after" /><Input value={end} onChange={(e) => { setEnd(e.target.value); setPage(1); }} type="date" aria-label="Opened before" /></div>
            <Button variant="ghost" size="sm" onClick={reset} disabled={!hasFilters}><X className="h-3.5 w-3.5" /> Clear</Button>
          </div>
          <div className="flex items-center justify-between gap-2"><p className="text-xs text-muted-foreground">{query.data ? `${query.data.total} incidents in scope` : "Loading incidents"}</p><Select value={sort} onValueChange={(value) => { setSort(value); setPage(1); }}><SelectTrigger className="h-8 w-48" aria-label="Sort incidents"><SelectValue /></SelectTrigger><SelectContent><SelectItem value="-created_at">Newest first</SelectItem><SelectItem value="created_at">Oldest first</SelectItem><SelectItem value="-risk_score">Highest risk</SelectItem><SelectItem value="risk_score">Lowest risk</SelectItem><SelectItem value="severity">Severity</SelectItem><SelectItem value="status">Status</SelectItem></SelectContent></Select></div>
        </CardContent>
        {query.isError ? <div className="p-4"><ErrorState error={query.error} onRetry={() => void query.refetch()} /></div> : null}
        {query.isLoading ? <TableLoading rows={8} columns={6} /> : query.data?.items.length === 0 ? (
          <EmptyState icon={Siren} title={hasFilters ? "No incidents match these filters" : "No incidents recorded"} description={hasFilters ? "Adjust or clear the filters to inspect all incidents in tenant scope." : "The backend opens incidents when containment or policy requires human review."} action={hasFilters ? <Button variant="outline" onClick={reset}>Clear filters</Button> : undefined} />
        ) : (
          <>
            <Table><TableHeader><TableRow><TableHead>Incident</TableHead><TableHead>Severity</TableHead><TableHead>Status</TableHead><TableHead>Risk</TableHead><TableHead>Trigger</TableHead><TableHead className="text-right">Opened</TableHead></TableRow></TableHeader><TableBody>
              {query.data?.items.map((incident) => (
                <TableRow key={incident.incident_id}>
                  <TableCell><Link to={`/incidents/${incident.incident_id}`} className="text-sm font-medium text-primary hover:underline">{incident.title}</Link><p className="mt-0.5 max-w-80 truncate text-[11px] text-muted-foreground">{incident.description}</p></TableCell>
                  <TableCell><SeverityBadge severity={incident.severity} /></TableCell>
                  <TableCell><StatusBadge status={incident.status} /></TableCell>
                  <TableCell><RiskMeter score={incident.risk_score} /></TableCell>
                  <TableCell><span className="rounded bg-muted px-1.5 py-0.5 font-mono text-[10px]">{incident.trigger_reason}</span></TableCell>
                  <TableCell className="whitespace-nowrap text-right text-[11px] text-muted-foreground">{formatDateTime(incident.created_at)}<p className="text-[10px]">{relativeTime(incident.created_at)}</p></TableCell>
                </TableRow>
              ))}
            </TableBody></Table>
            <Pagination page={query.data!.page} pageSize={query.data!.page_size} total={query.data!.total} onPageChange={setPage} label="incidents" />
          </>
        )}
      </Card>
      <p className="text-[11px] text-muted-foreground">Incident status labels: {["OPEN", "UNDER_REVIEW", "APPROVED", "RESOLVED", "REJECTED"].map(titleCase).join(" · ")}. Actions are gated by the backend, not hidden only in the UI.</p>
    </div>
  );
}
