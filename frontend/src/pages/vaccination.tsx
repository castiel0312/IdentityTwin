import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { RefreshCw, ShieldCheck, TriangleAlert, UserRound } from "lucide-react";
import { useState } from "react";
import { EmptyState } from "@/components/common/empty-state";
import { ErrorState } from "@/components/common/error-state";
import { InfoNote } from "@/components/common/info-note";
import { MetaStrip } from "@/components/common/meta-strip";
import { PageHeader } from "@/components/common/page-header";
import { ConfirmDialog } from "@/components/common/confirm-dialog";
import { Badge } from "@/components/ui/badge";
import { Button } from "@/components/ui/button";
import {
  Card,
  CardContent,
  CardDescription,
  CardHeader,
  CardTitle,
} from "@/components/ui/card";
import { Input } from "@/components/ui/input";
import { Label } from "@/components/ui/label";
import { Select, SelectContent, SelectItem, SelectTrigger, SelectValue } from "@/components/ui/select";
import { Table, TableBody, TableCell, TableHead, TableHeader, TableRow } from "@/components/ui/table";
import { Textarea } from "@/components/ui/textarea";
import { api, ApiError } from "@/lib/api";
import { useAuth } from "@/lib/auth";
import { formatDateTime, humanizeCode, titleCase } from "@/lib/format";
import { cn } from "@/lib/utils";
import type {
  VaccinationEvaluateRequest,
  VaccinationSignatureActionRequest,
  VaccinationSignatureCreateRequest,
} from "@/lib/api";

function statusVariant(status: string | null | undefined) {
  const key = (status ?? "").toUpperCase();
  if (key === "ACTIVE") return "success";
  if (key === "PROPOSED") return "warning";
    if (key === "REVOKED") return "danger";
  return "outline";
}

