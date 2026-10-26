import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { ArrowUpRight, FlaskConical, Loader2, Play, RefreshCw, ShieldCheck, TriangleAlert } from "lucide-react";
import { useState } from "react";
import { Link } from "react-router-dom";
import { EmptyState } from "@/components/common/empty-state";
import { ErrorState } from "@/components/common/error-state";
import { InfoNote } from "@/components/common/info-note";
import { CardsLoading } from "@/components/common/loading-state";
import { PageHeader } from "@/components/common/page-header";
import { ConfirmDialog } from "@/components/common/confirm-dialog";
import { Badge } from "@/components/ui/badge";
import { Button } from "@/components/ui/button";
import { Card, CardContent, CardDescription, CardHeader, CardTitle } from "@/components/ui/card";
import { Table, TableBody, TableCell, TableHead, TableHeader, TableRow } from "@/components/ui/table";
import { api, ApiError } from "@/lib/api";
import { useAuth } from "@/lib/auth";
import { formatDateTime, formatPercent, humanizeCode } from "@/lib/format";
import { cn } from "@/lib/utils";

export function SimulationPage() {
  const { session } = useAuth();
  const queryClient = useQueryClient();
  const [confirmOpen, setConfirmOpen] = useState(false);
  const scenarios = useQuery({ queryKey: ["simulation-scenarios"], queryFn: () => api.simulationScenarios(session!), enabled: Boolean(session) });
  const calibration = useQuery({ queryKey: ["calibration"], queryFn: () => api.calibration(session!), enabled: Boolean(session) });
  const drill = useMutation({
    mutationFn: () => api.runSimulation(session!),
    retry: false,
    onSuccess: () => {
      setConfirmOpen(false);
      void queryClient.invalidateQueries({ queryKey: ["incidents"] });
      void queryClient.invalidateQueries({ queryKey: ["sessions"] });
      void queryClient.invalidateQueries({ queryKey: ["identities"] });
      void queryClient.invalidateQueries({ queryKey: ["evidence-seals"] });
      void queryClient.invalidateQueries({ queryKey: ["honey-workspaces"] });
      void queryClient.invalidateQueries({ queryKey: ["honey-canaries"] });
      void queryClient.invalidateQueries({ queryKey: ["analytics-overview"] });
    },
  });
  const scenario = (scenarios.data?.scenarios ?? [])[0];
  const environment = scenarios.data?.environment ?? "unknown";
  const production = environment.toLowerCase() === "production";

  return (
    <div className="space-y-5">
      <PageHeader
        eyebrow="Simulation & calibration"
        title="Synthetic attack drills"
        description="Run only server-implemented scenarios and inspect the committed synthetic calibration. Results are bounded by the dataset and are not production fraud proof."
        actions={<Button variant="outline" size="sm" onClick={() => { void scenarios.refetch(); void calibration.refetch(); }} disabled={scenarios.isFetching || calibration.isFetching}><RefreshCw className={cn("h-3.5 w-3.5", (scenarios.isFetching || calibration.isFetching) && "animate-spin")} /> Refresh</Button>}
      />

      <InfoNote tone="warning" title="Synthetic and non-production">
        The drill creates synthetic sessions, canaries, an incident and evidence. It never contacts a real payment network. Production environments reject the drill with <span className="font-mono">SIMULATION_DISABLED_IN_PRODUCTION</span>. The console does not invent scenarios the backend does not implement.
      </InfoNote>

      <div className="grid gap-4 xl:grid-cols-3">
        <Card className="xl:col-span-2">
          <CardHeader><CardTitle className="flex items-center gap-2"><FlaskConical className="h-4 w-4 text-primary" /> Implemented scenario</CardTitle><CardDescription>Scenario metadata is served by the backend, not hardcoded in the console.</CardDescription></CardHeader>
          <CardContent className="space-y-4">
            {scenarios.isError ? <ErrorState error={scenarios.error} onRetry={() => void scenarios.refetch()} /> : scenarios.isLoading ? <div className="h-40 animate-pulse rounded-lg bg-muted" /> : !scenario ? <EmptyState icon={FlaskConical} title="No simulation scenario available" description="The backend returned no implemented attack scenarios for this environment." /> : (
              <>
                <div><div className="flex flex-wrap items-center gap-2"><h3 className="text-base font-semibold">{scenario.name}</h3><Badge variant="outline" className="font-mono">{scenario.attack_type}</Badge></div><p className="mt-1 text-sm leading-6 text-muted-foreground">{scenario.description}</p></div>
                <div className="grid gap-3 sm:grid-cols-3">
                  <div className="rounded-lg border border-border p-3"><p className="text-[10px] uppercase tracking-wider text-muted-foreground">Expected trust state</p><p className="mt-1 text-sm font-semibold">{scenario.expected_trust_state}</p></div>
                  <div className="rounded-lg border border-border p-3"><p className="text-[10px] uppercase tracking-wider text-muted-foreground">Minimum score</p><p className="mt-1 text-sm font-semibold">{scenario.expected_min_score.toFixed(1)}</p></div>
                  <div className="rounded-lg border border-border p-3"><p className="text-[10px] uppercase tracking-wider text-muted-foreground">Endpoint</p><p className="mt-1 break-all font-mono text-[11px]">{scenario.method} {scenario.endpoint}</p></div>
                </div>
                <div><p className="text-[11px] font-semibold uppercase tracking-wider text-muted-foreground">Expected outcomes</p><ul className="mt-2 space-y-1.5">{scenario.expected_outcomes?.map((outcome) => <li key={outcome} className="flex items-start gap-2 text-xs text-muted-foreground"><span className="mt-1.5 h-1 w-1 shrink-0 rounded-full bg-primary" aria-hidden="true" />{outcome}</li>)}</ul></div>
                <div><p className="text-[11px] font-semibold uppercase tracking-wider text-muted-foreground">Safety controls</p><ul className="mt-2 space-y-1.5">{scenario.safety?.map((item) => <li key={item} className="flex items-start gap-2 text-xs text-muted-foreground"><ShieldCheck className="mt-0.5 h-3.5 w-3.5 shrink-0 text-signal-normal" />{item}</li>)}</ul></div>
                <div className="flex flex-wrap items-center gap-3 border-t border-border pt-4">
                  <Button onClick={() => setConfirmOpen(true)} disabled={production || drill.isPending}><Play className="h-4 w-4" /> Run synthetic drill</Button>
                  {production ? <p className="text-xs text-signal-restricted">Blocked by environment: the backend disables this drill in production.</p> : <p className="text-xs text-muted-foreground">Environment: <span className="font-mono">{environment}</span></p>}
                </div>
                {drill.isError ? <ErrorState error={drill.error} title="Drill did not complete" extra={drill.error instanceof ApiError && drill.error.code === "SIMULATION_DISABLED_IN_PRODUCTION" ? <p className="text-xs text-muted-foreground">No records were created by this rejected request.</p> : <p className="text-xs text-muted-foreground">The console did not retry. Inspect incidents and sessions before another attempt.</p>} /> : null}
                {drill.isSuccess && drill.data ? (
                  <div className="rounded-lg border border-signal-normal/30 bg-signal-normal/[0.05] p-4" data-testid="simulation-result">
                    <div className="flex items-center gap-2"><ShieldCheck className="h-4 w-4 text-signal-normal" /><p className="text-sm font-semibold">Drill completed: synthetic records created</p></div>
                    <p className="mt-1 text-xs text-muted-foreground">This result proves the drill path executed; it does not prove production fraud prevention.</p>
                    <dl className="mt-3 grid gap-2 text-[11px] sm:grid-cols-2">
                      <div><dt className="text-muted-foreground">Synthetic session</dt><dd><Link className="font-mono text-primary hover:underline" to={`/sessions/${drill.data.session_id}`}>{drill.data.session_id}</Link></dd></div>
                      <div><dt className="text-muted-foreground">Incident sealed</dt><dd className="font-mono">{drill.data.incident_sealed ? "Yes" : "Not reported"}</dd></div>
                      <div><dt className="text-muted-foreground">Incident</dt><dd>{drill.data.incident_id ? <Link className="font-mono text-primary hover:underline" to={`/incidents/${drill.data.incident_id}`}>{drill.data.incident_id}</Link> : "None"}</dd></div>
                      <div><dt className="text-muted-foreground">Chain consistency</dt><dd className="font-mono">{drill.data.evidence_verify?.valid ? `Consistent (${drill.data.evidence_verify.checked})` : `Not consistent${drill.data.evidence_verify?.reason ? ` · ${drill.data.evidence_verify.reason}` : ""}`}</dd></div>
                    </dl>
                    <div className="mt-3 flex flex-wrap gap-2"><Button asChild size="sm" variant="outline"><Link to={`/incidents/${drill.data.incident_id}`}>Review incident <ArrowUpRight className="h-3.5 w-3.5" /></Link></Button><Button asChild size="sm" variant="ghost"><Link to="/evidence">Evidence vault</Link></Button></div>
                  </div>
                ) : null}
              </>
            )}
          </CardContent>
        </Card>

        <Card>
          <CardHeader><CardTitle>Drill guardrails</CardTitle><CardDescription>What this operation does and does not do.</CardDescription></CardHeader>
          <CardContent className="space-y-3 text-xs leading-5 text-muted-foreground">
            <p className="flex gap-2"><TriangleAlert className="mt-0.5 h-4 w-4 shrink-0 text-signal-restricted" /> The drill writes synthetic records to the database and opens a real incident record in this tenant.</p>
            <p className="flex gap-2"><ShieldCheck className="mt-0.5 h-4 w-4 shrink-0 text-signal-normal" /> It uses the mock provider and a synthetic canary; it never executes a real payout.</p>
            <p className="flex gap-2"><ShieldCheck className="mt-0.5 h-4 w-4 shrink-0 text-signal-normal" /> The backend rejects the operation in production mode. The UI reflects that server rule and does not bypass it.</p>
            <p>A drill pass is not a calibration result, a production control test or evidence that slow-and-low fraud is detected.</p>
          </CardContent>
        </Card>
      </div>

      <Card>
        <CardHeader><CardTitle>Calibration report</CardTitle><CardDescription>Synthetic calibration and held-out cohorts. Percentages are computed by the backend.</CardDescription></CardHeader>
        {calibration.isError ? <div className="p-4"><ErrorState error={calibration.error} onRetry={() => void calibration.refetch()} /></div> : calibration.isLoading ? <CardsLoading count={3} className="p-4" /> : calibration.data ? (
          <CardContent className="space-y-5">
            <div className="flex flex-wrap items-center gap-2 text-xs text-muted-foreground"><Badge variant="violet">Synthetic dataset</Badge><span>Seed <span className="font-mono">{calibration.data.seed}</span></span><span>·</span><span>Generated {formatDateTime(calibration.data.generated_at)}</span></div>
            <div className="grid gap-3 md:grid-cols-3">
              {[calibration.data.overall, calibration.data.calibration, calibration.data.holdout].map((split) => (
                <div key={split.name} className="rounded-xl border border-border p-4">
                  <div className="flex items-center justify-between gap-2"><p className="text-sm font-semibold">{humanizeCode(split.name)}</p><Badge variant="outline">{split.sessions} sessions</Badge></div>
                  <dl className="mt-3 space-y-2 text-xs">
                    <div className="flex justify-between gap-2"><dt className="text-muted-foreground">Detection rate</dt><dd className="font-mono font-semibold">{formatPercent(split.detection_rate)}</dd></div>
                    <div className="flex justify-between gap-2"><dt className="text-muted-foreground">False-positive rate</dt><dd className="font-mono font-semibold">{formatPercent(split.false_positive_rate)}</dd></div>
                    <div className="flex justify-between gap-2"><dt className="text-muted-foreground">Detected identities</dt><dd className="font-mono">{split.detected}/{split.compromised_identities}</dd></div>
                    <div className="flex justify-between gap-2"><dt className="text-muted-foreground">Mean session score</dt><dd className="font-mono">{split.mean_session_score.toFixed(2)}</dd></div>
                    <div className="flex justify-between gap-2"><dt className="text-muted-foreground">Max score</dt><dd className="font-mono">{split.max_score.toFixed(1)}</dd></div>
                  </dl>
                  <div className="mt-3 h-1.5 overflow-hidden rounded-full bg-muted"><div className="h-full rounded-full bg-primary" style={{ width: `${Math.min(100, Math.max(0, split.detection_rate))}%` }} /></div>
                </div>
              ))}
            </div>
            <div className="grid gap-4 xl:grid-cols-2">
              <div><h3 className="text-[11px] font-semibold uppercase tracking-wider text-muted-foreground">Cohort detail</h3><Table><TableHeader><TableRow><TableHead>Split</TableHead><TableHead>Flagged sessions</TableHead><TableHead>Benign FP</TableHead><TableHead>Events</TableHead></TableRow></TableHeader><TableBody>{[calibration.data.overall, calibration.data.calibration, calibration.data.holdout].map((split) => <TableRow key={split.name}><TableCell className="text-xs">{humanizeCode(split.name)}</TableCell><TableCell className="font-mono text-xs">{split.flagged_sessions}</TableCell><TableCell className="font-mono text-xs">{split.benign_flagged_sessions}</TableCell><TableCell className="font-mono text-xs">{split.flagged_events}/{split.events}</TableCell></TableRow>)}</TableBody></Table></div>
              <div className="space-y-3"><div><h3 className="text-[11px] font-semibold uppercase tracking-wider text-muted-foreground">Methodology</h3><ul className="mt-2 space-y-1.5">{calibration.data.methodology?.map((item) => <li key={item} className="text-xs leading-5 text-muted-foreground">{item}</li>)}</ul></div><div><h3 className="text-[11px] font-semibold uppercase tracking-wider text-muted-foreground">Limitations</h3><ul className="mt-2 space-y-1.5">{calibration.data.limitations?.map((item) => <li key={item} className="text-xs leading-5 text-signal-restricted">{item}</li>)}</ul></div></div>
            </div>
          </CardContent>
        ) : null}
      </Card>

      {scenarios.data?.limitations?.length ? <InfoNote tone="info" title="Scenario limitations">{scenarios.data.limitations.join(" ")}</InfoNote> : null}

      <ConfirmDialog
        open={confirmOpen}
        onOpenChange={(next) => { if (!next && !drill.isPending) setConfirmOpen(false); }}
        title="Run synthetic account-takeover drill?"
        description="This creates synthetic sessions, canaries, an incident and evidence records in this tenant. It does not move real money. Confirm that this non-production environment is appropriate for the drill."
        confirmLabel={drill.isPending ? "Running drill…" : "Run drill once"}
        onConfirm={() => drill.mutate()}
        pending={drill.isPending}
      >
        <div className="space-y-2 text-sm">
          <p className="font-medium">{scenario?.name}</p>
          <p className="text-xs leading-5 text-muted-foreground">The request will be submitted once. No automatic retry is performed. A server rejection, including production disablement, is shown as an error and is not replaced with demo data.</p>
          {drill.isPending ? <p className="flex items-center gap-2 text-xs text-muted-foreground"><Loader2 className="h-3.5 w-3.5 animate-spin" /> Waiting for the authoritative result…</p> : null}
        </div>
      </ConfirmDialog>
    </div>
  );
}
