import { useQuery } from "@tanstack/react-query";
import { Fingerprint, RefreshCw, Search, ShieldCheck, UserRound, Users, X } from "lucide-react";
import { useDeferredValue, useState } from "react";
import { Link } from "react-router-dom";
import { StatusBadge, TrustBadge } from "@/components/common/badges";
import { EmptyState } from "@/components/common/empty-state";
import { ErrorState } from "@/components/common/error-state";
import { TableLoading } from "@/components/common/loading-state";
import { PageHeader } from "@/components/common/page-header";
import { Pagination } from "@/components/common/pagination";
import { RiskMeter } from "@/components/common/risk-meter";
import { Button } from "@/components/ui/button";
import { Card, CardContent, CardDescription, CardHeader, CardTitle } from "@/components/ui/card";
import { Input } from "@/components/ui/input";
import { Select, SelectContent, SelectItem, SelectTrigger, SelectValue } from "@/components/ui/select";
import { Table, TableBody, TableCell, TableHead, TableHeader, TableRow } from "@/components/ui/table";
import { Tabs, TabsContent, TabsList, TabsTrigger } from "@/components/ui/tabs";
import { api } from "@/lib/api";
import { useAuth } from "@/lib/auth";
import { formatDateTime, relativeTime } from "@/lib/format";

const PAGE_SIZE = 25;

function SessionsTab() {
  const { session } = useAuth();
  const [page, setPage] = useState(1);
  const [search, setSearch] = useState("");
  const deferredSearch = useDeferredValue(search);
  const [status, setStatus] = useState("all");
  const [trust, setTrust] = useState("all");
  const [sort, setSort] = useState("-last_activity_at");

  const query = useQuery({
    queryKey: ["sessions", { deferredSearch, status, trust, sort, page }],
    queryFn: () => api.listSessions(session!, {
      q: deferredSearch || undefined,
      status: status === "all" ? undefined : status,
      trust_level: trust === "all" ? undefined : trust,
      sort, page, page_size: PAGE_SIZE,
    }),
    enabled: Boolean(session),
  });
  const hasFilters = Boolean(search || status !== "all" || trust !== "all");
  const reset = () => { setSearch(""); setStatus("all"); setTrust("all"); setSort("-last_activity_at"); setPage(1); };

  return (
    <Card>
      <CardContent className="space-y-3 p-4">
        <div className="grid gap-2 sm:grid-cols-2 lg:grid-cols-[minmax(0,2fr)_minmax(0,1fr)_minmax(0,1fr)_auto]">
          <div className="relative">
            <Search className="pointer-events-none absolute left-2.5 top-1/2 h-3.5 w-3.5 -translate-y-1/2 text-muted-foreground" aria-hidden="true" />
            <Input value={search} onChange={(e) => { setSearch(e.target.value); setPage(1); }} placeholder="Search session, user, device, IP…" className="pl-8" aria-label="Search sessions" />
          </div>
          <Select value={status} onValueChange={(value) => { setStatus(value); setPage(1); }}>
            <SelectTrigger aria-label="Filter by session status"><SelectValue /></SelectTrigger>
            <SelectContent><SelectItem value="all">All statuses</SelectItem><SelectItem value="active">Active</SelectItem><SelectItem value="revoked">Revoked</SelectItem><SelectItem value="expired">Expired</SelectItem></SelectContent>
          </Select>
          <Select value={trust} onValueChange={(value) => { setTrust(value); setPage(1); }}>
            <SelectTrigger aria-label="Filter by trust level"><SelectValue /></SelectTrigger>
            <SelectContent><SelectItem value="all">All trust levels</SelectItem><SelectItem value="NORMAL">Normal</SelectItem><SelectItem value="RESTRICTED">Restricted</SelectItem><SelectItem value="DECOY">Decoy</SelectItem><SelectItem value="ISOLATED">Isolated</SelectItem></SelectContent>
          </Select>
          <Button variant="ghost" size="sm" onClick={reset} disabled={!hasFilters}><X className="h-3.5 w-3.5" /> Clear</Button>
        </div>
        <div className="flex flex-wrap items-center justify-between gap-2">
          <p className="text-xs text-muted-foreground">{query.data ? `${query.data.total} sessions in tenant scope` : "Loading sessions"}</p>
          <Select value={sort} onValueChange={(value) => { setSort(value); setPage(1); }}>
            <SelectTrigger className="h-8 w-48" aria-label="Sort sessions"><SelectValue /></SelectTrigger>
            <SelectContent><SelectItem value="-last_activity_at">Most recent</SelectItem><SelectItem value="last_activity_at">Oldest activity</SelectItem><SelectItem value="-risk_score">Highest risk</SelectItem><SelectItem value="risk_score">Lowest risk</SelectItem><SelectItem value="trust_level">Trust level</SelectItem></SelectContent>
          </Select>
        </div>
      </CardContent>
      {query.isError ? <div className="p-4"><ErrorState error={query.error} onRetry={() => void query.refetch()} /></div> : null}
      {query.isLoading ? <TableLoading rows={8} columns={6} /> : query.data?.items.length === 0 ? (
        <EmptyState icon={Fingerprint} title={hasFilters ? "No sessions match these filters" : "No sessions recorded"} description={hasFilters ? "Adjust or clear the filters to inspect the tenant session inventory." : "Sessions appear here as they are created through the backend."} action={hasFilters ? <Button variant="outline" onClick={reset}>Clear filters</Button> : undefined} />
      ) : (
        <>
          <Table>
            <TableHeader><TableRow><TableHead>Session</TableHead><TableHead>Identity</TableHead><TableHead>Trust</TableHead><TableHead>Status</TableHead><TableHead>Device / IP</TableHead><TableHead className="text-right">Last activity</TableHead></TableRow></TableHeader>
            <TableBody>
              {query.data?.items.map((item) => (
                <TableRow key={item.session_id}>
                  <TableCell><Link to={`/sessions/${item.session_id}`} className="font-mono text-xs text-primary hover:underline">{item.session_id.slice(0, 8)}…</Link><p className="mt-0.5 text-[10px] text-muted-foreground">since {formatDateTime(item.created_at)}</p></TableCell>
                  <TableCell><Link to={`/identities/${item.user_id}`} className="font-mono text-[11px] text-primary hover:underline">{item.user_id.slice(0, 8)}…</Link></TableCell>
                  <TableCell><div className="space-y-1"><TrustBadge level={item.trust_level} /><RiskMeter score={item.risk_score} /></div></TableCell>
                  <TableCell><StatusBadge status={item.status} /></TableCell>
                  <TableCell><p className="max-w-44 truncate text-xs">{item.device_fingerprint ?? "—"}</p><p className="font-mono text-[10px] text-muted-foreground">{item.ip_address ?? "—"}</p></TableCell>
                  <TableCell className="whitespace-nowrap text-right text-[11px] text-muted-foreground">{relativeTime(item.last_activity_at)}</TableCell>
                </TableRow>
              ))}
            </TableBody>
          </Table>
          <Pagination page={query.data!.page} pageSize={query.data!.page_size} total={query.data!.total} onPageChange={setPage} label="sessions" />
        </>
      )}
    </Card>
  );
}

