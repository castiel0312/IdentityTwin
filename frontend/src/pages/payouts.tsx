import { useQuery } from "@tanstack/react-query";
import { ArrowLeftRight, Filter, Plus, RefreshCw, Search, X } from "lucide-react";
import { useDeferredValue, useState } from "react";
import { Link } from "react-router-dom";
import { RiskMeter } from "@/components/common/risk-meter";
import { EmptyState } from "@/components/common/empty-state";
import { ErrorState } from "@/components/common/error-state";
import { TableLoading } from "@/components/common/loading-state";
import { MetaStrip } from "@/components/common/meta-strip";
import { PageHeader } from "@/components/common/page-header";
import { Pagination } from "@/components/common/pagination";
import { StatusBadge, TrustBadge } from "@/components/common/badges";
import { Badge } from "@/components/ui/badge";
import { Button } from "@/components/ui/button";
import { Card, CardContent } from "@/components/ui/card";
import { Input } from "@/components/ui/input";
import { Select, SelectContent, SelectItem, SelectTrigger, SelectValue } from "@/components/ui/select";
import { Table, TableBody, TableCell, TableHead, TableHeader, TableRow } from "@/components/ui/table";
import { PayoutDialog } from "@/features/payouts/payout-dialog";
import { api } from "@/lib/api";
import { useAuth } from "@/lib/auth";
import { formatDateTime, formatMoney, titleCase } from "@/lib/format";
import { cn } from "@/lib/utils";

const PAGE_SIZE = 25;

