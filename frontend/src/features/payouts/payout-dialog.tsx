import { zodResolver } from "@hookform/resolvers/zod";
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { ArrowRight, Loader2, LockKeyhole, ShieldCheck } from "lucide-react";
import { useState } from "react";
import { Controller, useForm, useWatch } from "react-hook-form";
import { Link } from "react-router-dom";
import { toast } from "sonner";
import { z } from "zod";
import { StatusBadge, TrustBadge } from "@/components/common/badges";
import { ConfirmDialog } from "@/components/common/confirm-dialog";
import { InfoNote } from "@/components/common/info-note";
import { Button } from "@/components/ui/button";
import {
  Dialog,
  DialogContent,
  DialogDescription,
  DialogFooter,
  DialogHeader,
  DialogTitle,
} from "@/components/ui/dialog";
import { Input } from "@/components/ui/input";
import { Label } from "@/components/ui/label";
import { Select, SelectContent, SelectItem, SelectTrigger, SelectValue } from "@/components/ui/select";
import { Textarea } from "@/components/ui/textarea";
import { api, ApiError, type Schema } from "@/lib/api";
import { useAuth } from "@/lib/auth";
import { formatMoney, newIdempotencyKey, titleCase } from "@/lib/format";

const payoutSchema = z.object({
  session_id: z.string().min(1, "Select an active session."),
  recipient_email: z.string().email("Enter a valid recipient email."),
  amount: z
    .number({ message: "Enter a payout amount." })
    .positive("Amount must be greater than zero.")
    .max(100_000, "The gateway maximum is 100,000."),
  currency: z.string().length(3, "Use a three-letter currency code."),
  reference_note: z.string().max(255, "Keep the reference under 255 characters.").optional(),
});

type FormValues = z.infer<typeof payoutSchema>;

type PayoutResult = Schema<"PayoutResponse">;

export function PayoutDialog({
  open,
  onOpenChange,
}: {
  open: boolean;
  onOpenChange: (open: boolean) => void;
}) {
  // Remount on each open so submission, step-up and idempotency state cannot
  // leak from a previous payout attempt.
  return (
    <PayoutDialogBody
      key={open ? "open" : "closed"}
      open={open}
      onOpenChange={onOpenChange}
    />
  );
}

