import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { CheckCircle2, Loader2, LockKeyhole, ShieldCheck } from "lucide-react";
import { useState } from "react";
import { toast } from "sonner";
import { ConfirmDialog } from "@/components/common/confirm-dialog";
import { ErrorState } from "@/components/common/error-state";
import { InfoNote } from "@/components/common/info-note";
import { Badge } from "@/components/ui/badge";
import { Button } from "@/components/ui/button";
import { Card, CardContent, CardDescription, CardHeader, CardTitle } from "@/components/ui/card";
import { Label } from "@/components/ui/label";
import { Textarea } from "@/components/ui/textarea";
import { api, ApiError, type Schema } from "@/lib/api";
import { useAuth } from "@/lib/auth";
import { humanizeCode, titleCase } from "@/lib/format";

type ActionAvailability = Schema<"IncidentActionAvailability">;

export function IncidentActions({ incidentId }: { incidentId: string }) {
  const { session } = useAuth();
  const queryClient = useQueryClient();
  const [selected, setSelected] = useState<ActionAvailability | null>(null);
  const [notes, setNotes] = useState("");
  const [reason, setReason] = useState("");
  const [error, setError] = useState<string | null>(null);

  const query = useQuery({
    queryKey: ["incident-actions", incidentId],
    queryFn: () => api.incidentActions(session!, incidentId),
    enabled: Boolean(session && incidentId),
  });

  const mutation = useMutation({
    mutationFn: async (action: ActionAvailability) => {
      const body = { notes: notes || null, resolution_reason: reason || null };
      if (action.action === "approve") return api.approveIncident(session!, incidentId, body);
      if (action.action === "resolve") return api.resolveIncident(session!, incidentId, body);
      if (action.action === "approve_revocation") return api.approveRevocation(session!, incidentId, body);
      throw new Error(`Unsupported incident action: ${action.action}`);
    },
    onSuccess: (response) => {
      toast.success(response.message);
      setSelected(null);
      setNotes("");
      setReason("");
      void queryClient.invalidateQueries({ queryKey: ["incident", incidentId] });
      void queryClient.invalidateQueries({ queryKey: ["incident-actions", incidentId] });
      void queryClient.invalidateQueries({ queryKey: ["incident-timeline", incidentId] });
      void queryClient.invalidateQueries({ queryKey: ["incidents"] });
      void queryClient.invalidateQueries({ queryKey: ["analytics-overview"] });
    },
    onError: (cause) => setError(cause instanceof ApiError ? `${cause.code}: ${cause.message}` : cause instanceof Error ? cause.message : "The action failed."),
  });

  if (query.isLoading) return <Card><CardContent className="p-5"><div className="h-24 animate-pulse rounded bg-muted" /></CardContent></Card>;
  if (query.isError) return <ErrorState error={query.error} onRetry={() => void query.refetch()} />;
  if (!query.data) return null;

  const actions = query.data.actions ?? [];
  const available = actions.filter((action) => action.allowed);
  const denied = actions.filter((action) => !action.allowed);

  return (
    <>
      <Card>
        <CardHeader>
          <CardTitle className="flex items-center gap-2"><ShieldCheck className="h-4 w-4 text-primary" /> Authorization-aware actions</CardTitle>
          <CardDescription>
            These capabilities come from the server for principal role <span className="font-medium">{query.data.principal_role}</span>.
          </CardDescription>
        </CardHeader>
        <CardContent className="space-y-3">
          {available.length === 0 ? (
            <div className="rounded-lg border border-dashed border-border p-4">
              <p className="flex items-center gap-2 text-sm font-medium"><LockKeyhole className="h-4 w-4 text-muted-foreground" /> No actions available</p>
              <p className="mt-1 text-xs text-muted-foreground">This status, role or tenant scope does not permit an incident action. The backend remains the enforcement point.</p>
            </div>
          ) : available.map((action) => (
            <div key={action.action} className="flex flex-col gap-2 rounded-lg border border-border p-3 sm:flex-row sm:items-center sm:justify-between">
              <div><p className="text-sm font-medium">{action.label}</p><p className="text-[11px] text-muted-foreground">{humanizeCode(action.action)} · roles: {(action.required_roles ?? []).join(", ") || "server policy"}</p></div>
              <Button size="sm" variant={action.destructive ? "destructive" : "default"} onClick={() => { setSelected(action); setError(null); }}>{action.label}</Button>
            </div>
          ))}
          {denied.length ? (
            <details className="rounded-lg border border-border bg-muted/20 p-3">
              <summary className="cursor-pointer text-xs font-medium text-muted-foreground">Unavailable actions ({denied.length})</summary>
              <ul className="mt-2 space-y-2">
                {denied.map((action) => (
                  <li key={action.action} className="text-xs"><span className="font-medium">{action.label}</span> <Badge variant="muted" className="ml-1">{(action.required_roles ?? []).join("/") || "restricted"}</Badge><p className="mt-0.5 text-muted-foreground">{action.reason ?? "Not permitted for this principal."}</p></li>
                ))}
              </ul>
            </details>
          ) : null}
          <p className="text-[11px] leading-5 text-muted-foreground">Approval records an analyst decision only. It does not execute payouts, re-enable sessions or reverse containment.</p>
        </CardContent>
      </Card>

      <ConfirmDialog
        open={Boolean(selected)}
        onOpenChange={(open) => { if (!open && !mutation.isPending) { setSelected(null); setError(null); } }}
        title={selected?.label ?? "Confirm incident action"}
        description={selected?.label === "Approve revocation" ? "This records confirmation of permanent session revocation. It cannot re-enable the session." : "The backend will validate your role, tenant scope and current incident status before recording this action."}
        confirmLabel={mutation.isPending ? "Recording…" : "Record action"}
        onConfirm={() => { if (selected) { setError(null); mutation.mutate(selected); } }}
        pending={mutation.isPending}
        destructive={Boolean(selected?.destructive)}
      >
        <div className="space-y-3">
          <div className="space-y-2"><Label htmlFor="incident-notes">Analyst notes</Label><Textarea id="incident-notes" value={notes} onChange={(e) => setNotes(e.target.value)} maxLength={500} rows={3} placeholder="Evidence reviewed, rationale, follow-up…" /></div>
          <div className="space-y-2"><Label htmlFor="incident-reason">Resolution reason (optional)</Label><Textarea id="incident-reason" value={reason} onChange={(e) => setReason(e.target.value)} maxLength={255} rows={2} placeholder="Structured reason code or short tag" /></div>
          {selected ? <InfoNote tone="warning" title={`${titleCase(selected.action)} is attributable`}>The action is recorded against your principal and appears in the incident audit trail.</InfoNote> : null}
          {error ? <p role="alert" className="text-xs text-destructive">{error}</p> : null}
          {mutation.isPending ? <p className="flex items-center gap-2 text-xs text-muted-foreground"><Loader2 className="h-3.5 w-3.5 animate-spin" /> Waiting for the authoritative response.</p> : null}
          {mutation.isSuccess ? <p className="flex items-center gap-2 text-xs text-signal-normal"><CheckCircle2 className="h-3.5 w-3.5" /> Action recorded.</p> : null}
        </div>
      </ConfirmDialog>
    </>
  );
}