function IdentitiesTab() {
  const { session } = useAuth();
  const [page, setPage] = useState(1);
  const [search, setSearch] = useState("");
  const deferredSearch = useDeferredValue(search);
  const [hasTwin, setHasTwin] = useState("all");
  const query = useQuery({
    queryKey: ["identities", { deferredSearch, hasTwin, page }],
    queryFn: () => api.listIdentities(session!, { q: deferredSearch || undefined, has_twin: hasTwin === "all" ? undefined : hasTwin === "yes", page, page_size: PAGE_SIZE }),
    enabled: Boolean(session),
  });
  return (
    <Card>
      <CardContent className="space-y-3 p-4">
        <div className="grid gap-2 sm:grid-cols-[minmax(0,2fr)_minmax(0,1fr)]">
          <div className="relative"><Search className="pointer-events-none absolute left-2.5 top-1/2 h-3.5 w-3.5 -translate-y-1/2 text-muted-foreground" aria-hidden="true" /><Input value={search} onChange={(e) => { setSearch(e.target.value); setPage(1); }} placeholder="Search identity email…" className="pl-8" aria-label="Search identities" /></div>
          <Select value={hasTwin} onValueChange={(value) => { setHasTwin(value); setPage(1); }}>
            <SelectTrigger aria-label="Filter identities by behavioural twin"><SelectValue /></SelectTrigger>
            <SelectContent><SelectItem value="all">All identities</SelectItem><SelectItem value="yes">Has behavioural twin</SelectItem><SelectItem value="no">No twin yet</SelectItem></SelectContent>
          </Select>
        </div>
      </CardContent>
      {query.isError ? <div className="p-4"><ErrorState error={query.error} onRetry={() => void query.refetch()} /></div> : null}
      {query.isLoading ? <TableLoading rows={6} columns={5} /> : query.data?.items.length === 0 ? (
        <EmptyState icon={Users} title="No identities found" description="Identity projections appear when users and sessions exist for this merchant." />
      ) : (
        <>
          <Table>
            <TableHeader><TableRow><TableHead>Identity</TableHead><TableHead>Role</TableHead><TableHead>Behavioural twin</TableHead><TableHead>Sessions</TableHead><TableHead className="text-right">Last activity</TableHead></TableRow></TableHeader>
            <TableBody>
              {query.data?.items.map((identity) => (
                <TableRow key={identity.user_id}>
                  <TableCell><Link to={`/identities/${identity.user_id}`} className="text-sm font-medium text-primary hover:underline">{identity.email}</Link><p className="font-mono text-[10px] text-muted-foreground">{identity.user_id}</p></TableCell>
                  <TableCell><span className="text-xs capitalize">{identity.role}</span><div className="mt-1"><StatusBadge status={identity.is_active ? "active" : "expired"} /></div></TableCell>
                  <TableCell>{identity.twin ? <div><p className="text-xs">{identity.twin.confirmed_device_count} devices · {identity.twin.confirmed_payee_count} payees</p><p className="text-[10px] text-muted-foreground">{identity.twin.sample_count} samples{identity.twin.is_provisional ? " · provisional" : ""}</p></div> : <span className="text-xs text-muted-foreground">Not established</span>}</TableCell>
                  <TableCell><p className="text-xs">{identity.active_sessions} active / {identity.sessions_total} total</p><RiskMeter score={identity.max_risk_score} /></TableCell>
                  <TableCell className="text-right text-[11px] text-muted-foreground">{relativeTime(identity.last_activity_at)}</TableCell>
                </TableRow>
              ))}
            </TableBody>
          </Table>
          <Pagination page={query.data!.page} pageSize={query.data!.page_size} total={query.data!.total} onPageChange={setPage} label="identities" />
        </>
      )}
    </Card>
  );
}