export function VaccinationPage() {
  const { session } = useAuth();
  const queryClient = useQueryClient();
  const isAnalyst = session?.role === "analyst" || session?.role === "admin";
  const [openAction, setOpenAction] = useState<{ kind: "approve" | "reject" | "revoke"; signatureId: string } | null>(null);
  const [selectedEvalSession, setSelectedEvalSession] = useState<string>("");

  const signatures = useQuery({
    queryKey: ["vaccination-signatures"],
    queryFn: () => api.listVaccinationSignatures(session!),
    enabled: Boolean(session),
  });
  const matches = useQuery({
    queryKey: ["vaccination-matches"],
    queryFn: () => api.listVaccinationMatches(session!),
    enabled: Boolean(session),
  });
  const availableSessions = useQuery({
    queryKey: ["vaccination-evaluate-sessions"],
    queryFn: () => api.listSessions(session!),
    enabled: Boolean(session),
  });

  const createSignature = useMutation({
    mutationFn: (body: VaccinationSignatureCreateRequest) => api.createVaccinationSignature(session!, body),
    retry: false,
    onSuccess: () => {
      void queryClient.invalidateQueries({ queryKey: ["vaccination-signatures"] });
    },
  });
  const signatureAction = useMutation({
    mutationFn: ({
      signatureId,
      body,
      kind,
    }: {
      signatureId: string;
      body: VaccinationSignatureActionRequest;
      kind: "approve" | "reject" | "revoke";
    }) => api[`${kind}VaccinationSignature`](session!, signatureId, body),
    retry: false,
    onSuccess: () => {
      setOpenAction(null);
      void queryClient.invalidateQueries({ queryKey: ["vaccination-signatures"] });
    },
  });
  const evaluate = useMutation({
    mutationFn: (body: VaccinationEvaluateRequest) => api.evaluateVaccination(session!, body),
    retry: false,
  });

  const createDisabled = createSignature.isPending;
  const actionDisabled = signatureAction.isPending;

  const items = signatures.data?.items ?? [];
  const proposed = items.filter((i) => i.status === "PROPOSED");
  const active = items.filter((i) => i.status === "ACTIVE");
  const revoked = items.filter((i) => i.status === "REVOKED");
  const matchItems = matches.data?.items ?? [];

  const handleCreate = (e: React.FormEvent) => {
    e.preventDefault();
    const form = e.currentTarget as HTMLFormElement;
    const sessionId = (form.elements.namedItem("session_id") as HTMLInputElement)?.value;
    const name = (form.elements.namedItem("name") as HTMLInputElement)?.value;
    const description = (form.elements.namedItem("description") as HTMLTextAreaElement)?.value || undefined;
    if (!sessionId || !name) return;
    void createSignature.mutate({
      session_id: sessionId,
      name,
      description,
      signature_definition: {
        pattern: {
          action_type: "payout",
          event_sequence: [
            { event_type: "payee_added", action_type: "payee.add" },
            { event_type: "payout", action_type: "payout", within_seconds: 1800 },
          ],
          requires_new_device: true,
          requires_new_payee: true,
          requires_large_payout: true,
          amount_threshold: 5000,
          within_seconds: 1800,
        },
        risk_indicators: {},
        detection_confidence: 80,
        evidence_refs: [],
        created_at: new Date().toISOString(),
      },
    });
    form.reset();
  };

  const handleEvaluate = (e: React.FormEvent) => {
    e.preventDefault();
    const form = e.currentTarget as HTMLFormElement;
    const sessionId = selectedEvalSession || (form.elements.namedItem("eval_session_id") as HTMLInputElement)?.value;
    const amount = parseFloat((form.elements.namedItem("amount") as HTMLInputElement)?.value || "0");
    const recipient = (form.elements.namedItem("recipient") as HTMLInputElement)?.value || "";
    if (!sessionId) return;
    void evaluate.mutate({
      session_id: sessionId,
      amount,
      recipient,
      action_type: "payout",
      event_type: "payout.execute",
    });
    form.reset();
  };

  return (
    <div className="space-y-5">
      <PageHeader
        eyebrow="Security Vaccination"
        title="Behavioral attack signatures"
        description={
          <>
            Signatures are extracted from confirmed attacks and require <strong>analyst approval</strong> before they are applied. Only ACTIVE signatures influence a merchant&apos;s risk evaluation through the Trust Gateway; the gateway remains the final enforcement boundary.
          </>
        }
        actions={<Button variant="outline" size="sm" onClick={() => { void signatures.refetch(); void matches.refetch(); }} disabled={signatures.isFetching || matches.isFetching}><RefreshCw className={cn("h-3.5 w-3.5", (signatures.isFetching || matches.isFetching) && "animate-spin")} /> Refresh</Button>}
      />

      <InfoNote title="How vaccination works">
        1. A merchant extracts a <strong>PROPOSED</strong> signature from a confirmed attack session. 2. An analyst approves it, moving it to <strong>ACTIVE</strong>. 3. Active signatures are compared against live sessions; a match adds an explainable risk signal but never executes or authorizes a payout. Signatures are tenant-scoped: a merchant manages only the signatures it sourced.
      </InfoNote>

      <MetaStrip
        items={[
          { label: "Proposed (pending approval)", value: String(proposed.length), hint: "Awaiting analyst decision" },
          { label: "Active (enforced)", value: String(active.length), hint: "Applied to session evaluation" },
          { label: "Revoked", value: String(revoked.length), hint: "No longer matches" },
          { label: "Matches recorded", value: String(matchItems.length), hint: "Cross-merchant detections" },
        ]}
      />

      {/* Signature management */}
      <Card>
        <CardHeader>
          <CardTitle className="flex items-center gap-2"><UserRound className="h-4 w-4 text-primary" /> Signatures in tenant scope</CardTitle>
          <CardDescription>Signatures sourced by this merchant. Lifecycle: PROPOSED → ACTIVE → REVOKED.</CardDescription>
        </CardHeader>
        <CardContent className="space-y-4">
          {signatures.isError ? <div className="p-4"><ErrorState error={signatures.error} onRetry={() => void signatures.refetch()} /></div> : signatures.isLoading ? <div className="h-40 animate-pulse rounded-lg bg-muted" /> : items.length === 0 ? (
            <EmptyState icon={UserRound} title="No vaccination signatures" description="Extract a signature from a confirmed attack session to begin." />
          ) : (
            <>
              <div className="grid gap-3 md:grid-cols-2">
                {items.map((signature) => (
                  <Card key={signature.signature_id} className="border border-border p-3">
                    <CardContent className="space-y-3">
                      <div className="flex items-center justify-between gap-2">
                        <div>
                          <p className="text-sm font-semibold">{signature.name}</p>
                          <p className="text-[10px] text-muted-foreground">{humanizeCode(signature.signature_id)}</p>
                        </div>
                        <Badge variant={statusVariant(signature.status)} className="font-mono text-[10px]">{titleCase(signature.status)}</Badge>
                      </div>
                      {signature.description && <p className="text-[11px] leading-4 text-muted-foreground">{signature.description}</p>}
                      <dl className="grid gap-2 text-[10px] sm:grid-cols-4">
                        <div><dt className="text-muted-foreground">Confidence</dt><dd className="font-mono">{signature.detection_confidence.toFixed(0)}%</dd></div>
                        <div><dt className="text-muted-foreground">Version</dt><dd className="font-mono">{signature.version}</dd></div>
                        <div><dt className="text-muted-foreground">Created</dt><dd className="font-mono">{formatDateTime(signature.created_at)}</dd></div>
                        <div><dt className="text-muted-foreground">Matches</dt><dd className="font-mono">{signature.match_count}</dd></div>
                      </dl>
                      <div className="flex flex-wrap gap-2">
                        {signature.status === "PROPOSED" && isAnalyst && (
                          <>
                            <Button size="sm" onClick={() => setOpenAction({ kind: "approve", signatureId: signature.signature_id })}>Approve</Button>
                            <Button size="sm" variant="outline" onClick={() => setOpenAction({ kind: "reject", signatureId: signature.signature_id })}>Reject</Button>
                          </>
                        )}
                        {signature.status === "ACTIVE" && isAnalyst && (
                          <Button size="sm" variant="destructive" onClick={() => setOpenAction({ kind: "revoke", signatureId: signature.signature_id })}>Revoke</Button>
                        )}
                        {!isAnalyst && signature.status === "PROPOSED" && (
                          <Button size="sm" variant="ghost" disabled>Awaiting analyst approval</Button>
                        )}
                      </div>
                    </CardContent>
                  </Card>
                ))}
              </div>
              {isAnalyst && proposed.length > 0 && (
                <div className="pt-2 text-[11px] text-muted-foreground">PROPOSED signatures require analyst approval before they are applied to any merchant evaluation.</div>
              )}
            </>
          )}
        </CardContent>
      </Card>

      {/* Extract signature form */}
      {signatures.data !== undefined && !signatures.isLoading && !createDisabled && (
        <Card>
          <CardHeader><CardTitle>Extract a signature from a confirmed attack</CardTitle><CardDescription>Enter the session that experienced the confirmed attack. The pattern is derived from that session&rsquo;s persisted events.</CardDescription></CardHeader>
          <CardContent className="space-y-4">
            <form onSubmit={handleCreate} className="grid gap-3 md:grid-cols-4 items-end">
              <div className="flex flex-col gap-1"><Label htmlFor="session_id">Attack session ID</Label><Input id="session_id" name="session_id" placeholder="Session UUID" required /></div>
              <div className="flex flex-col gap-1"><Label htmlFor="name">Signature name</Label><Input id="name" name="name" placeholder="e.g. Payee-add then large payout" required /></div>
              <div className="flex flex-col gap-1"><Label htmlFor="description">Description</Label><Textarea id="description" name="description" rows={2} placeholder="What the attack looked like" /></div>
              <Button type="submit" disabled={createDisabled}>Extract signature</Button>
            </form>
            <p className="text-[11px] text-muted-foreground">The stored definition is sanitized: it contains behavioral patterns only&mdash;no passwords, tokens, PayPal credentials or customer PII.</p>
          </CardContent>
        </Card>
      )}

      {/* Match history */}
      <Card>
        <CardHeader>
          <CardTitle className="flex items-center gap-2"><ShieldCheck className="h-4 w-4 text-primary" /> Match history</CardTitle>
          <CardDescription>Sessions whose behavior matched an active vaccination signature.</CardDescription>
        </CardHeader>
        <CardContent className="space-y-4">
          {matches.isError ? <div className="p-4"><ErrorState error={matches.error} onRetry={() => void matches.refetch()} /></div> : matches.isLoading ? <div className="h-40 animate-pulse rounded-lg bg-muted" /> : matchItems.length === 0 ? (
            <EmptyState icon={ShieldCheck} title="No vaccination matches" description="No session has matched an active signature in this tenant." />
          ) : (
            <Table>
              <TableHeader>
                <TableRow>
                  <TableHead>Signature</TableHead><TableHead>Target session</TableHead><TableHead>Match score</TableHead><TableHead>Risk points</TableHead><TableHead className="text-right">Matched at</TableHead>
                </TableRow>
              </TableHeader>
              <TableBody>
                {matchItems.map((match) => (
                  <TableRow key={match.match_id}>
                    <TableCell><span className="font-mono text-[10px]">{humanizeCode(match.signature_id)}</span><p className="mt-0.5 text-[10px] text-muted-foreground">{match.signature_name}</p></TableCell>
                    <TableCell><span className="font-mono text-[10px]">{match.session_id ? humanizeCode(match.session_id) : "—"}</span></TableCell>
                    <TableCell><span className="font-mono text-[11px]">{match.match_score.toFixed(1)}</span></TableCell>
                    <TableCell><span className="font-mono text-[11px]">{match.risk_points.toFixed(1)}</span></TableCell>
                    <TableCell className="whitespace-nowrap text-right text-[11px] text-muted-foreground">{formatDateTime(match.matched_at)}</TableCell>
                  </TableRow>
                ))}
              </TableBody>
            </Table>
          )}
        </CardContent>
      </Card>

      {/* Evaluate */}
      <Card>
        <CardHeader>
          <CardTitle className="flex items-center gap-2"><TriangleAlert className="h-4 w-4 text-primary" /> Evaluate a session against active signatures</CardTitle>
          <CardDescription>Runs the session&rsquo;s observed behavior against active vaccination signatures. A match adds a risk signal; it never bypasses the Trust Gateway.</CardDescription>
        </CardHeader>
        <CardContent className="space-y-4">
          <form onSubmit={handleEvaluate} className="grid gap-3 md:grid-cols-5 items-end">
            <div className="flex flex-col gap-1"><Label htmlFor="eval_session_id">Session ID</Label><Select name="eval_session_id" defaultValue="" onValueChange={(value) => setSelectedEvalSession(value ?? "")}><SelectTrigger><SelectValue placeholder="Choose a session" /></SelectTrigger><SelectContent>{availableSessions.data?.items.map((s) => (
                      <SelectItem key={s.session_id} value={s.session_id}>{`${humanizeCode(s.session_id)} · ${s.trust_level} · risk ${s.risk_score.toFixed(1)}`}</SelectItem>
                    )) ?? <SelectItem value="" disabled>Loading sessions…</SelectItem>}</SelectContent></Select></div>
            <div className="flex flex-col gap-1"><Label htmlFor="amount">Amount</Label><Input id="amount" name="amount" type="number" step="0.01" defaultValue="0" /></div>
            <div className="flex flex-col gap-1"><Label htmlFor="recipient">Recipient</Label><Input id="recipient" name="recipient" defaultValue="" /></div>
            <div className="flex flex-col gap-1"><Label htmlFor="action_type">Action type</Label><Select defaultValue="payout" name="action_type"><SelectTrigger><SelectValue /></SelectTrigger><SelectContent><SelectItem value="payout">Payout</SelectItem><SelectItem value="transfer">Transfer</SelectItem><SelectItem value="withdrawal">Withdrawal</SelectItem></SelectContent></Select></div>
            <Button type="submit" disabled={evaluate.isPending}>Evaluate</Button>
          </form>
          {evaluate.isError && <div className="p-3 rounded-lg border border-signal-isolated/30 bg-signal-isolated/[0.05]"><p className="text-xs text-signal-restricted">{evaluate.error instanceof ApiError ? evaluate.error.message : String(evaluate.error)}</p></div>}
          {evaluate.data?.match.matched && evaluate.data.match.signature_id && (
            <div className="rounded-lg border border-signal-restricted/30 bg-signal-restricted/[0.05] p-3">
              <p className="text-sm font-semibold flex items-center gap-2"><TriangleAlert className="h-4 w-4 shrink-0 text-signal-restricted" /> Signature matched</p>
              <dl className="mt-2 grid gap-2 text-[11px] sm:grid-cols-3">
                <div><dt className="text-muted-foreground">Signature</dt><dd className="font-mono">{evaluate.data.match.signature_name}</dd></div>
                <div><dt className="text-muted-foreground">Match score</dt><dd className="font-mono">{evaluate.data.match.match_score.toFixed(1)}</dd></div>
                <div><dt className="text-muted-foreground">Risk points added</dt><dd className="font-mono">{evaluate.data.match.risk_points.toFixed(1)}</dd></div>
              </dl>
              <p className="mt-2 text-xs text-muted-foreground">{evaluate.data.match.match_reason}</p>
            </div>
          )}
        </CardContent>
      </Card>

      <ConfirmDialog
        open={Boolean(openAction)}
        onOpenChange={(next) => { if (!next) setOpenAction(null); }}
        title={openAction?.kind === "revoke" ? "Revoke vaccination signature?" : `${titleCase(openAction?.kind)} vaccination signature?`}
        description={
          openAction?.kind === "revoke"
            ? "Revoking makes this signature inactive. It will no longer match merchant sessions. Already-recorded matches remain in the audit history."
            : `Moving a signature to ${titleCase(openAction?.kind ?? "")} changes whether it is applied during session evaluation. This action is recorded in the evidence chain.`
        }
        confirmLabel={signatureAction.isPending ? "Processing…" : openAction?.kind === "revoke" ? "Revoke" : titleCase(openAction?.kind ?? "")}
        pending={actionDisabled}
        onConfirm={() => {
          if (!openAction) return;
          const body: VaccinationSignatureActionRequest = { notes: "" };
          void signatureAction.mutate({
            signatureId: openAction.signatureId,
            body,
            kind: openAction.kind,
          });
        }}
      >
        <div className="space-y-2 text-sm">
          <p className="font-medium">{openAction?.signatureId ? humanizeCode(openAction.signatureId) : ""}</p>
          {openAction?.kind === "approve" && (
            <p className="text-xs leading-5 text-muted-foreground">Only an ACTIVE signature is applied to merchant evaluations. Proposed signatures never match.</p>
          )}
          {openAction?.kind === "reject" && (
            <p className="text-xs leading-5 text-muted-foreground">A rejected signature moves to REVOKED and will never be applied.</p>
          )}
          {signatureAction.isPending && <p className="text-xs text-muted-foreground">Waiting for the authoritative result…</p>}
        </div>
      </ConfirmDialog>
    </div>
  );
}
