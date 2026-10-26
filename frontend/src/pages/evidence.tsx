import { useQuery } from "@tanstack/react-query";
import { FileCheck2, FileLock2, RefreshCw, ShieldCheck, ShieldQuestion } from "lucide-react";
import { useState } from "react";
import { Link } from "react-router-dom";
import { StatusBadge } from "@/components/common/badges";
import { EmptyState } from "@/components/common/empty-state";
import { ErrorState } from "@/components/common/error-state";
import { InfoNote } from "@/components/common/info-note";
import { TableLoading } from "@/components/common/loading-state";
import { PageHeader } from "@/components/common/page-header";
import { Pagination } from "@/components/common/pagination";
import { Badge } from "@/components/ui/badge";
import { Button } from "@/components/ui/button";
import { Card, CardContent, CardDescription, CardHeader, CardTitle } from "@/components/ui/card";
import { Table, TableBody, TableCell, TableHead, TableHeader, TableRow } from "@/components/ui/table";
import { api } from "@/lib/api";
import { useAuth } from "@/lib/auth";
import { formatDateTime } from "@/lib/format";
import { cn } from "@/lib/utils";

const PAGE_SIZE = 25;

export function EvidencePage() {
  const { session } = useAuth();
  const [page, setPage] = useState(1);
  const seals = useQuery({ queryKey: ["evidence-seals", page], queryFn: () => api.listEvidenceSeals(session!, { page, page_size: PAGE_SIZE }), enabled: Boolean(session) });
  const verification = useQuery({ queryKey: ["evidence-verify"], queryFn: () => api.verifyEvidence(session!), enabled: false });
  const result = verification.data;

  return (
    <div className="space-y-5">
      <PageHeader
        eyebrow="Evidence vault"
        title="Tamper-evident evidence"
        description="Inspect sealed evidence ranges and check consistency against the stored hash chain. The console is deliberately precise about what verification proves."
        actions={<Button variant="outline" size="sm" onClick={() => void seals.refetch()} disabled={seals.isFetching}><RefreshCw className={cn("h-3.5 w-3.5", seals.isFetching && "animate-spin")} /> Refresh seals</Button>}
      />

      <div className="grid gap-4 xl:grid-cols-3">
        <Card className="xl:col-span-2">
          <CardHeader>
            <CardTitle className="flex items-center gap-2"><ShieldCheck className="h-4 w-4 text-primary" /> Chain consistency check</CardTitle>
            <CardDescription>Runs the server-side verification against the current chain and persisted checkpoint.</CardDescription>
          </CardHeader>
          <CardContent className="space-y-4">
            <div className="flex flex-wrap items-center gap-3">
              <Button onClick={() => void verification.refetch()} disabled={verification.isFetching}>
                {verification.isFetching ? <RefreshCw className="h-4 w-4 animate-spin" /> : <FileCheck2 className="h-4 w-4" />}
                {verification.isFetching ? "Verifying…" : "Verify current chain"}
              </Button>
              {verification.isError ? <span className="text-xs font-medium text-signal-isolated">Verification request failed</span> : result ? <Badge variant={result.valid ? "success" : "danger"}>{result.valid ? "Consistent" : "Inconsistent"}</Badge> : <span className="text-xs text-muted-foreground">Not checked in this view</span>}
            </div>

            {verification.isError ? <ErrorState error={verification.error} onRetry={() => void verification.refetch()} /> : null}
            {verification.isFetching ? <div className="h-24 animate-pulse rounded-lg bg-muted" /> : null}
            {!verification.isFetching && result ? (
              <div data-testid="chain-verification-result" className={cn("rounded-lg border p-4", result.valid ? "border-signal-normal/30 bg-signal-normal/[0.05]" : "border-signal-isolated/30 bg-signal-isolated/[0.05]")}>
                <div className="flex items-start gap-3">
                  {result.valid ? <ShieldCheck className="mt-0.5 h-5 w-5 shrink-0 text-signal-normal" /> : <ShieldQuestion className="mt-0.5 h-5 w-5 shrink-0 text-signal-isolated" />}
                  <div className="min-w-0">
                    <p className="text-sm font-semibold">{result.valid ? `Chain is consistent across ${result.checked} entries` : "Chain consistency check failed"}</p>
                    <p className="mt-0.5 text-xs leading-5 text-muted-foreground">{result.valid ? "Every checked entry matched sequence, link, payload and hash expectations up to the persisted checkpoint." : "The verification result indicates an inconsistency. Treat evidence as potentially altered and escalate; do not claim the chain is intact."}</p>
                    <dl className="mt-3 grid gap-2 text-[11px] sm:grid-cols-2">
                      <div><dt className="text-muted-foreground">Entries checked</dt><dd className="font-mono">{result.checked}</dd></div>
                      <div><dt className="text-muted-foreground">Reported head</dt><dd className="break-all font-mono">{result.head_hash}</dd></div>
                      {result.reason ? <div><dt className="text-muted-foreground">Server reason</dt><dd className="font-mono text-signal-isolated">{result.reason}</dd></div> : null}
                      {typeof result.first_broken_seq === "number" ? <div><dt className="text-muted-foreground">First broken sequence</dt><dd className="font-mono text-signal-isolated">{result.first_broken_seq}</dd></div> : null}
                    </dl>
                  </div>
                </div>
              </div>
            ) : null}
            <InfoNote tone="info" title="What this check does and does not prove">
              It proves consistency with the available chain and checkpoint. It does <strong>not</strong> prove database immutability, independent custody or that an administrator could not rewrite or restore the database. A network or server failure is shown separately and is not evidence of tampering.
            </InfoNote>
          </CardContent>
        </Card>
        <Card>
          <CardHeader><CardTitle>Current checkpoint</CardTitle><CardDescription>Reported with the seal inventory.</CardDescription></CardHeader>
          <CardContent className="space-y-3">
            <div><p className="text-[11px] uppercase tracking-wider text-muted-foreground">Checkpoint sequence</p><p className="mt-1 font-mono text-lg">{seals.data?.chain_checkpoint_seq ?? "—"}</p></div>
            <div><p className="text-[11px] uppercase tracking-wider text-muted-foreground">Head hash</p><p className="mt-1 break-all font-mono text-[10px]">{seals.data?.chain_head_hash ?? "No checkpoint reported"}</p></div>
            <div><p className="text-[11px] uppercase tracking-wider text-muted-foreground">Sealed ranges</p><p className="mt-1 text-lg font-semibold">{seals.data?.total ?? "—"}</p></div>
            <p className="text-[11px] leading-5 text-muted-foreground">No chain head is fabricated when the backend has not recorded one.</p>
          </CardContent>
        </Card>
      </div>

      <Card>
        <CardHeader><CardTitle className="flex items-center gap-2"><FileLock2 className="h-4 w-4 text-primary" /> Evidence seals</CardTitle><CardDescription>Each seal covers a specific incident session range. Open a seal for range verification.</CardDescription></CardHeader>
        {seals.isError ? <div className="p-4"><ErrorState error={seals.error} onRetry={() => void seals.refetch()} /></div> : null}
        {seals.isLoading ? <TableLoading rows={5} columns={6} /> : seals.data?.items.length === 0 ? (
          <EmptyState icon={FileLock2} title="No evidence seals" description="Seals are created by the backend when an incident is sealed. Absence of a seal is not evidence of tampering." />
        ) : (
          <>
            <Table><TableHeader><TableRow><TableHead>Seal</TableHead><TableHead>Incident</TableHead><TableHead>Session</TableHead><TableHead>Range</TableHead><TableHead>Head hash</TableHead><TableHead className="text-right">Sealed</TableHead></TableRow></TableHeader><TableBody>
              {seals.data?.items.map((seal) => (
                <TableRow key={seal.seal_id}>
                  <TableCell><Link to={`/evidence/${seal.seal_id}`} className="font-mono text-xs text-primary hover:underline">{seal.seal_id.slice(0, 8)}…</Link></TableCell>
                  <TableCell><Link to={`/incidents/${seal.incident_id}`} className="text-xs font-medium hover:underline">{seal.incident_title}</Link><div className="mt-1"><StatusBadge status={seal.incident_status} /></div></TableCell>
                  <TableCell><Link to={`/sessions/${seal.session_id}`} className="font-mono text-[11px] text-primary hover:underline">{seal.session_id.slice(0, 8)}…</Link></TableCell>
                  <TableCell className="font-mono text-xs">{seal.start_seq}–{seal.end_seq}</TableCell>
                  <TableCell><span className="break-all font-mono text-[10px]">{seal.head_hash.slice(0, 20)}…</span></TableCell>
                  <TableCell className="whitespace-nowrap text-right text-[11px] text-muted-foreground">{formatDateTime(seal.sealed_at)}</TableCell>
                </TableRow>
              ))}
            </TableBody></Table>
            <Pagination page={seals.data!.page} pageSize={seals.data!.page_size} total={seals.data!.total} onPageChange={setPage} label="seals" />
          </>
        )}
      </Card>
    </div>
  );
}
