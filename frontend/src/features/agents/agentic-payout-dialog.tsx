import { zodResolver } from "@hookform/resolvers/zod";
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { ArrowUpRight, Bot, Loader2, LockKeyhole, ShieldCheck } from "lucide-react";
import { useState } from "react";
import { Controller, useForm, useWatch } from "react-hook-form";
import { Link } from "react-router-dom";
import { toast } from "sonner";
import { z } from "zod";
import { StatusBadge, TrustBadge } from "@/components/common/badges";
import { ConfirmDialog } from "@/components/common/confirm-dialog";
import { InfoNote } from "@/components/common/info-note";
import { Button } from "@/components/ui/button";
import { Dialog, DialogContent, DialogDescription, DialogFooter, DialogHeader, DialogTitle } from "@/components/ui/dialog";
import { Input } from "@/components/ui/input";
import { Label } from "@/components/ui/label";
import { Select, SelectContent, SelectItem, SelectTrigger, SelectValue } from "@/components/ui/select";
import { Textarea } from "@/components/ui/textarea";
import { api, ApiError, type Schema } from "@/lib/api";
import { useAuth } from "@/lib/auth";
import { formatMoney, humanizeCode, newIdempotencyKey, titleCase } from "@/lib/format";

const agentPayoutSchema = z.object({
  agent_id: z.string().min(1, "Choose an agent."),
  authorization_grant_id: z.string().min(1, "Choose an active authorization grant."),
  session_id: z.string().min(1, "Choose the session the agent acts within."),
  recipient_email: z.string().email("Enter a valid recipient email."),
  amount: z.number({ message: "Enter an amount." }).positive("Amount must be greater than zero.").max(100_000, "The gateway maximum is 100,000."),
  currency: z.string().length(3, "Use a three-letter currency code."),
  reference_note: z.string().max(255, "Keep the reference under 255 characters.").optional(),
  agent_intent: z.string().max(255, "Keep the intent under 255 characters.").optional(),
});

type FormValues = z.infer<typeof agentPayoutSchema>;
type AgenticResult = Schema<"AgenticCommerceResponse">;

export function AgenticPayoutDialog({
  open,
  onOpenChange,
  initialAgentId,
}: {
  open: boolean;
  onOpenChange: (open: boolean) => void;
  initialAgentId?: string;
}) {
  // Remount on each open so a previous review, idempotency key or step-up
  // token can never be reused for a new consequential request.
  return (
    <AgenticPayoutDialogBody
      key={open ? "open" : "closed"}
      open={open}
      onOpenChange={onOpenChange}
      initialAgentId={initialAgentId}
    />
  );
}