export function SessionsPage() {
  const { session } = useAuth();
  const [tab, setTab] = useState("sessions");
  return (
    <div className="space-y-5">
      <PageHeader
        eyebrow="Identity surface"
        title="Sessions & identities"
        description="Investigate trust state, the risk ledger, sequence markers and the behavioural twin. All values are projected from backend state; the console does not recompute scores."
        actions={<Button variant="outline" size="sm" onClick={() => void import("@/lib/query").then(({ queryClient }) => queryClient.invalidateQueries())}><RefreshCw className="h-3.5 w-3.5" /> Refresh views</Button>}
      />
      <div className="grid gap-4 sm:grid-cols-3">
        <Card><CardHeader className="pb-2"><CardDescription className="flex items-center gap-1.5"><ShieldCheck className="h-3.5 w-3.5" /> Authority</CardDescription><CardTitle className="text-sm font-medium">Backend-scored trust</CardTitle></CardHeader><CardContent><p className="text-xs leading-5 text-muted-foreground">Thresholds and weights are runtime configuration from the server.</p></CardContent></Card>
        <Card><CardHeader className="pb-2"><CardDescription className="flex items-center gap-1.5"><Fingerprint className="h-3.5 w-3.5" /> Investigation</CardDescription><CardTitle className="text-sm font-medium">Evidence-linked activity</CardTitle></CardHeader><CardContent><p className="text-xs leading-5 text-muted-foreground">Events, payouts, sequences and canaries share session scope.</p></CardContent></Card>
        <Card><CardHeader className="pb-2"><CardDescription className="flex items-center gap-1.5"><UserRound className="h-3.5 w-3.5" /> Identity</CardDescription><CardTitle className="text-sm font-medium">Provisional twins</CardTitle></CardHeader><CardContent><p className="text-xs leading-5 text-muted-foreground">Twins are marked provisional until enough samples exist.</p></CardContent></Card>
      </div>
      <Tabs value={tab} onValueChange={setTab}>
        <TabsList><TabsTrigger value="sessions">Sessions</TabsTrigger><TabsTrigger value="identities">Identities</TabsTrigger></TabsList>
        <TabsContent value="sessions"><SessionsTab /></TabsContent>
        <TabsContent value="identities"><IdentitiesTab /></TabsContent>
      </Tabs>
      <p className="text-[11px] text-muted-foreground">Signed in as {session?.label}. Tenant scope is resolved from the authenticated principal, not from a client-supplied merchant id.</p>
    </div>
  );
}