function PayoutDialogBody({
  open,
  onOpenChange,
}: {
  open: boolean;
  onOpenChange: (open: boolean) => void;
}) {
  const { session } = useAuth();
  const queryClient = useQueryClient();
  const [idempotencyKey] = useState(() => newIdempotencyKey("payout"));
  const [review, setReview] = useState<FormValues | null>(null);
  const [result, setResult] = useState<PayoutResult | null>(null);
  const [stepUpChallenge, setStepUpChallenge] = useState<Schema<"StepUpChallengeCreateResponse"> | null>(null);
  const [otp, setOtp] = useState("");
  const [stepUpToken, setStepUpToken] = useState("");
  const [stepUpError, setStepUpError] = useState<string | null>(null);

  const form = useForm<FormValues>({
    resolver: zodResolver(payoutSchema),
    defaultValues: {
      session_id: "",
      recipient_email: "",
      amount: 0,
      currency: "USD",
      reference_note: "",
    },
    mode: "onBlur",
  });

  const selectedSessionId = useWatch({ control: form.control, name: "session_id" });
  const sessionsQuery = useQuery({
    queryKey: ["sessions", "payout-picker"],
    queryFn: () => api.listSessions(session!, { status: "active", page_size: 100, sort: "-last_activity_at" }),
    enabled: open && Boolean(session),
  });
  const sessions = sessionsQuery.data?.items ?? [];
  const selectedSession = sessions.find((item) => item.session_id === selectedSessionId);
  const restricted = selectedSession?.trust_level === "RESTRICTED";
  const requiresStepUp = restricted && !stepUpToken;

  const resetStepUp = () => {
    setStepUpChallenge(null);
    setOtp("");
    setStepUpToken("");
    setStepUpError(null);
  };

  const stepUpMutation = useMutation({
    mutationFn: () => api.createStepUp(session!, form.getValues("session_id")),
    onSuccess: (challenge) => {
      setStepUpChallenge(challenge);
      setOtp(challenge.simulated_otp ?? "");
      setStepUpError(null);
      if (!challenge.simulated_otp) {
        toast.info("A step-up challenge was issued. Enter the verification code out of band.");
      }
    },
    onError: (cause) => setStepUpError(cause instanceof Error ? cause.message : "Could not issue step-up challenge."),
  });

  const verifyMutation = useMutation({
    mutationFn: () =>
      api.verifyStepUp(session!, form.getValues("session_id"), {
        challenge_id: stepUpChallenge!.challenge_id,
        code: otp,
      }),
    onSuccess: (response) => {
      setStepUpToken(response.step_up_token);
      setStepUpError(null);
      toast.success("Step-up verified for this session. The token is single-use.");
    },
    onError: (cause) => setStepUpError(cause instanceof Error ? cause.message : "Could not verify the step-up code."),
  });

  const payoutMutation = useMutation({
    retry: false,
    mutationFn: (values: FormValues) =>
      api.executePayout(session!, {
        session_id: values.session_id,
        recipient_email: values.recipient_email,
        amount: values.amount,
        currency: values.currency,
        reference_note: values.reference_note || null,
        idempotency_key: idempotencyKey,
        step_up_token: stepUpToken || null,
      }),
    onSuccess: (response) => {
      setResult(response);
      setReview(null);
      void queryClient.invalidateQueries({ queryKey: ["payouts"] });
      void queryClient.invalidateQueries({ queryKey: ["analytics-overview"] });
      void queryClient.invalidateQueries({ queryKey: ["sessions"] });
      void queryClient.invalidateQueries({ queryKey: ["identities"] });
      toast.success(`Gateway recorded ${titleCase(response.status)} for this payout.`);
    },
    onError: (cause) => {
      // The mutation is deliberately never retried. A transport failure may
      // have happened after execution, so the operator must inspect the ledger.
      setReview(null);
      const message =
        cause instanceof ApiError
          ? cause.message
          : "The connection failed after submission. The outcome is unknown — inspect the ledger before any new attempt.";
      toast.error(message);
    },
  });

  const close = () => {
    if (payoutMutation.isPending) return;
    onOpenChange(false);
  };

  const expectedCopy = selectedSession
    ? selectedSession.trust_level === "NORMAL"
      ? "Expected path: provider execution if all policy checks pass."
      : selectedSession.trust_level === "RESTRICTED"
        ? "Restricted sessions require step-up verification. Amounts above the configured limit are rejected server-side."
        : selectedSession.trust_level === "DECOY"
          ? "Decoy sessions route to the synthetic honey workspace. No real recipient is paid."
          : "Isolated sessions are blocked and may trigger containment. No provider is contacted."
    : "Choose a session to see the server-side routing expectation.";

  return (
    <>
      <Dialog open={open && !result} onOpenChange={(next) => (!next ? close() : undefined)}>
        <DialogContent className="max-w-xl">
          <DialogHeader>
            <DialogTitle>Execute protected payout</DialogTitle>
            <DialogDescription>
              The Trust Gateway evaluates risk, chooses routing and executes the provider call. This console never scores risk locally.
            </DialogDescription>
          </DialogHeader>

          <form className="space-y-4" onSubmit={form.handleSubmit((values) => setReview(values))}>
            <div className="space-y-2">
              <Label htmlFor="payout-session">Session</Label>
              {sessionsQuery.isLoading ? (
                <div className="h-9 animate-pulse rounded-lg bg-muted" />
              ) : sessions.length === 0 ? (
                <InfoNote tone="warning">
                  No active sessions are available. <Link className="underline" to="/sessions">Inspect sessions</Link> or create one through the backend.
                </InfoNote>
              ) : (
                <Controller
                  control={form.control}
                  name="session_id"
                  render={({ field }) => (
                    <Select
                      value={field.value}
                      onValueChange={(value) => {
                        field.onChange(value);
                        resetStepUp();
                      }}
                    >
                      <SelectTrigger id="payout-session" aria-describedby="payout-session-help">
                        <SelectValue placeholder="Select an active session" />
                      </SelectTrigger>
                      <SelectContent>
                        {sessions.map((item) => (
                          <SelectItem key={item.session_id} value={item.session_id}>
                            {item.trust_level} · {item.session_id.slice(0, 8)} · score {item.risk_score.toFixed(1)}
                          </SelectItem>
                        ))}
                      </SelectContent>
                    </Select>
                  )}
                />
              )}
              {form.formState.errors.session_id ? (
                <p className="text-xs text-destructive" role="alert">{form.formState.errors.session_id.message}</p>
              ) : null}
              <p id="payout-session-help" className="text-[11px] leading-5 text-muted-foreground">{expectedCopy}</p>
              {selectedSession ? (
                <div className="flex items-center gap-2">
                  <TrustBadge level={selectedSession.trust_level} />
                  <span className="text-[11px] text-muted-foreground">Server score {selectedSession.risk_score.toFixed(1)}</span>
                </div>
              ) : null}
            </div>

            {restricted ? (
              <div className="space-y-3 rounded-lg border border-signal-restricted/30 bg-signal-restricted/[0.06] p-3">
                <div className="flex items-center gap-2">
                  <LockKeyhole className="h-4 w-4 text-signal-restricted" aria-hidden="true" />
                  <p className="text-xs font-semibold uppercase tracking-wider text-signal-restricted">Step-up required</p>
                </div>
                {stepUpToken ? (
                  <p className="flex items-center gap-2 text-xs text-signal-normal">
                    <ShieldCheck className="h-4 w-4" aria-hidden="true" />
                    Step-up verified. The token will be submitted once with this payout.
                  </p>
                ) : stepUpChallenge ? (
                  <div className="space-y-2">
                    <Label htmlFor="step-up-code">Verification code</Label>
                    <p className="text-[11px] text-muted-foreground">
                      {stepUpChallenge.simulated_otp
                        ? "Development backend returned a simulated code and prefilled it. Production providers must return no code."
                        : "Enter the code delivered by the configured verification channel."}
                    </p>
                    <div className="flex gap-2">
                      <Input
                        id="step-up-code"
                        value={otp}
                        onChange={(event) => setOtp(event.target.value)}
                        inputMode="numeric"
                        autoComplete="one-time-code"
                        className="font-mono"
                      />
                      <Button
                        onClick={() => verifyMutation.mutate()}
                        disabled={verifyMutation.isPending || otp.length < 4}
                      >
                        {verifyMutation.isPending ? <Loader2 className="h-4 w-4 animate-spin" /> : null}
                        Verify
                      </Button>
                    </div>
                  </div>
                ) : (
                  <Button
                    variant="outline"
                    size="sm"
                    onClick={() => stepUpMutation.mutate()}
                    disabled={stepUpMutation.isPending || !selectedSessionId}
                  >
                    {stepUpMutation.isPending ? <Loader2 className="h-4 w-4 animate-spin" /> : <LockKeyhole className="h-4 w-4" />}
                    Start step-up challenge
                  </Button>
                )}
                {stepUpError ? <p className="text-xs text-destructive" role="alert">{stepUpError}</p> : null}
              </div>
            ) : null}

            <div className="grid gap-3 sm:grid-cols-2">
              <div className="space-y-2 sm:col-span-2">
                <Label htmlFor="recipient">Recipient email</Label>
                <Input id="recipient" type="email" placeholder="beneficiary@example.com" autoComplete="off" {...form.register("recipient_email")} />
                {form.formState.errors.recipient_email ? (
                  <p className="text-xs text-destructive" role="alert">{form.formState.errors.recipient_email.message}</p>
                ) : null}
              </div>
              <div className="space-y-2">
                <Label htmlFor="amount">Amount</Label>
                <Input
                  id="amount"
                  type="number"
                  inputMode="decimal"
                  min="0"
                  step="0.01"
                  {...form.register("amount", { valueAsNumber: true })}
                />
                {form.formState.errors.amount ? (
                  <p className="text-xs text-destructive" role="alert">{form.formState.errors.amount.message}</p>
                ) : null}
              </div>
              <div className="space-y-2">
                <Label htmlFor="currency">Currency</Label>
                <Controller
                  control={form.control}
                  name="currency"
                  render={({ field }) => (
                    <Select value={field.value} onValueChange={field.onChange}>
                      <SelectTrigger id="currency"><SelectValue /></SelectTrigger>
                      <SelectContent>
                        <SelectItem value="USD">USD</SelectItem>
                        <SelectItem value="EUR">EUR</SelectItem>
                        <SelectItem value="GBP">GBP</SelectItem>
                      </SelectContent>
                    </Select>
                  )}
                />
              </div>
              <div className="space-y-2 sm:col-span-2">
                <Label htmlFor="reference">Reference note</Label>
                <Textarea id="reference" rows={2} placeholder="Invoice or business reference" {...form.register("reference_note")} />
              </div>
            </div>

            <div className="rounded-lg border border-border bg-muted/30 p-3 font-mono text-[11px] text-muted-foreground">
              Idempotency key: <span className="break-all text-foreground">{idempotencyKey}</span>
            </div>

            <DialogFooter>
              <Button variant="outline" onClick={close}>Cancel</Button>
              <Button
                type="submit"
                disabled={form.formState.isSubmitting || requiresStepUp || sessions.length === 0}
              >
                Review payout
                <ArrowRight className="h-4 w-4" aria-hidden="true" />
              </Button>
            </DialogFooter>
            {requiresStepUp ? (
              <p className="text-[11px] text-signal-restricted">Complete step-up verification before reviewing this payout.</p>
            ) : null}
          </form>
        </DialogContent>
      </Dialog>

      <ConfirmDialog
        open={Boolean(review)}
        onOpenChange={(next) => (!next ? setReview(null) : undefined)}
        title="Confirm payout execution"
        description="This submission can move money. The gateway may route it to a provider, reject it, or divert it to a synthetic decoy. Review the authoritative inputs below."
        confirmLabel="Execute once"
        onConfirm={() => {
          if (review) payoutMutation.mutate(review);
        }}
        pending={payoutMutation.isPending}
        destructive
      >
        {review ? (
          <div className="space-y-3">
            <dl className="grid gap-2 rounded-lg border border-border p-3 text-sm sm:grid-cols-2">
              <div><dt className="text-[11px] uppercase tracking-wider text-muted-foreground">Amount</dt><dd className="font-medium">{formatMoney(review.amount, review.currency)}</dd></div>
              <div><dt className="text-[11px] uppercase tracking-wider text-muted-foreground">Recipient</dt><dd className="break-all font-medium">{review.recipient_email}</dd></div>
              <div><dt className="text-[11px] uppercase tracking-wider text-muted-foreground">Session</dt><dd className="font-mono text-xs">{review.session_id}</dd></div>
              <div><dt className="text-[11px] uppercase tracking-wider text-muted-foreground">Routing expectation</dt><dd><TrustBadge level={selectedSession?.trust_level} /></dd></div>
            </dl>
            <InfoNote tone="warning" title="No automatic retry">
              The console does not retry this mutation. If the connection drops after submission, inspect the payout ledger for this idempotency key before doing anything else.
            </InfoNote>
          </div>
        ) : null}
      </ConfirmDialog>

      <Dialog open={Boolean(result)} onOpenChange={(next) => (!next ? close() : undefined)}>
        <DialogContent>
          <DialogHeader>
            <DialogTitle>Gateway outcome recorded</DialogTitle>
            <DialogDescription>
              These values come directly from the authoritative gateway response. They are not a console prediction.
            </DialogDescription>
          </DialogHeader>
          {result ? (
            <div className="space-y-3">
              <dl className="grid gap-3 rounded-lg border border-border p-4 text-sm sm:grid-cols-2">
                <div><dt className="text-[11px] uppercase tracking-wider text-muted-foreground">Status</dt><dd className="mt-1"><StatusBadge status={result.status} /></dd></div>
                <div><dt className="text-[11px] uppercase tracking-wider text-muted-foreground">Action</dt><dd className="mt-1"><StatusBadge status={result.action} /></dd></div>
                <div><dt className="text-[11px] uppercase tracking-wider text-muted-foreground">Trust level</dt><dd className="mt-1"><TrustBadge level={result.trust_level} /></dd></div>
                <div><dt className="text-[11px] uppercase tracking-wider text-muted-foreground">Risk score</dt><dd className="mt-1 font-mono">{result.risk_score.toFixed(1)}</dd></div>
                <div className="sm:col-span-2"><dt className="text-[11px] uppercase tracking-wider text-muted-foreground">Provider reference</dt><dd className="mt-1 font-mono text-xs">{result.provider_reference ?? "—"}</dd></div>
                <div className="sm:col-span-2"><dt className="text-[11px] uppercase tracking-wider text-muted-foreground">Reason codes</dt><dd className="mt-1 flex flex-wrap gap-1">{result.reason_codes.length ? result.reason_codes.map((code) => <span key={code} className="rounded bg-muted px-1.5 py-0.5 font-mono text-[11px]">{code}</span>) : "None"}</dd></div>
              </dl>
              {result.is_duplicate ? (
                <InfoNote tone="warning" title="Served from idempotency cache">
                  The gateway did not execute a second payment for this key. The existing outcome is shown.
                </InfoNote>
              ) : null}
              <Button asChild variant="outline" className="w-full">
                <Link to={`/payouts/${result.payout_id}`} onClick={close}>Open payout record</Link>
              </Button>
            </div>
          ) : null}
          <DialogFooter>
            <Button onClick={close}>Done</Button>
          </DialogFooter>
        </DialogContent>
      </Dialog>
    </>
  );
}
