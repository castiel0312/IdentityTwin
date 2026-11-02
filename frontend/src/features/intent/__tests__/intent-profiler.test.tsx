import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { render, screen } from "@testing-library/react";
import { describe, expect, it, vi } from "vitest";
import { IntentProfiler } from "@/features/intent/intent-profiler";
import { api, ApiError, type Schema } from "@/lib/api";
import { AuthProvider } from "@/lib/auth";

const STORAGE_KEY = "identitytwin.console.session.v1";
const sessionId = "88888888-8888-8888-8888-888888888888";
const merchantId = "00000000-0000-0000-0000-000000000001";

function sessionFor(role: "merchant" | "analyst") {
  return {
    token: role === "analyst" ? "dev-analyst-token" : "dev-merchant-token",
    label: `${role}-dev@identitytwin.local`,
    role,
    developmentOnly: true,
    devHeaders: {
      "X-Dev-Role": role,
      "X-Dev-Merchant-Id": merchantId,
      "X-Dev-User-Id":
        role === "analyst"
          ? "00000000-0000-0000-0000-000000000002"
          : "11111111-1111-1111-1111-111111111111",
    },
  };
}

function renderFor(role: "merchant" | "analyst") {
  window.sessionStorage.setItem(STORAGE_KEY, JSON.stringify(sessionFor(role)));
  const client = new QueryClient({ defaultOptions: { queries: { retry: false } } });
  return render(
    <QueryClientProvider client={client}>
      <AuthProvider>
        <IntentProfiler sessionId={sessionId} />
      </AuthProvider>
    </QueryClientProvider>,
  );
}

function intentProfile(
  overrides: Partial<Schema<"IntentProfileResponse">> = {},
): Schema<"IntentProfileResponse"> {
  return {
    profile_id: "99999999-9999-9999-9999-999999999999",
    session_id: sessionId,
    merchant_id: merchantId,
    status: "COMPLETE",
    ai_used: false,
    model_name: null,
    created_by: "00000000-0000-0000-0000-000000000002",
    created_at: "2026-11-02T19:00:00Z",
    updated_at: "2026-11-02T19:00:00Z",
    bundle: {
      session_id: sessionId,
      merchant_id: merchantId,
      analysis: {
        primary_intent: "SUSPECTED_PAYEE_REDIRECTION",
        secondary_intents: ["SUSPECTED_VELOCITY_ABUSE"],
        confidence: "MEDIUM",
        confidence_basis: ["HIGH_SPECIFICITY_SEQUENCE"],
        evidence: [
          {
            source: "event",
            ref_id: "event-1",
            summary: "A payee registration preceded a payout inside the window.",
            occurred_at: "2026-11-02T18:50:00Z",
            signal_codes: ["PAYEE_ADD_THEN_PAYOUT"],
          },
        ],
        limitations: ["Absence of an anomaly is not proof of benign activity."],
        abstention_reason: null,
        signals: {},
        advisory_only: true,
        requires_human_approval: true,
        classifier_version: "intent-classifier-v1",
      },
      narrative: {
        headline: "Advisory hypothesis: Payee Redirection",
        summary: "The deterministic classifier selected payee redirection.",
        uncertainty_notes: ["Evidence is bounded."],
        generated_by: "deterministic",
      },
      redaction_applied: true,
      ai_used: false,
      model_name: null,
    },
    ...overrides,
  } as unknown as Schema<"IntentProfileResponse">;
}

describe("IntentProfiler", () => {
  it("lets an analyst create a profile and shows the empty state", async () => {
    const list = vi.spyOn(api, "listSessionIntentProfiles").mockResolvedValue({
      items: [],
      total: 0,
      page: 1,
      page_size: 25,
    } as Schema<"IntentProfileListResponse">);

    renderFor("analyst");

    expect(await screen.findByText(/No intent profile has been recorded/)).toBeInTheDocument();
    expect(screen.getByRole("button", { name: "Run intent profile" })).toBeEnabled();
    expect(list).toHaveBeenCalledWith(
      expect.objectContaining({
        devHeaders: expect.objectContaining({ "X-Dev-Role": "analyst" }),
      }),
      sessionId,
    );
  });

  it("hides creation from merchants", async () => {
    vi.spyOn(api, "listSessionIntentProfiles").mockResolvedValue({
      items: [],
      total: 0,
      page: 1,
      page_size: 25,
    } as Schema<"IntentProfileListResponse">);

    renderFor("merchant");

    expect(await screen.findByText(/Analyst access is required/)).toBeInTheDocument();
    expect(
      screen.queryByRole("button", { name: "Run intent profile" }),
    ).not.toBeInTheDocument();
  });

  it("renders a loading state", async () => {
    vi.spyOn(api, "listSessionIntentProfiles").mockReturnValue(new Promise(() => undefined));

    renderFor("analyst");

    expect(
      await screen.findByRole("status", { name: "Loading intent profile" }),
    ).toBeInTheDocument();
  });

  it("renders an error state with retry", async () => {
    vi.spyOn(api, "listSessionIntentProfiles").mockRejectedValue(
      new ApiError(500, "INTERNAL_ERROR", "Intent profile lookup failed."),
    );

    renderFor("analyst");

    expect(await screen.findByRole("alert")).toBeInTheDocument();
    expect(screen.getByText("Intent profile lookup failed.")).toBeInTheDocument();
    expect(screen.getByRole("button", { name: "Retry request" })).toBeInTheDocument();
  });

  it("renders confidence, evidence, limitations, fallback and advisory-only status", async () => {
    vi.spyOn(api, "listSessionIntentProfiles").mockResolvedValue({
      items: [intentProfile({ status: "FALLBACK" })],
      total: 1,
      page: 1,
      page_size: 25,
    } as Schema<"IntentProfileListResponse">);

    renderFor("analyst");

    expect(await screen.findByText("Suspected payee redirection")).toBeInTheDocument();
    expect(screen.getByText("MEDIUM confidence")).toBeInTheDocument();
    expect(screen.getByText("FALLBACK")).toBeInTheDocument();
    expect(screen.getByText("Deterministic narrative")).toBeInTheDocument();
    expect(
      screen.getByText("A payee registration preceded a payout inside the window."),
    ).toBeInTheDocument();
    expect(screen.getByText(/Absence of an anomaly/)).toBeInTheDocument();
    expect(screen.getByText("Advisory only")).toBeInTheDocument();
  });
});
