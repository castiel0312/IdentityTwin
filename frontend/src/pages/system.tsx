import { useQuery } from "@tanstack/react-query";
import { AlertTriangle, CheckCircle2, Database, KeyRound, LockKeyhole, RefreshCw, Server, XCircle } from "lucide-react";
import { StatusBadge } from "@/components/common/badges";
import { DataField } from "@/components/common/data-field";
import { ErrorState } from "@/components/common/error-state";
import { InfoNote } from "@/components/common/info-note";
import { DetailLoading } from "@/components/common/loading-state";
import { PageHeader } from "@/components/common/page-header";
import { Badge } from "@/components/ui/badge";
import { Button } from "@/components/ui/button";
import { Card, CardContent, CardDescription, CardHeader, CardTitle } from "@/components/ui/card";
import { Table, TableBody, TableCell, TableHead, TableHeader, TableRow } from "@/components/ui/table";
import { api } from "@/lib/api";
import { useAuth } from "@/lib/auth";
import { formatDateTime, humanizeCode } from "@/lib/format";
import { cn } from "@/lib/utils";

export function SystemPage() {
  const { session, signOut } = useAuth();
  const query = useQuery({ queryKey: ["system-context"], queryFn: () => api.systemContext(session!), enabled: Boolean(session) });

  if (query.isLoading) return <DetailLoading />;
  if (query.isError) {
    return (
      <div className="space-y-5">
        <PageHeader eyebrow="System & access" title="Runtime context" description="The backend context could not be loaded. No cached or fabricated authority settings are shown." />
        <InfoNote tone="danger" title="Backend connection unavailable">The console could not reach the system context endpoint. Authentication or network failure is shown as a real failure; the UI does not substitute default thresholds.</InfoNote>
        <ErrorState error={query.error} onRetry={() => void query.refetch()} />
      </div>
    );
  }
  if (!query.data) return null;
  const context = query.data;
  const capabilities = context.capabilities ?? [];
  const available = capabilities.filter((capability) => capability.available).length;
  const development = context.auth.development_only;

  return (
    <div className="space-y-5">
      <PageHeader
        eyebrow="System & access"
        title="Runtime context"
        description="The authoritative environment, authentication mode, provider posture, thresholds and capabilities supplied by the running backend."
        actions={<Button variant="outline" size="sm" onClick={() => void query.refetch()} disabled={query.isFetching}><RefreshCw className={cn("h-3.5 w-3.5", query.isFetching && "animate-spin")} /> Refresh</Button>}
      />

      <div className="grid gap-4 sm:grid-cols-2 xl:grid-cols-4">
        <Card className="p-4"><p className="text-[11px] uppercase tracking-wider text-muted-foreground">Environment</p><p className="mt-1 flex items-center gap-2 text-lg font-semibold"><Server className="h-4 w-4 text-muted-foreground" />{context.environment}</p><p className="text-[10px] text-muted-foreground">{development ? "Non-production auth posture" : "Verify provider and auth controls"}</p></Card>
        <Card className="p-4"><p className="text-[11px] uppercase tracking-wider text-muted-foreground">Principal role</p><p className="mt-1 text-lg font-semibold capitalize">{context.principal.role}</p><p className="truncate text-[10px] text-muted-foreground">{context.principal.username}</p></Card>
        <Card className="p-4"><p className="text-[11px] uppercase tracking-wider text-muted-foreground">Identity provider</p><p className="mt-1 text-lg font-semibold">{context.auth.oidc_configured ? "OIDC configured" : "OIDC not configured"}</p><p className="text-[10px] text-muted-foreground">{humanizeCode(context.auth.mode)}</p></Card>
        <Card className="p-4"><p className="text-[11px] uppercase tracking-wider text-muted-foreground">Capabilities</p><p className="mt-1 text-lg font-semibold">{available} / {capabilities.length}</p><p className="text-[10px] text-muted-foreground">Available in this environment</p></Card>
      </div>

      {development ? (
        <InfoNote tone="warning" title="Development authentication is active">
          This backend is using <span className="font-mono">{context.auth.mode}</span>, which is for local development only. The console keeps the session in tab-scoped <span className="font-mono">sessionStorage</span>, never <span className="font-mono">localStorage</span>. Do not use development credentials in production. {context.auth.limitations?.join(" ")}
        </InfoNote>
      ) : !context.auth.oidc_configured ? (
        <InfoNote tone="warning" title="OIDC is not configured">The current authentication mode is <span className="font-mono">{context.auth.mode}</span>. Production login uses an externally issued bearer token pasted by the operator because the OIDC callback is not implemented. This is a known access limitation.</InfoNote>
      ) : null}

      <div className="grid gap-4 xl:grid-cols-3">
        <div className="space-y-4 xl:col-span-2">
          <Card>
            <CardHeader><CardTitle className="flex items-center gap-2"><KeyRound className="h-4 w-4 text-primary" /> Principal & merchant</CardTitle><CardDescription>Scope is resolved by the backend principal, never by a browser-supplied merchant id.</CardDescription></CardHeader>
            <CardContent className="grid gap-4 sm:grid-cols-2">
              <DataField label="User id" mono>{context.principal.user_id}</DataField>
              <DataField label="Merchant id" mono>{context.principal.merchant_id}</DataField>
              <DataField label="Username">{context.principal.username}</DataField>
              <DataField label="Role"><Badge variant="outline">{context.principal.role}</Badge></DataField>
              <DataField label="Authentication method" mono>{context.principal.auth_method}</DataField>
              <DataField label="Merchant"><span className="flex flex-wrap items-center gap-2">{context.merchant?.name ?? "Merchant unavailable"}<StatusBadge status={context.merchant?.is_active ? "active" : "inactive"} /></span></DataField>
              <DataField label="Merchant slug" mono>{context.merchant?.slug ?? "—"}</DataField>
              <DataField label="Console session">Tab-scoped; bearer not written to localStorage</DataField>
            </CardContent>
          </Card>

          <Card>
            <CardHeader><CardTitle className="flex items-center gap-2"><Database className="h-4 w-4 text-primary" /> Payment provider posture</CardTitle><CardDescription>Provider limitations are server configuration, not UI assumptions.</CardDescription></CardHeader>
            <CardContent className="space-y-4">
              <div className="flex flex-wrap items-center gap-2"><Badge variant={context.provider.sandbox_only ? "warning" : "success"}>{context.provider.sandbox_only ? "Sandbox only" : "Verify production provider"}</Badge><Badge variant={context.provider.webhook_verification_configured ? "success" : "danger"}>{context.provider.webhook_verification_configured ? "Webhook verification configured" : "Webhook verification not configured"}</Badge><span className="font-mono text-xs text-muted-foreground">{context.provider.mode}</span></div>
              {context.provider.notes?.length ? <ul className="space-y-1.5">{context.provider.notes.map((note) => <li key={note} className="flex items-start gap-2 text-xs leading-5 text-muted-foreground"><AlertTriangle className="mt-0.5 h-3.5 w-3.5 shrink-0 text-signal-restricted" />{note}</li>)}</ul> : <p className="text-sm text-muted-foreground">No provider notes provided.</p>}
              <div className="rounded-lg border border-border bg-muted/20 p-3"><p className="text-xs leading-5 text-muted-foreground">Payout execution remains server-authoritative. The console invokes the gateway once and displays its recorded outcome, including rejection, block, decoy and reconciliation states.</p></div>
            </CardContent>
          </Card>

          <Card>
            <CardHeader><CardTitle>Risk runtime configuration</CardTitle><CardDescription>Displayed exactly as the running engine reports it. Documentation may lag runtime configuration.</CardDescription></CardHeader>
            <CardContent className="space-y-4">
              <div className="grid gap-3 sm:grid-cols-3">
                <div className="rounded-lg border border-border p-3"><p className="text-[10px] uppercase tracking-wider text-muted-foreground">Restricted</p><p className="mt-1 font-mono text-lg font-semibold">{context.thresholds.restricted.toFixed(1)}</p></div>
                <div className="rounded-lg border border-border p-3"><p className="text-[10px] uppercase tracking-wider text-muted-foreground">Decoy</p><p className="mt-1 font-mono text-lg font-semibold">{context.thresholds.decoy.toFixed(1)}</p></div>
                <div className="rounded-lg border border-border p-3"><p className="text-[10px] uppercase tracking-wider text-muted-foreground">Isolated</p><p className="mt-1 font-mono text-lg font-semibold">{context.thresholds.isolated.toFixed(1)}</p></div>
              </div>
              <dl className="grid gap-3 text-sm sm:grid-cols-2">
                <DataField label="Baseline score">{context.thresholds.baseline_score.toFixed(1)}</DataField>
                <DataField label="Restricted payout limit">{context.thresholds.restricted_payout_limit.toFixed(2)}</DataField>
                <DataField label="Sequence window">{context.risk.sequence_window_seconds}s</DataField>
                <DataField label="Minimum samples">{context.risk.min_samples}</DataField>
                <DataField label="Provisional factor">{context.risk.provisional_factor}</DataField>
                <DataField label="Decay per event">{context.risk.decay_points_per_event}</DataField>
                <DataField label="Default timezone">{context.risk.default_timezone}</DataField>
                <DataField label="Protected actions"><div className="flex flex-wrap gap-1">{context.risk.protected_actions?.length ? context.risk.protected_actions.map((action) => <span key={action} className="rounded bg-muted px-1.5 py-0.5 font-mono text-[10px]">{action}</span>) : "None"}</div></DataField>
              </dl>
              <details className="rounded-lg border border-border"><summary className="cursor-pointer px-3 py-2 text-xs font-medium">Signal weights ({context.risk.weights?.length ?? 0})</summary><div className="border-t border-border"><Table><TableHeader><TableRow><TableHead>Signal</TableHead><TableHead>Weight</TableHead><TableHead>Description</TableHead></TableRow></TableHeader><TableBody>{context.risk.weights?.map((weight) => <TableRow key={weight.name}><TableCell className="font-mono text-xs">{weight.name}</TableCell><TableCell className="font-mono text-xs">{weight.weight.toFixed(1)}</TableCell><TableCell className="text-xs text-muted-foreground">{weight.description}</TableCell></TableRow>)}</TableBody></Table></div></details>
            </CardContent>
          </Card>
        </div>

        <div className="space-y-4">
          <Card>
            <CardHeader><CardTitle className="flex items-center gap-2"><LockKeyhole className="h-4 w-4 text-primary" /> Access model</CardTitle></CardHeader>
            <CardContent className="space-y-3 text-xs leading-5 text-muted-foreground">
              <p><span className="font-medium text-foreground">Bearer transport.</span> API calls pass the bearer token in the <span className="font-mono">Authorization</span> header. It is not placed in the SSE query string.</p>
              <p><span className="font-medium text-foreground">SSE.</span> The live stream uses authenticated fetch streaming, not a URL credential.</p>
              <p><span className="font-medium text-foreground">Tenant scope.</span> Every read is scoped from the authenticated principal; cross-tenant ids return not found.</p>
              <p><span className="font-medium text-foreground">No production token in localStorage.</span> The console clears auth on sign-out and does not persist tokens in localStorage.</p>
              <Button variant="outline" size="sm" className="w-full" onClick={() => signOut()}>Sign out of this tab</Button>
            </CardContent>
          </Card>

          <Card>
            <CardHeader><CardTitle>Capabilities</CardTitle><CardDescription>Unavailable features are shown honestly, not stubbed in the UI.</CardDescription></CardHeader>
            <CardContent className="space-y-2">
              {capabilities.length ? capabilities.map((capability) => (
                <div key={capability.id} className="rounded-lg border border-border p-3">
                  <div className="flex items-center justify-between gap-2"><p className="text-sm font-medium">{capability.name}</p>{capability.available ? <CheckCircle2 className="h-4 w-4 text-signal-normal" aria-label="Available" /> : <XCircle className="h-4 w-4 text-muted-foreground" aria-label="Unavailable" />}</div>
                  <p className="mt-0.5 text-[11px] leading-5 text-muted-foreground">{capability.detail}</p>
                </div>
              )) : <p className="text-sm text-muted-foreground">No capability projection was returned.</p>}
            </CardContent>
          </Card>

          <Card>
            <CardHeader><CardTitle>Environment limitations</CardTitle></CardHeader>
            <CardContent className="space-y-2">
              {context.auth.limitations?.length ? context.auth.limitations.map((limitation) => <p key={limitation} className="flex items-start gap-2 text-xs leading-5 text-muted-foreground"><AlertTriangle className="mt-0.5 h-3.5 w-3.5 shrink-0 text-signal-restricted" />{limitation}</p>) : <p className="text-sm text-muted-foreground">No auth limitations were reported.</p>}
              <p className="pt-2 text-[11px] text-muted-foreground">Context loaded at {formatDateTime(new Date().toISOString())}.</p>
            </CardContent>
          </Card>
        </div>
      </div>
    </div>
  );
}
