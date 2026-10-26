import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { render, screen } from "@testing-library/react";
import { describe, expect, it, vi } from "vitest";
import { IncidentActions } from "@/features/incidents/incident-actions";
import { api } from "@/lib/api";
import { AuthProvider } from "@/lib/auth";
import type { Schema } from "@/lib/api";

const STORAGE_KEY = "identitytwin.console.session.v1";
const incidentId = "66666666-6666-6666-6666-666666666666";

function renderWithAnalyst() {
  window.sessionStorage.setItem(
    STORAGE_KEY,
    JSON.stringify({
      token: "dev-analyst-token",
      label: "analyst-dev@identitytwin.local",
      role: "analyst",
      developmentOnly: true,
      devHeaders: {
        "X-Dev-Role": "analyst",
        "X-Dev-Merchant-Id": "00000000-0000-0000-0000-000000000001",
        "X-Dev-User-Id": "00000000-0000-0000-0000-000000000002",
      },
    }),
  );
  const client = new QueryClient({ defaultOptions: { queries: { retry: false } } });
  return render(
    <QueryClientProvider client={client}>
      <AuthProvider>
        <IncidentActions incidentId={incidentId} />
      </AuthProvider>
    </QueryClientProvider>,
  );
}

describe("IncidentActions", () => {
  it("renders only server-authorized actions and explains denied capabilities", async () => {
    vi.spyOn(api, "incidentActions").mockResolvedValue({
      incident_id: incidentId,
      principal_role: "analyst",
      actions: [
        {
          action: "approve",
          label: "Approve containment",
          allowed: true,
          destructive: false,
          required_roles: ["analyst", "admin"],
          reason: null,
        },
        {
          action: "resolve",
          label: "Resolve incident",
          allowed: false,
          destructive: false,
          required_roles: ["admin"],
          reason: "Only an administrator can resolve this incident.",
        },
      ],
    } as unknown as Schema<"IncidentActionsResponse">);

    renderWithAnalyst();

    expect(await screen.findByRole("button", { name: "Approve containment" })).toBeInTheDocument();
    expect(screen.getByRole("button", { name: "Approve containment" })).toBeEnabled();
    expect(screen.queryByRole("button", { name: "Resolve incident" })).not.toBeInTheDocument();
    expect(screen.getByText("Unavailable actions (1)")).toBeInTheDocument();
    expect(screen.getByText("Only an administrator can resolve this incident.")).toBeInTheDocument();
  });

  it("shows a permission-denied server failure instead of fabricated actions", async () => {
    vi.spyOn(api, "incidentActions").mockRejectedValue(
      new (await import("@/lib/api")).ApiError(403, "FORBIDDEN", "Analyst scope is required."),
    );

    renderWithAnalyst();

    expect(await screen.findByText("Access denied")).toBeInTheDocument();
    expect(screen.getByText("Analyst scope is required.")).toBeInTheDocument();
    expect(screen.queryByRole("button", { name: "Retry request" })).not.toBeInTheDocument();
  });
});
