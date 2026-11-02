import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { render, screen } from "@testing-library/react";
import { describe, expect, it, vi } from "vitest";
import { AiInvestigator } from "@/features/incidents/ai-investigator";
import { api, ApiError, type Schema } from "@/lib/api";
import { AuthProvider } from "@/lib/auth";

const STORAGE_KEY = "identitytwin.console.session.v1";
const incidentId = "66666666-6666-6666-6666-666666666666";
const merchantId = "00000000-0000-0000-0000-000000000001";
const altMerchantId = "00000000-0000-0000-0000-000000000099";

function sessionFor(role: "merchant" | "analyst", merchant = merchantId) {
  return {
    token: role === "analyst" ? "dev-analyst-token" : "dev-merchant-token",
    label: `${role}-dev@identitytwin.local`,
    role,
    developmentOnly: true,
    devHeaders: {
      "X-Dev-Role": role,
      "X-Dev-Merchant-Id": merchant,
      "X-Dev-User-Id":
        role === "analyst"
          ? "00000000-0000-0000-0000-000000000002"
          : "11111111-1111-1111-1111-111111111111",
    },
  };
}

function renderFor(role: "merchant" | "analyst", merchant = merchantId) {
  window.sessionStorage.setItem(STORAGE_KEY, JSON.stringify(sessionFor(role, merchant)));
  const client = new QueryClient({ defaultOptions: { queries: { retry: false } } });
  return render(
    <QueryClientProvider client={client}>
      <AuthProvider>
        <AiInvestigator incidentId={incidentId} />
      </AuthProvider>
    </QueryClientProvider>,
  );
}

function investigation(
  overrides: Partial<Schema<"InvestigationResponse">> = {},
): Schema<"InvestigationResponse"> {
  return {
    investigation_id: "77777777-7777-7777-7777-777777777777",
    incident_id: incidentId,
    session_id: "88888888-8888-8888-8888-888888888888",
    merchant_id: merchantId,
    status: "COMPLETE",
    ai_used: false,
    model_name: null,
    created_by: "00000000-0000-0000-0000-000000000002",
    created_at: "2026-11-02T19:00:00Z",
    updated_at: "2026-11-02T19:00:00Z",
    bundle: {
      incident_id: incidentId,
      session_id: "88888888-8888-8888-8888-888888888888",
      merchant_id: merchantId,
      focus: null,
      risk_score: 96,
      trust_level: "ISOLATED",
      trigger_reason: "NEW_PAYEE_LARGE_PAYOUT",
      incident_status: "OPEN",
      evidence_counts: {},
      findings: [],
      evidence: [],
      recommendations: [
        {
          action: "Preserve containment.",
          rationale: "The gateway remains authoritative.",
          priority: "HIGH",
          advisory_only: true,
          requires_human_approval: true,
        },
      ],
      narrative: {
        headline: "New payee at 03:00",
        summary: "A new payee and large payout were recorded.",
        why_suspicious: "The deterministic evidence records a new payee.",
        uncertainty_notes: ["Advisory only."],
        generated_by: "deterministic",
      },
      redaction_applied: true,
      ai_used: false,
      model_name: null,
      limitations: [],
    },
    ...overrides,
  } as Schema<"InvestigationResponse">;
}

describe("AiInvestigator", () => {
  it("lets an analyst run an investigation and shows the empty state", async () => {
    const list = vi.spyOn(api, "listIncidentInvestigations").mockResolvedValue({
      items: [],
      total: 0,
      page: 1,
      page_size: 25,
    } as Schema<"InvestigationListResponse">);

    renderFor("analyst");

    expect(await screen.findByText(/No investigation has been run/)).toBeInTheDocument();
    expect(screen.getByRole("button", { name: "Run investigation" })).toBeEnabled();
    expect(list).toHaveBeenCalledWith(
      expect.objectContaining({
        devHeaders: expect.objectContaining({ "X-Dev-Role": "analyst" }),
      }),
      incidentId,
    );
  });

  it("hides the run action from merchants and explains analyst access", async () => {
    vi.spyOn(api, "listIncidentInvestigations").mockResolvedValue({
      items: [],
      total: 0,
      page: 1,
      page_size: 25,
    } as Schema<"InvestigationListResponse">);

    renderFor("merchant");

    expect(await screen.findByText(/Analyst access is required/)).toBeInTheDocument();
    expect(screen.queryByRole("button", { name: "Run investigation" })).not.toBeInTheDocument();
  });

  it("renders a loading state", async () => {
    vi.spyOn(api, "listIncidentInvestigations").mockReturnValue(
      new Promise(() => undefined),
    );

    renderFor("analyst");

    expect(await screen.findByRole("status", { name: "Loading investigation" })).toBeInTheDocument();
  });

  it("renders an error state with a retry action", async () => {
    vi.spyOn(api, "listIncidentInvestigations").mockRejectedValue(
      new ApiError(500, "INTERNAL_ERROR", "Investigation lookup failed."),
    );

    renderFor("analyst");

    expect(await screen.findByRole("alert")).toBeInTheDocument();
    expect(screen.getByText("Investigation lookup failed.")).toBeInTheDocument();
    expect(screen.getByRole("button", { name: "Retry request" })).toBeInTheDocument();
  });

  it("renders the fallback status and deterministic narrative", async () => {
    vi.spyOn(api, "listIncidentInvestigations").mockResolvedValue({
      items: [
        investigation({
          status: "FALLBACK",
          ai_used: false,
        }),
      ],
      total: 1,
      page: 1,
      page_size: 25,
    } as Schema<"InvestigationListResponse">);

    renderFor("analyst");

    expect(await screen.findByText("FALLBACK")).toBeInTheDocument();
    expect(screen.getByText("Deterministic narrative")).toBeInTheDocument();
    expect(screen.getByText("New payee at 03:00")).toBeInTheDocument();
  });

  it("uses the merchant-scoped session for rendering", async () => {
    const list = vi
      .spyOn(api, "listIncidentInvestigations")
      .mockResolvedValue({
        items: [investigation({ merchant_id: altMerchantId })],
        total: 1,
        page: 1,
        page_size: 25,
      } as Schema<"InvestigationListResponse">);

    renderFor("merchant", altMerchantId);

    expect(await screen.findByText("New payee at 03:00")).toBeInTheDocument();
    expect(list).toHaveBeenCalledWith(
      expect.objectContaining({
        devHeaders: expect.objectContaining({ "X-Dev-Merchant-Id": altMerchantId }),
      }),
      incidentId,
    );
  });
});