function AgenticPayoutDialogBody({
  open,
  onOpenChange,
  initialAgentId,
}: {
  open: boolean;
  onOpenChange: (open: boolean) => void;
  initialAgentId?: string;
}) {
  const { session } = useAuth();
  const queryClient = useQueryClient();
  const [idempotencyKey] = useState(() => newIdempotencyKey("agent"));
  const [review, setReview] = useState<FormValues | null>(null);
  const [result, setResult] = useState<AgenticResult | null>(null);
  const [stepUpChallenge, setStepUpChallenge] = useState<Schema<"StepUpChallengeCreateResponse"> | null>(null);
  const [otp, setOtp] = useState("");
  const [stepUpToken, setStepUpToken] = useState("");
  const [stepUpError, setStepUpError] = useState<string | null>(null);
  const [submitError, setSubmitError] = useState<string | null>(null);

  const form = useForm<FormValues>({
    resolver: zodResolver(agentPayoutSchema),
    defaultValues: { agent_id: initialAgentId ?? "", authorization_grant_id: "", session_id: "", recipient_email: "", amount: 0, currency: "USD", reference_note: "", agent_intent: "" },
    mode: "onBlur",
  });
  const agentId = useWatch({ control: form.control, name: "agent_id" });
  const grantId = useWatch({ control: form.control, name: "authorization_grant_id" });
  const selectedSessionId = useWatch({ control: form.control, name: "session_id" });

  const agentsQuery = useQuery({ queryKey: ["agents", "agentic-picker"], queryFn: () => api.listAgents(session!, { status: "active", page_size: 100 }), enabled: open && Boolean(session) });
  const agentDetailQuery = useQuery({ queryKey: ["agent", agentId, "agentic-picker"], queryFn: () => api.agent(session!, agentId), enabled: open && Boolean(session && agentId) });
  const sessionsQuery = useQuery({ queryKey: ["sessions", "agentic-picker"], queryFn: () => api.listSessions(session!, { status: "active", page_size: 100, sort: "-last_activity_at" }), enabled: open && Boolean(session) });
  const grants = agentDetailQuery.data?.grants ?? [];
  const activeGrants = grants.filter((grant) => grant.status === "active" && !grant.revoked_at && !grant.consumed_at);
  const sessions = sessionsQuery.data?.items ?? [];
  const selectedSession = sessions.find((item) => item.session_id === selectedSessionId);
  const selectedGrant = activeGrants.find((grant) => grant.grant_id === grantId);
  const restricted = selectedSession?.trust_level === "RESTRICTED";

  const stepUpMutation = useMutation({
    mutationFn: () => api.createStepUp(session!, form.getValues("session_id")),
    onSuccess: (challenge) => {
      setStepUpChallenge(challenge);
      setOtp(challenge.simulated_otp ?? "");
      setStepUpError(null);
      if (!challenge.simulated_otp) toast.info("Step-up challenge issued. Enter the code out of band.");
    },
    onError: (cause) => setStepUpError(cause instanceof Error ? cause.message : "Could not issue a step-up challenge."),
  });

  const verifyMutation = useMutation({
    mutationFn: () => api.verifyStepUp(session!, form.getValues("session_id"), { challenge_id: stepUpChallenge!.challenge_id, code: otp }),
    onSuccess: (response) => {
      setStepUpToken(response.step_up_token);
      setStepUpError(null);
      toast.success("Step-up verified. The token is single-use.");
    },
    onError: (cause) => setStepUpError(cause instanceof Error ? cause.message : "Could not verify the step-up code."),
  });

  const payoutMutation = useMutation({
    mutationFn: (values: FormValues) => api.agenticPayout(session!, {
      agent_id: values.agent_id,
      authorization_grant_id: values.authorization_grant_id,
      session_id: values.session_id,
      recipient_email: values.recipient_email,
      amount: values.amount,
      currency: values.currency.toUpperCase(),
      reference_note: values.reference_note || null,
      agent_intent: values.agent_intent || null,
      idempotency_key: idempotencyKey,
      step_up_token: stepUpToken || null,
    }),
    onSuccess: (response) => {
      setResult(response);
      setReview(null);
      setSubmitError(null);
      void queryClient.invalidateQueries({ queryKey: ["agents"] });
      void queryClient.invalidateQueries({ queryKey: ["agent", response.agent_id] });
      void queryClient.invalidateQueries({ queryKey: ["agent-audit"] });
      void queryClient.invalidateQueries({ queryKey: ["payouts"] });
      void queryClient.invalidateQueries({ queryKey: ["analytics-overview"] });
      toast.success(`Gateway recorded ${titleCase(response.status)} for this agent request.`);
    },
    onError: (cause) => {
      setReview(null);
      setSubmitError(cause instanceof ApiError ? `${cause.code}: ${cause.message}` : "The connection failed after submission. The outcome is unknown — inspect the agent audit ledger before any new attempt.");
    },
    retry: false,
  });

  const resetStepUpOnSessionChange = () => {
    setStepUpChallenge(null);
    setOtp("");
    setStepUpToken("");
    setStepUpError(null);
  };

  const close = () => {
    if (payoutMutation.isPending) return;
    onOpenChange(false);
  };

  const canSubmit = Boolean(selectedGrant && selectedSession && (!restricted || stepUpToken));

  return (
    <>
      <Dialog open={open && !result} onOpenChange={(next) => (!next ? close() : undefined)}>
        <DialogContent className="max-h-[92vh] max-w-2xl overflow-y-auto">
          <DialogHeader>
            <DialogTitle className="flex items-center gap-2"><Bot className="h-4 w-4 text-primary" /> Agent-initiated payout</DialogTitle>
            <DialogDescription>Submit through the internal agentic adapter. Identity, scopes and limits are resolved server-side and cannot be claimed by the browser.</DialogDescription>
          </DialogHeader>

          <form className="space-y-4" onSubmit={form.handleSubmit((values) => { setSubmitError(null); setReview(values); })}>
            <div className="grid gap-3 sm:grid-cols-2">
              <div className="space-y-2">
                <Label htmlFor="agentic-agent">Agent</Label>
                <Controller control={form.control} name="agent_id" render={({ field }) => (
                  <Select value={field.value} onValueChange={(value) => { field.onChange(value); form.setValue("authorization_grant_id", ""); form.setValue("session_id", ""); resetStepUpOnSessionChange(); }} disabled={agentsQuery.isLoading}>
                    <SelectTrigger id="agentic-agent"><SelectValue placeholder={agentsQuery.isLoading ? "Loading agents…" : "Choose a registered agent"} /></SelectTrigger>
                    <SelectContent>{agentsQuery.data?.items.map((agent) => <SelectItem key={agent.agent_id} value={agent.agent_id}>{agent.display_name} · {agent.agent_type}{agent.max_payout_amount ? ` · ≤ ${formatMoney(agent.max_payout_amount, "USD")}` : ""}</SelectItem>)}</SelectContent>
                  </Select>
                )} />
                {agentsQuery.isError ? <p className="text-xs text-destructive" role="alert">Could not load agents. {agentsQuery.error instanceof Error ? agentsQuery.error.message : ""}</p> : null}
                {agentsQuery.data?.items.length === 0 ? <p className="text-xs text-muted-foreground">No active registered agents. The backend rejects unregistered agents.</p> : null}
                {form.formState.errors.agent_id ? <p className="text-xs text-destructive" role="alert">{form.formState.errors.agent_id.message}</p> : null}
              </div>
              <div className="space-y-2">
                <Label htmlFor="agentic-grant">Authorization grant</Label>
                <Controller control={form.control} name="authorization_grant_id" render={({ field }) => (
                  <Select value={field.value} onValueChange={(value) => {
                    field.onChange(value);
                    resetStepUpOnSessionChange();
                    const grant = activeGrants.find((item) => item.grant_id === value);
                    if (grant?.session_id) form.setValue("session_id", grant.session_id, { shouldValidate: true });
                  }} disabled={!agentId || agentDetailQuery.isLoading}>
                    <SelectTrigger id="agentic-grant"><SelectValue placeholder={!agentId ? "Choose an agent first" : agentDetailQuery.isLoading ? "Loading grants…" : activeGrants.length ? "Choose an active grant" : "No active grants"} /></SelectTrigger>
                    <SelectContent>{activeGrants.map((grant) => <SelectItem key={grant.grant_id} value={grant.grant_id}>{grant.grant_id.slice(0, 8)} · exp {new Date(grant.expires_at).toLocaleDateString()}{grant.max_amount ? ` · ≤ ${formatMoney(grant.max_amount, "USD")}` : ""}</SelectItem>)}</SelectContent>
                  </Select>
                )} />
                {form.formState.errors.authorization_grant_id ? <p className="text-xs text-destructive" role="alert">{form.formState.errors.authorization_grant_id.message}</p> : null}
                {agentId && !agentDetailQuery.isLoading && activeGrants.length === 0 ? <p className="text-xs text-signal-restricted">No active grant is available. The server will reject this agent otherwise.</p> : null}
              </div>
            </div>

            {selectedGrant ? (
              <div className="rounded-lg border border-border bg-muted/20 p-3 text-xs">
                <div className="flex flex-wrap gap-1.5">{(selectedGrant.scopes ?? []).map((scope) => <span key={scope} className="rounded bg-background px-1.5 py-0.5 font-mono text-[10px] ring-1 ring-border">{scope}</span>)}</div>
                <p className="mt-2 text-[11px] text-muted-foreground">Grant expires {new Date(selectedGrant.expires_at).toLocaleString()}{selectedGrant.max_amount ? ` · amount ceiling ${formatMoney(selectedGrant.max_amount, "USD")}` : ""}</p>
              </div>
            ) : null}

            <div className="space-y-2">
              <Label htmlFor="agentic-session">Session</Label>
              <Controller control={form.control} name="session_id" render={({ field }) => (
                <Select value={field.value} onValueChange={(value) => { field.onChange(value); resetStepUpOnSessionChange(); }} disabled={sessionsQuery.isLoading || Boolean(selectedGrant?.session_id)}>
                  <SelectTrigger id="agentic-session"><SelectValue placeholder={sessionsQuery.isLoading ? "Loading sessions…" : "Choose an active session"} /></SelectTrigger>
                  <SelectContent>{sessions.map((item) => <SelectItem key={item.session_id} value={item.session_id}>{item.trust_level} · {item.session_id.slice(0, 8)} · score {item.risk_score.toFixed(1)}</SelectItem>)}</SelectContent>
                </Select>
              )} />
              {selectedGrant?.session_id ? <p className="text-[11px] text-muted-foreground">Session bound by the selected authorization grant.</p> : null}
              {form.formState.errors.session_id ? <p className="text-xs text-destructive" role="alert">{form.formState.errors.session_id.message}</p> : null}
              {selectedSession ? <div className="flex items-center gap-2"><TrustBadge level={selectedSession.trust_level} /><span className="text-[11px] text-muted-foreground">Server score {selectedSession.risk_score.toFixed(1)}</span></div> : null}
            </div>

            {restricted ? (
              <div className="space-y-3 rounded-lg border border-signal-restricted/30 bg-signal-restricted/[0.06] p-3">
                <div className="flex items-center gap-2"><LockKeyhole className="h-4 w-4 text-signal-restricted" /><p className="text-xs font-semibold uppercase tracking-wider text-signal-restricted">Step-up required</p></div>
                {stepUpToken ? <p className="flex items-center gap-2 text-xs text-signal-normal"><ShieldCheck className="h-4 w-4" /> Step-up verified for this session.</p> : stepUpChallenge ? (
                  <div className="space-y-2">
                    <Label htmlFor="agent-step-up-code">Verification code</Label>
                    <p className="text-[11px] text-muted-foreground">{stepUpChallenge.simulated_otp ? "Development backend returned a simulated code and prefilled it. This code is not production material." : "Enter the code delivered by the configured verification channel."}</p>
                    <div className="flex gap-2"><Input id="agent-step-up-code" value={otp} onChange={(e) => setOtp(e.target.value)} inputMode="numeric" autoComplete="one-time-code" className="max-w-40" /><Button type="button" variant="outline" size="sm" onClick={() => verifyMutation.mutate()} disabled={verifyMutation.isPending || otp.length < 4}>{verifyMutation.isPending ? <Loader2 className="h-3.5 w-3.5 animate-spin" /> : null} Verify</Button></div>
                  </div>
                ) : <Button type="button" variant="outline" size="sm" onClick={() => stepUpMutation.mutate()} disabled={!selectedSessionId || stepUpMutation.isPending}>{stepUpMutation.isPending ? <Loader2 className="h-3.5 w-3.5 animate-spin" /> : <LockKeyhole className="h-3.5 w-3.5" />} Start step-up</Button>}
                {stepUpError ? <p className="text-xs text-destructive" role="alert">{stepUpError}</p> : null}
              </div>
            ) : null}

            <div className="grid gap-3 sm:grid-cols-2">
              <div className="space-y-2 sm:col-span-2"><Label htmlFor="agentic-recipient">Recipient email</Label><Input id="agentic-recipient" type="email" autoComplete="off" {...form.register("recipient_email")} aria-invalid={Boolean(form.formState.errors.recipient_email)} />{form.formState.errors.recipient_email ? <p className="text-xs text-destructive" role="alert">{form.formState.errors.recipient_email.message}</p> : null}</div>
              <div className="space-y-2"><Label htmlFor="agentic-amount">Amount</Label><Input id="agentic-amount" type="number" step="0.01" min="0" {...form.register("amount", { valueAsNumber: true })} />{form.formState.errors.amount ? <p className="text-xs text-destructive" role="alert">{form.formState.errors.amount.message}</p> : null}</div>
              <div className="space-y-2"><Label htmlFor="agentic-currency">Currency</Label><Input id="agentic-currency" maxLength={3} {...form.register("currency")} />{form.formState.errors.currency ? <p className="text-xs text-destructive" role="alert">{form.formState.errors.currency.message}</p> : null}</div>
              <div className="space-y-2 sm:col-span-2"><Label htmlFor="agentic-intent">Agent intent (optional)</Label><Input id="agentic-intent" maxLength={255} placeholder="Business purpose recorded for audit" {...form.register("agent_intent")} /></div>
              <div className="space-y-2 sm:col-span-2"><Label htmlFor="agentic-reference">Reference note (optional)</Label><Textarea id="agentic-reference" rows={2} maxLength={255} {...form.register("reference_note")} /></div>
            </div>

            <div className="space-y-1 rounded-lg bg-muted/30 p-3"><p className="text-[11px] text-muted-foreground">Idempotency key (new per dialog, preserved verbatim)</p><p className="break-all font-mono text-[10px]">{idempotencyKey}</p></div>
            {submitError ? <InfoNote tone="danger" title="Submission failed">{submitError} The console will not retry automatically. Inspect the agent audit trail and payout ledger before another attempt.</InfoNote> : null}
            {!canSubmit && selectedGrant && !restricted ? <p className="text-[11px] text-muted-foreground">Choose a session bound to this grant to enable submission.</p> : null}
            <DialogFooter><Button type="button" variant="ghost" onClick={close} disabled={payoutMutation.isPending}>Cancel</Button><Button type="submit" disabled={payoutMutation.isPending || !canSubmit}>{payoutMutation.isPending ? <Loader2 className="h-4 w-4 animate-spin" /> : null} Review agent payout</Button></DialogFooter>
          </form>
        </DialogContent>
      </Dialog>

      <ConfirmDialog
        open={Boolean(review)}
        onOpenChange={(next) => { if (!next && !payoutMutation.isPending) setReview(null); }}
        title="Confirm agent-initiated payout"
        description="This is a consequential action. The gateway will evaluate risk and may execute a real provider payout for a normal session, or route to a decoy or rejection path. Confirm only after verifying the agent, grant, session and amount."
        confirmLabel={payoutMutation.isPending ? "Submitting once…" : "Submit agent payout"}
        onConfirm={() => { if (review) payoutMutation.mutate(review); }}
        pending={payoutMutation.isPending}
      >
        {review ? (
          <div className="space-y-3 text-sm">
            <dl className="grid gap-2 sm:grid-cols-2">
              <div><dt className="text-[11px] text-muted-foreground">Agent</dt><dd className="font-medium">{agentDetailQuery.data?.agent.display_name ?? review.agent_id}</dd></div>
              <div><dt className="text-[11px] text-muted-foreground">Grant</dt><dd className="break-all font-mono text-xs">{review.authorization_grant_id}</dd></div>
              <div><dt className="text-[11px] text-muted-foreground">Session</dt><dd className="font-mono text-xs">{review.session_id}</dd></div>
              <div><dt className="text-[11px] text-muted-foreground">Trust</dt><dd>{selectedSession ? <TrustBadge level={selectedSession.trust_level} /> : "—"}</dd></div>
              <div><dt className="text-[11px] text-muted-foreground">Recipient</dt><dd className="break-all">{review.recipient_email}</dd></div>
              <div><dt className="text-[11px] text-muted-foreground">Amount</dt><dd className="font-semibold">{formatMoney(review.amount, review.currency.toUpperCase())}</dd></div>
            </dl>
            <InfoNote tone="warning" title="No automatic retry">If the connection fails after submission, the outcome may already have executed. Inspect the ledger and agent audit trail; do not create a new attempt blindly.</InfoNote>
          </div>
        ) : null}
      </ConfirmDialog>

      <Dialog open={Boolean(result)} onOpenChange={(next) => { if (!next) { setResult(null); onOpenChange(false); } }}>
        <DialogContent className="max-w-lg">
          <DialogHeader><DialogTitle>Authoritative agent outcome</DialogTitle><DialogDescription>The gateway response is shown as recorded, including rejected, blocked and decoy outcomes.</DialogDescription></DialogHeader>
          {result ? (
            <div className="space-y-3">
              <div className="flex flex-wrap items-center gap-2"><StatusBadge status={result.status} /><TrustBadge level={result.trust_level} /><span className="text-sm font-semibold">{formatMoney(result.amount, result.currency)}</span></div>
              <dl className="grid gap-2 text-sm sm:grid-cols-2">
                <ResultField label="Action" value={<StatusBadge status={result.action} />} />
                <ResultField label="Routing" value={humanizeCode(result.routing_destination)} />
                <ResultField label="Risk score" value={result.risk_score.toFixed(1)} />
                <ResultField label="Provider reference" value={result.provider_reference ?? "None"} />
                <ResultField label="Agent" value={result.agent_display_name} />
                <ResultField label="Grant" value={<span className="break-all font-mono text-xs">{result.authorization_grant_id}</span>} />
                <ResultField label="Payout" value={<Link to={`/payouts/${result.payout_id}`} className="font-mono text-xs text-primary hover:underline">{result.payout_id}</Link>} />
                <ResultField label="Duplicate" value={result.is_duplicate ? "Served from idempotency cache" : "No"} />
              </dl>
              {result.reason_codes?.length ? <div className="flex flex-wrap gap-1">{result.reason_codes.map((code) => <span key={code} className="rounded bg-muted px-1.5 py-0.5 font-mono text-[10px]">{code}</span>)}</div> : null}
              <InfoNote tone={result.status === "completed" ? "info" : "warning"} title="Recorded outcome">{result.status === "completed" ? "Provider execution was recorded. Reconcile as required; do not resubmit." : "This outcome was recorded by the gateway. It may be a rejection, block or synthetic decoy result. Do not treat it as a successful real payment."}</InfoNote>
            </div>
          ) : null}
          <DialogFooter><Button asChild variant="outline"><Link to="/agents/audit">Open agent audit <ArrowUpRight className="h-3.5 w-3.5" /></Link></Button><Button onClick={() => { setResult(null); onOpenChange(false); }}>Done</Button></DialogFooter>
        </DialogContent>
      </Dialog>
    </>
  );
}

function ResultField({ label, value }: { label: string; value: React.ReactNode }) {
  return <div><dt className="text-[11px] text-muted-foreground">{label}</dt><dd className="mt-0.5 break-all">{value}</dd></div>;
}

