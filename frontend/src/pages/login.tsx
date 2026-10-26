import { useMutation } from "@tanstack/react-query";
import {
  AlertTriangle,
  ArrowRight,
  Eye,
  EyeOff,
  KeyRound,
  Loader2,
  LockKeyhole,
  ShieldCheck,
  Sparkles,
} from "lucide-react";
import { useState } from "react";
import { Navigate, useLocation, useNavigate } from "react-router-dom";
import { Badge } from "@/components/ui/badge";
import { Button } from "@/components/ui/button";
import { Input } from "@/components/ui/input";
import { Label } from "@/components/ui/label";
import { ApiError } from "@/lib/api";
import { DEV_PERSONAS, useAuth, type DevPersonaId } from "@/lib/auth";
import { cn } from "@/lib/utils";

export function LoginPage() {
  const { session, signInWithPersona, signInWithToken } = useAuth();
  const navigate = useNavigate();
  const location = useLocation();
  const from = (location.state as { from?: string } | null)?.from ?? "/";
  const [token, setToken] = useState("");
  const [showToken, setShowToken] = useState(false);
  const [selectedPersona, setSelectedPersona] = useState<DevPersonaId | null>(null);
  const [error, setError] = useState<string | null>(null);

  const personaMutation = useMutation({
    mutationFn: async (id: DevPersonaId) => {
      setSelectedPersona(id);
      await signInWithPersona(id);
    },
    onSuccess: () => navigate(from, { replace: true }),
    onError: (cause) => {
      setSelectedPersona(null);
      setError(cause instanceof ApiError ? cause.message : cause instanceof Error ? cause.message : "Sign-in failed.");
    },
  });

  const tokenMutation = useMutation({
    mutationFn: () => signInWithToken(token),
    onSuccess: () => navigate(from, { replace: true }),
    onError: (cause) => {
      setError(cause instanceof ApiError ? cause.message : cause instanceof Error ? cause.message : "Sign-in failed.");
    },
  });

  if (session) return <Navigate to={from} replace />;

  const pending = personaMutation.isPending || tokenMutation.isPending;

  return (
    <div className="grid min-h-screen lg:grid-cols-[1.08fr_1fr]">
      <section className="relative hidden overflow-hidden bg-[#0B0C0D] p-12 lg:flex lg:flex-col lg:justify-between xl:p-16">
        <div className="absolute inset-0 bg-grid opacity-[0.06]" aria-hidden="true" />
        <div
          className="pointer-events-none absolute -right-40 top-24 h-[34rem] w-[34rem] rounded-full border border-white/[0.07]"
          aria-hidden="true"
        />
        <div
          className="pointer-events-none absolute -right-24 top-40 h-[24rem] w-[24rem] rounded-full border border-primary/25"
          aria-hidden="true"
        />
        <div
          className="pointer-events-none absolute -right-4 top-56 h-14 w-14 rounded-full bg-primary/90 blur-[1px]"
          aria-hidden="true"
        />
        <div className="pointer-events-none absolute -bottom-56 left-1/4 h-[30rem] w-[30rem] rounded-full bg-mint/[0.035] blur-3xl" aria-hidden="true" />

        <div className="relative flex items-center gap-3">
          <div className="relative flex h-11 w-11 items-center justify-center rounded-full border border-primary/40 bg-primary">
            <span className="font-mono text-sm font-bold text-primary-foreground">IT</span>
            <span className="absolute -bottom-0.5 -right-0.5 h-3 w-3 rounded-full border-2 border-[#0B0C0D] bg-mint" aria-hidden="true" />
          </div>
          <div>
            <p className="text-lg font-medium tracking-tight text-[#E7F0EF]">IdentityTwin</p>
            <p className="text-2xs font-semibold uppercase tracking-[0.22em] text-[#929B9A]">Trust Operations Console</p>
          </div>
        </div>

        <div className="relative max-w-2xl space-y-8 py-12">
          <p className="flex items-center gap-2.5 text-2xs font-semibold uppercase tracking-[0.26em] text-mint-muted">
            <span className="h-px w-8 bg-primary" aria-hidden="true" />
            Behavioural trust · Evidence integrity
          </p>
          <h1 className="text-balance text-5xl font-light leading-[0.95] tracking-[-0.045em] text-[#E7F0EF] xl:text-[4.4rem]">
            Every payout.
            <br />
            Accountable
            <br />
            <span className="text-primary">by design.</span>
          </h1>
          <p className="max-w-lg text-[0.9375rem] leading-7 text-[#929B9A]">
            Operate the gateway, investigate identity drift, contain canary interactions and verify evidence seals — without
            the console ever re-implementing the risk engine.
          </p>
          <dl className="grid max-w-xl grid-cols-2 gap-px overflow-hidden rounded-2xl border border-white/[0.08] bg-white/[0.06]">
            {[
              ["Server-authoritative", "Risk scoring, routing and payout execution stay in FastAPI."],
              ["Tenant-scoped", "Every projection is derived from the authenticated principal."],
              ["Evidence-aware", "Seal checks state precisely what they prove — and what they do not."],
              ["Honest failure", "No fabricated demo fallback when the API is disconnected."],
            ].map(([title, detail]) => (
              <div key={title} className="bg-[#0E1011] p-4 xl:p-5">
                <dt className="text-xs font-medium text-[#E7F0EF]">{title}</dt>
                <dd className="mt-1.5 text-[11px] leading-5 text-[#929B9A]">{detail}</dd>
              </div>
            ))}
          </dl>
        </div>

        <div className="relative flex items-center justify-between gap-4 border-t border-white/[0.08] pt-5">
          <p className="font-mono text-2xs uppercase tracking-[0.16em] text-[#5E6767]">IdentityTwin · Trust Gateway operations</p>
          <p className="font-mono text-2xs uppercase tracking-[0.16em] text-[#5E6767]">v1 console</p>
        </div>
      </section>

      <section className="relative flex items-center justify-center overflow-hidden bg-mint px-5 py-10 text-background sm:px-8 lg:py-14">
        <div
          className="pointer-events-none absolute -right-24 -top-24 h-72 w-72 rounded-full border border-[#0B0C0D]/10"
          aria-hidden="true"
        />
        <div
          className="pointer-events-none absolute -left-20 bottom-0 h-56 w-56 rounded-full border border-[#0B0C0D]/10"
          aria-hidden="true"
        />
        <div className="relative w-full max-w-md space-y-6">
          <div className="space-y-2 lg:hidden">
            <div className="flex items-center gap-2.5">
              <div className="relative flex h-9 w-9 items-center justify-center rounded-full bg-[#0B0C0D]">
                <span className="font-mono text-[11px] font-bold text-mint">IT</span>
                <span className="absolute -bottom-0.5 -right-0.5 h-2.5 w-2.5 rounded-full border-2 border-mint bg-primary" aria-hidden="true" />
              </div>
              <div>
                <p className="text-base font-medium tracking-tight text-background">IdentityTwin</p>
                <p className="text-[9px] font-semibold uppercase tracking-[0.2em] text-background/55">Trust operations console</p>
              </div>
            </div>
          </div>

          <div className="space-y-2">
            <p className="text-2xs font-semibold uppercase tracking-[0.2em] text-background/50">Secure access</p>
            <h2 className="text-balance text-3xl font-light tracking-[-0.035em] text-background">Sign in to the console</h2>
            <p className="text-sm leading-6 text-background/60">
              Authentication is resolved by the backend. The console never accepts a merchant identity from the client.
            </p>
          </div>

          {import.meta.env.DEV ? (
            <div className="space-y-3 rounded-2xl border border-background/15 bg-white/30 p-4">
              <div className="flex items-center gap-2">
                <AlertTriangle className="h-4 w-4 text-[#8A4400]" aria-hidden="true" />
                <p className="text-2xs font-semibold uppercase tracking-[0.16em] text-[#8A4400]">Development-only personas</p>
              </div>
              <p className="text-xs leading-5 text-background/60">
                These well-known tokens are accepted only by a development backend. They are tab-scoped and must never be used
                in production.
              </p>
              <div className="grid gap-2">
                {DEV_PERSONAS.map((persona) => (
                  <button
                    key={persona.id}
                    type="button"
                    className="group flex h-auto w-full items-center justify-between gap-3 rounded-xl border border-background/15 bg-white/35 px-3.5 py-3 text-left text-background transition-colors duration-200 hover:border-background/30 hover:bg-white/60 focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-background/40 focus-visible:ring-offset-2 focus-visible:ring-offset-mint disabled:pointer-events-none disabled:opacity-50"
                    onClick={() => {
                      setError(null);
                      personaMutation.mutate(persona.id);
                    }}
                    disabled={pending}
                    aria-busy={selectedPersona === persona.id && personaMutation.isPending}
                  >
                    <span className="min-w-0">
                      <span className="block text-sm font-medium">{persona.label}</span>
                      <span className="mt-0.5 block truncate text-[11px] text-background/55">{persona.description}</span>
                    </span>
                    {selectedPersona === persona.id && personaMutation.isPending ? (
                      <Loader2 className="h-4 w-4 shrink-0 animate-spin" aria-hidden="true" />
                    ) : (
                      <ArrowRight
                        className="h-4 w-4 shrink-0 text-background/45 transition-transform duration-200 group-hover:translate-x-0.5"
                        aria-hidden="true"
                      />
                    )}
                  </button>
                ))}
              </div>
            </div>
          ) : null}

          <form
            className="space-y-4 rounded-2xl border border-background/15 bg-white/30 p-5"
            onSubmit={(event) => {
              event.preventDefault();
              setError(null);
              tokenMutation.mutate();
            }}
          >
            <div className="flex items-center gap-2">
              <KeyRound className="h-4 w-4 text-background/55" aria-hidden="true" />
              <h3 className="text-sm font-medium text-background">Bearer access token</h3>
            </div>
            <div className="space-y-2">
              <Label htmlFor="access-token" className="text-background/60">
                Access token
              </Label>
              <div className="relative">
                <Input
                  id="access-token"
                  type={showToken ? "text" : "password"}
                  autoComplete="off"
                  spellCheck={false}
                  value={token}
                  onChange={(event) => setToken(event.target.value)}
                  placeholder="Paste a backend-issued bearer token"
                  className="border-background/20 bg-white/55 font-mono text-xs text-background shadow-none placeholder:text-background/40 hover:border-background/35 focus-visible:border-background/60 focus-visible:ring-background/30"
                  aria-describedby="token-help"
                />
                <button
                  type="button"
                  className="absolute right-1.5 top-1/2 -translate-y-1/2 rounded-full p-1.5 text-background/55 transition-colors hover:bg-background/10 hover:text-background focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-background/40"
                  onClick={() => setShowToken((value) => !value)}
                  aria-label={showToken ? "Hide token" : "Show token"}
                >
                  {showToken ? <EyeOff className="h-4 w-4" /> : <Eye className="h-4 w-4" />}
                </button>
              </div>
              <p id="token-help" className="text-[11px] leading-5 text-background/55">
                Held in this tab&apos;s session storage only — never in localStorage. Closing the tab clears it.
              </p>
            </div>
            <Button
              type="submit"
              className="w-full bg-background text-mint hover:bg-[#1B1E1F] focus-visible:ring-background/40 focus-visible:ring-offset-mint"
              disabled={pending || !token.trim()}
            >
              {tokenMutation.isPending ? (
                <Loader2 className="h-4 w-4 animate-spin" aria-hidden="true" />
              ) : (
                <LockKeyhole className="h-4 w-4" aria-hidden="true" />
              )}
              Verify and enter console
            </Button>
            {!import.meta.env.DEV ? (
              <p className="flex gap-2 rounded-xl bg-background/[0.055] p-3 text-[11px] leading-5 text-background/60">
                <ShieldCheck className="mt-0.5 h-3.5 w-3.5 shrink-0" aria-hidden="true" />
                OIDC not configured. Use a token issued for this environment; production OIDC is a documented gap.
              </p>
            ) : null}
          </form>

          {error ? (
            <div
              role="alert"
              className={cn(
                "flex gap-2.5 rounded-xl border border-[#8C1D0E]/25 bg-[#8C1D0E]/10 p-3.5 text-sm text-[#7A190C]",
              )}
            >
              <AlertTriangle className="mt-0.5 h-4 w-4 shrink-0" aria-hidden="true" />
              <span>{error}</span>
            </div>
          ) : null}

          <p className="flex items-start gap-2 text-[11px] leading-5 text-background/55">
            <Sparkles className="mt-0.5 h-3.5 w-3.5 shrink-0" aria-hidden="true" />
            The risk engine, payout policy and evidence chain remain the authoritative source. This console is a read and
            action surface only.
          </p>

          <div className="flex items-center justify-between gap-3 border-t border-background/15 pt-4">
            <Badge variant="outline" className="border-background/20 bg-white/25 text-background/60">
              Session-scoped
            </Badge>
            <p className="font-mono text-2xs uppercase tracking-[0.14em] text-background/40">No localStorage · No demo fallback</p>
          </div>
        </div>
      </section>
    </div>
  );
}