export function PayoutsPage() {
  const { session } = useAuth();
  const [dialogOpen, setDialogOpen] = useState(false);
  const [page, setPage] = useState(1);
  const [search, setSearch] = useState("");
  const [status, setStatus] = useState("all");
  const [trust, setTrust] = useState("all");
  const [provider, setProvider] = useState("all");
  const [initiator, setInitiator] = useState("all");
  const [sort, setSort] = useState("-created_at");
  const deferredSearch = useDeferredValue(search);

  const hasFilters = Boolean(search || status !== "all" || trust !== "all" || provider !== "all" || initiator !== "all");

  const query = useQuery({
    queryKey: ["payouts", { deferredSearch, status, trust, provider, initiator, sort, page }],
    queryFn: () =>
      api.listPayouts(session!, {
        q: deferredSearch || undefined,
        status: status === "all" ? undefined : status,
        trust_level: trust === "all" ? undefined : trust,
        provider: provider === "all" ? undefined : provider,
        initiator: initiator === "all" ? undefined : initiator,
        sort,
        page,
        page_size: PAGE_SIZE,
      }),
    enabled: Boolean(session),
  });

  const resetFilters = () => {
    setSearch("");
    setStatus("all");
    setTrust("all");
    setProvider("all");
    setInitiator("all");
    setSort("-created_at");
    setPage(1);
  };

  const totalPages = query.data ? Math.max(1, Math.ceil(query.data.total / query.data.page_size)) : null;
  const pageItems = query.data?.items ?? [];
  const trustCounts = pageItems.reduce<Record<string, number>>((acc, payout) => {
    const level = (payout.trust_level ?? "UNKNOWN").toUpperCase();
    acc[level] = (acc[level] ?? 0) + 1;
    return acc;
  }, {});
  const trustTones: Record<string, string> = {
    NORMAL: "bg-signal-normal",
    RESTRICTED: "bg-signal-restricted",
    DECOY: "bg-signal-decoy",
    ISOLATED: "bg-signal-isolated",
  };

  return (
    <div className="space-y-5">
      <PageHeader
        eyebrow="Gateway ledger"
        title="Payout operations"
        description="Every row is a payout persisted by the Trust Gateway, projected with its authoritative decision and execution status. Listing and inspection never execute or retry a payout."
        actions={
          <>
            <Button variant="outline" size="sm" onClick={() => void query.refetch()} disabled={query.isFetching}>
              <RefreshCw className={cn("h-3.5 w-3.5", query.isFetching && "animate-spin")} aria-hidden="true" />
              Refresh
            </Button>
            <Button size="sm" onClick={() => setDialogOpen(true)}>
              <Plus className="h-3.5 w-3.5" aria-hidden="true" />
              New payout
            </Button>
          </>
        }
      />

      <MetaStrip
        items={[
          {
            label: "Ledger rows",
            value: query.data ? query.data.total.toLocaleString() : "—",
            hint: "Matching the active filter set",
          },
          {
            label: "Page",
            value: query.data ? `${query.data.page} / ${totalPages}` : "—",
            hint: `${PAGE_SIZE} rows per page`,
          },
          {
            label: "Filter state",
            value: (
              <Badge variant={hasFilters ? "warning" : "muted"}>{hasFilters ? "Filtered" : "Unfiltered"}</Badge>
            ),
            hint: "Search + five server-side filters",
          },
          {
            label: "Trust mix · this page",
            value: pageItems.length ? (
              <div className="w-full space-y-2">
                <div
                  className="flex h-1.5 w-full overflow-hidden rounded-full bg-white/[0.06]"
                  role="img"
                  aria-label={Object.entries(trustCounts)
                    .map(([level, count]) => `${level}: ${count}`)
                    .join(", ")}
                >
                  {Object.entries(trustCounts).map(([level, count]) => (
                    <span
                      key={level}
                      className={cn("h-full", trustTones[level] ?? "bg-muted-foreground")}
                      style={{ width: `${(count / pageItems.length) * 100}%` }}
                    />
                  ))}
                </div>
                <div className="flex flex-wrap gap-x-3 gap-y-1 font-mono text-2xs text-muted-foreground">
                  {Object.entries(trustCounts).map(([level, count]) => (
                    <span key={level} className="inline-flex items-center gap-1">
                      <span className={cn("h-1 w-1 rounded-full", trustTones[level] ?? "bg-muted-foreground")} aria-hidden="true" />
                      {level.toLowerCase()} {count}
                    </span>
                  ))}
                </div>
              </div>
            ) : (
              "No rows"
            ),
            hint: "Composition of the loaded page only",
          },
        ]}
      />

      <Card>
        <CardContent className="p-4">
          <div className="grid gap-3 lg:grid-cols-[minmax(0,1.5fr)_repeat(4,minmax(0,1fr))_auto]">
            <div className="relative">
              <Search className="pointer-events-none absolute left-2.5 top-1/2 h-3.5 w-3.5 -translate-y-1/2 text-muted-foreground" aria-hidden="true" />
              <Input
                value={search}
                onChange={(event) => {
                  setSearch(event.target.value);
                  setPage(1);
                }}
                placeholder="Search id, recipient, reference…"
                className="pl-8"
                aria-label="Search payouts"
              />
            </div>
            <Select value={status} onValueChange={(value) => { setStatus(value); setPage(1); }}>
              <SelectTrigger aria-label="Filter by status"><SelectValue placeholder="Status" /></SelectTrigger>
              <SelectContent>
                <SelectItem value="all">All statuses</SelectItem>
                <SelectItem value="completed">Completed</SelectItem>
                <SelectItem value="reconciled_completed">Reconciled completed</SelectItem>
                <SelectItem value="rejected">Rejected</SelectItem>
                <SelectItem value="decoy_completed">Decoy completed</SelectItem>
                <SelectItem value="blocked">Blocked</SelectItem>
                <SelectItem value="provider_denied">Provider denied</SelectItem>
              </SelectContent>
            </Select>
            <Select value={trust} onValueChange={(value) => { setTrust(value); setPage(1); }}>
              <SelectTrigger aria-label="Filter by trust level"><SelectValue placeholder="Trust" /></SelectTrigger>
              <SelectContent>
                <SelectItem value="all">All trust levels</SelectItem>
                <SelectItem value="NORMAL">Normal</SelectItem>
                <SelectItem value="RESTRICTED">Restricted</SelectItem>
                <SelectItem value="DECOY">Decoy</SelectItem>
                <SelectItem value="ISOLATED">Isolated</SelectItem>
              </SelectContent>
            </Select>
            <Select value={provider} onValueChange={(value) => { setProvider(value); setPage(1); }}>
              <SelectTrigger aria-label="Filter by provider"><SelectValue placeholder="Provider" /></SelectTrigger>
              <SelectContent>
                <SelectItem value="all">All providers</SelectItem>
                <SelectItem value="mock_sandbox">Mock sandbox</SelectItem>
                <SelectItem value="honey_synthetic_decoy">Honey decoy</SelectItem>
                <SelectItem value="paypal_sandbox">PayPal sandbox</SelectItem>
              </SelectContent>
            </Select>
            <Select value={initiator} onValueChange={(value) => { setInitiator(value); setPage(1); }}>
              <SelectTrigger aria-label="Filter by initiator"><SelectValue placeholder="Initiator" /></SelectTrigger>
              <SelectContent>
                <SelectItem value="all">All initiators</SelectItem>
                <SelectItem value="human">Human</SelectItem>
                <SelectItem value="agent">AI agent</SelectItem>
              </SelectContent>
            </Select>
            <Button variant="ghost" size="sm" onClick={resetFilters} disabled={!hasFilters} className="justify-start lg:justify-center">
              <X className="h-3.5 w-3.5" aria-hidden="true" />
              Clear
            </Button>
          </div>
          <div className="mt-3 flex flex-wrap items-center justify-between gap-2">
            <p className="flex items-center gap-1.5 text-xs text-muted-foreground">
              <Filter className="h-3.5 w-3.5" aria-hidden="true" />
              {query.data ? `${query.data.total} matching payout${query.data.total === 1 ? "" : "s"}` : "Loading ledger"}
            </p>
            <Select value={sort} onValueChange={(value) => { setSort(value); setPage(1); }}>
              <SelectTrigger className="h-8 w-48" aria-label="Sort payouts"><SelectValue /></SelectTrigger>
              <SelectContent>
                <SelectItem value="-created_at">Newest first</SelectItem>
                <SelectItem value="created_at">Oldest first</SelectItem>
                <SelectItem value="-amount">Highest amount</SelectItem>
                <SelectItem value="amount">Lowest amount</SelectItem>
                <SelectItem value="-risk_score">Highest risk</SelectItem>
                <SelectItem value="risk_score">Lowest risk</SelectItem>
                <SelectItem value="status">Status A–Z</SelectItem>
              </SelectContent>
            </Select>
          </div>
        </CardContent>
        {query.isError ? <div className="p-4"><ErrorState error={query.error} onRetry={() => void query.refetch()} /></div> : null}
        {query.isLoading ? (
          <TableLoading rows={8} columns={7} />
        ) : query.data?.items.length === 0 ? (
          <EmptyState
            icon={ArrowLeftRight}
            title={hasFilters ? "No payouts match these filters" : "No payouts recorded yet"}
            description={
              hasFilters
                ? "Adjust the filters or clear them to inspect the full merchant ledger."
                : "Use New payout to submit one protected request through the gateway. The payout will appear here with its authoritative outcome."
            }
            action={hasFilters ? <Button variant="outline" onClick={resetFilters}>Clear filters</Button> : <Button onClick={() => setDialogOpen(true)}>New payout</Button>}
          />
        ) : (
          <>
            <div className="overflow-x-auto">
            <Table>
              <TableHeader>
                <TableRow>
                  <TableHead className="min-w-[140px]">Payout</TableHead>
                  <TableHead className="min-w-[200px]">Recipient</TableHead>
                  <TableHead className="min-w-[120px]">Amount</TableHead>
                  <TableHead className="min-w-[150px]">Decision</TableHead>
                  <TableHead className="min-w-[150px]">Status</TableHead>
                  <TableHead className="min-w-[140px]">Initiator</TableHead>
                  <TableHead className="min-w-[150px] text-right">Created</TableHead>
                </TableRow>
              </TableHeader>
              <TableBody>
                {query.data?.items.map((payout) => (
                  <TableRow key={payout.payout_id}>
                    <TableCell>
                      <Link to={`/payouts/${payout.payout_id}`} className="font-mono text-xs text-primary hover:underline">
                        {payout.payout_id.slice(0, 8)}…
                      </Link>
                      <p className="mt-0.5 truncate text-[11px] text-muted-foreground">{payout.provider_name}</p>
                    </TableCell>
                    <TableCell>
                      <p className="max-w-[260px] break-words text-sm">{payout.recipient_email}</p>
                      <p className="max-w-[260px] break-words text-[11px] text-muted-foreground">{payout.reference_note ?? "No reference"}</p>
                    </TableCell>
                    <TableCell className="whitespace-nowrap font-mono text-xs tabular-nums">{formatMoney(payout.amount, payout.currency)}</TableCell>
                    <TableCell>
                      <div className="space-y-1">
                        <TrustBadge level={payout.trust_level} />
                        <RiskMeter score={payout.risk_score} />
                      </div>
                    </TableCell>
                    <TableCell>
                      <div className="flex flex-wrap items-center gap-1">
                        <StatusBadge status={payout.status} />
                        {payout.reconciliation_required ? <Badge variant="warning">Reconcile</Badge> : null}
                      </div>
                    </TableCell>
                    <TableCell>
                      {payout.agent_display_name ? (
                        <div>
                          <p className="max-w-[160px] truncate text-xs font-medium">{payout.agent_display_name}</p>
                          <p className="text-[10px] uppercase tracking-wider text-muted-foreground">AI agent</p>
                        </div>
                      ) : (
                        <span className="text-xs text-muted-foreground">Human · {titleCase(payout.action)}</span>
                      )}
                    </TableCell>
                    <TableCell className="whitespace-nowrap text-right text-[11px] text-muted-foreground">{formatDateTime(payout.created_at)}</TableCell>
                  </TableRow>
                ))}
              </TableBody>
            </Table>
            </div>
            <Pagination page={query.data!.page} pageSize={query.data!.page_size} total={query.data!.total} onPageChange={setPage} label="payouts" />
          </>
        )}
      </Card>

      <PayoutDialog open={dialogOpen} onOpenChange={setDialogOpen} />
    </div>
  );
}
