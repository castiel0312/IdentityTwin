import { useQuery } from "@tanstack/react-query";
import { ArrowLeft, FileLock2, RefreshCw, ShieldCheck, ShieldQuestion } from "lucide-react";
import { Link, useParams } from "react-router-dom";
import { StatusBadge } from "@/components/common/badges";
import { DataField } from "@/components/common/data-field";
import { ErrorState } from "@/components/common/error-state";
import { InfoNote } from "@/components/common/info-note";
import { Limitations } from "@/components/common/limitations";
import { DetailLoading } from "@/components/common/loading-state";
import { PageHeader } from "@/components/common/page-header";
import { Badge } from "@/components/ui/badge";
import { Button } from "@/components/ui/button";
import { Card, CardContent, CardDescription, CardHeader, CardTitle } from "@/components/ui/card";
import { api } from "@/lib/api";
import { useAuth } from "@/lib/auth";
import { formatDateTime } from "@/lib/format";
import { cn } from "@/lib/utils";

export function EvidenceDetailPage() {
  const { sealId = "" } = useParams();
  const { session } = useAuth();
  const query = useQuery({ queryKey: ["evidence-seal", sealId], queryFn: () => api.evidenceSeal(session!, sealId), enabled: Boolean(session && sealId) });

  if (query.isLoading) return <DetailLoading />;
  if (query.isError) return <div className="space-y-4"><Button asChild variant="ghost" size="sm" className="-ml-2"><Link to="/evidence"><ArrowLeft className="h-4 w-4" /> Back to evidence</Link></Button><ErrorState error={query.error} onRetry={() => void query.refetch()} /></div>;
  if (!query.data) return null;
  const { seal, entries = [], seal_verification: verification, limitations = [] } = query.data;
  const isConsistent = verification.valid;

  return (
    <div className="space-y-6">
      <div>
        <Button asChild variant="ghost" size="sm" className="-ml-2 mb-2"><Link to="/evidence"><ArrowLeft className="h-4 w-4" /> Back to evidence</Link></Button>
        <PageHeader
          eyebrow="Evidence seal"
          title={`Sealed range ${seal.start_seq}–${seal.end_seq}`}
          description={<span className="flex flex-wrap items-center gap-2"><Badge variant={isConsistent ? "success" : "danger"}>{isConsistent ? "Range consistent" : "Range inconsistent"}</Badge><StatusBadge status={seal.incident_status} /><span className="font-mono text-[11px] text-muted-foreground">{seal.seal_id}</span></span>}
          actions={<Button variant="outline" size="sm" onClick={() => void query.refetch()} disabled={query.isFetching}><RefreshCw className={cn("h-3.5 w-3.5", query.isFetching && "animate-spin")} /> Re-verify</Button>}
        />
      </div>

      <div className={cn("rounded-xl border p-4", isConsistent ? "border-signal-normal/30 bg-signal-normal/[0.05]" : "border-signal-isolated/30 bg-signal-isolated/[0.05]")} data-testid="seal-verification">
        <div className="flex items-start gap-3">
          {isConsistent ? <ShieldCheck className="mt-0.5 h-5 w-5 shrink-0 text-signal-normal" /> : <ShieldQuestion className="mt-0.5 h-5 w-5 shrink-0 text-signal-isolated" />}
          <div className="min-w-0">
            <p className="text-sm font-semibold">{isConsistent ? "Seal range is internally consistent" : "Seal range verification failed"}</p>
            <p className="mt-1 text-xs leading-5 text-muted-foreground">
              {isConsistent
                ? "Sequence continuity, chain links, payload hashes and the sealed head matched the available chain. This is consistency evidence, not proof of immutability or independent custody."
                : "The backend reports an inconsistency in this range. Preserve the current state, escalate for investigation, and do not represent this seal as intact."}
            </p>
            <dl className="mt-3 grid gap-2 text-[11px] sm:grid-cols-2 xl:grid-cols-4">
              <div><dt className="text-muted-foreground">Scope</dt><dd className="font-mono">{verification.scope}</dd></div>
              <div><dt className="text-muted-foreground">Entries checked</dt><dd className="font-mono">{verification.checked}</dd></div>
              <div><dt className="text-muted-foreground">Sealed head matches</dt><dd className={verification.head_matches ? "font-mono text-signal-normal" : "font-mono text-signal-isolated"}>{verification.head_matches ? "Yes" : "No"}</dd></div>
              <div><dt className="text-muted-foreground">Server reason</dt><dd className={cn("font-mono", !isConsistent && "text-signal-isolated")}>{verification.reason ?? "None"}</dd></div>
              {typeof verification.first_broken_seq === "number" ? <div><dt className="text-muted-foreground">First broken seq</dt><dd className="font-mono text-signal-isolated">{verification.first_broken_seq}</dd></div> : null}
            </dl>
          </div>
        </div>
      </div>

      <div className="grid gap-4 xl:grid-cols-3">
        <div className="space-y-4 xl:col-span-2">
          <Card>
            <CardHeader><CardTitle className="flex items-center gap-2"><FileLock2 className="h-4 w-4 text-primary" /> Sealed entries</CardTitle><CardDescription>Payloads are server-redacted. Every field shown comes from the seal response.</CardDescription></CardHeader>
            <CardContent>
              {entries.length === 0 ? <p className="py-8 text-center text-sm text-muted-foreground">The sealed range contains no readable entries. The backend reports this as <span className="font-mono">{verification.reason ?? "empty"}</span>.</p> : (
                <ol className="space-y-3">
                  {entries.map((entry) => (
                    <li key={entry.seq} className="rounded-lg border border-border">
                      <div className="flex flex-wrap items-center justify-between gap-2 border-b border-border bg-muted/20 px-3 py-2">
                        <div className="flex items-center gap-2"><Badge variant="outline" className="font-mono">seq {entry.seq}</Badge><span className="font-mono text-[11px]">{entry.event_ref}</span></div>
                        <span className="text-[10px] text-muted-foreground">{formatDateTime(entry.created_at)}</span>
                      </div>
                      <div className="grid gap-3 p-3 sm:grid-cols-2">
                        <DataField label="Payload hash" mono>{entry.payload_hash}</DataField>
                        <DataField label="Chain hash" mono>{entry.hash}</DataField>
                        <DataField label="Previous hash" mono>{entry.prev_hash}</DataField>
                        <DataField label="Event reference" mono>{entry.event_ref}</DataField>
                      </div>
                      {Object.keys(entry.payload ?? {}).length ? (
                        <details className="border-t border-border"><summary className="cursor-pointer px-3 py-2 text-[11px] font-medium">Redacted payload</summary><pre className="max-h-64 overflow-auto border-t border-border p-3 font-mono text-[10px] leading-5">{JSON.stringify(entry.payload, null, 2)}</pre></details>
                      ) : <p className="border-t border-border px-3 py-2 text-[11px] text-muted-foreground">No payload fields were returned.</p>}
                    </li>
                  ))}
                </ol>
              )}
            </CardContent>
          </Card>
          <Limitations notes={limitations} />
        </div>

        <div className="space-y-4">
          <Card>
            <CardHeader><CardTitle>Seal facts</CardTitle></CardHeader>
            <CardContent className="space-y-3">
              <DataField label="Seal id" mono>{seal.seal_id}</DataField>
              <DataField label="Incident"><Link to={`/incidents/${seal.incident_id}`} className="text-sm text-primary hover:underline">{seal.incident_title}</Link><div className="mt-1"><StatusBadge status={seal.incident_status} /></div></DataField>
              <DataField label="Session"><Link to={`/sessions/${seal.session_id}`} className="font-mono text-xs text-primary hover:underline">{seal.session_id}</Link></DataField>
              <DataField label="Merchant" mono>{seal.merchant_id}</DataField>
              <DataField label="Sealed at">{formatDateTime(seal.sealed_at)}</DataField>
              <DataField label="Head hash" mono>{seal.head_hash}</DataField>
            </CardContent>
          </Card>
          <InfoNote tone="warning" title="Do not overstate verification">
            A passing check proves only that the available chain and checkpoint are internally consistent. It does not prove that the underlying database is immutable or that custody was independent. A failed request is a request failure; it is not itself proof of tampering.
          </InfoNote>
          <Card>
            <CardHeader><CardTitle>Incident context</CardTitle></CardHeader>
            <CardContent className="space-y-2">
              <Button asChild variant="outline" size="sm" className="w-full"><Link to={`/incidents/${seal.incident_id}`}>Open incident</Link></Button>
              <Button asChild variant="outline" size="sm" className="w-full"><Link to={`/sessions/${seal.session_id}`}>Open session investigation</Link></Button>
            </CardContent>
          </Card>
        </div>
      </div>
    </div>
  );
}
