import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { render, screen, waitFor } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { MemoryRouter } from "react-router-dom";
import { Toaster } from "sonner";
import { describe, expect, it, vi } from "vitest";
import { PayoutDialog } from "@/features/payouts/payout-dialog";
import { api } from "@/lib/api";
import { AuthProvider } from "@/lib/auth";
import type { Schema } from "@/lib/api";

const STORAGE_KEY = "identitytwin.console.session.v1";

function signInForTest() {
  window.sessionStorage.setItem(
    STORAGE_KEY,
    JSON.stringify({
      token: "dev-merchant-token",
      label: "merchant-dev@identitytwin.local",
      role: "merchant",
      developmentOnly: true,
      devHeaders: {
        "X-Dev-Role": "merchant",
        "X-Dev-Merchant-Id": "00000000-0000-0000-0000-000000000001",
        "X-Dev-User-Id": "11111111-1111-1111-1111-111111111111",
      },
    }),
  );
}

function renderDialog() {
  signInForTest();
  const client = new QueryClient({
    defaultOptions: {
      queries: { retry: false },
      mutations: { retry: 3, retryDelay: 50 },
    },
  });
  return render(
    <MemoryRouter>
      <QueryClientProvider client={client}>
        <AuthProvider>
          <PayoutDialog open onOpenChange={() => undefined} />
          <Toaster />
        </AuthProvider>
      </QueryClientProvider>
    </MemoryRouter>,
  );
}

const normalSession = {
  session_id: "22222222-2222-2222-2222-222222222222",
  trust_level: "NORMAL",
  risk_score: 4,
  status: "active",
} as Schema<"SessionResponse">;

const restrictedSession = {
  session_id: "33333333-3333-3333-3333-333333333333",
  trust_level: "RESTRICTED",
  risk_score: 45,
  status: "active",
} as Schema<"SessionResponse">;

describe("PayoutDialog", () => {
  it("submits a consequential payout once and never retries a transport failure", async () => {
    const user = userEvent.setup();
    vi.spyOn(api, "listSessions").mockResolvedValue({
      items: [normalSession],
      total: 1,
      page: 1,
      page_size: 100,
    });
    const execute = vi.spyOn(api, "executePayout").mockRejectedValue(new TypeError("Failed to fetch"));

    renderDialog();

    await user.click(await screen.findByLabelText("Session"));
    await user.click(await screen.findByRole("option", { name: /NORMAL/ }));
    await user.type(screen.getByLabelText("Recipient email"), "beneficiary@example.test");
    await user.type(screen.getByLabelText("Amount"), "125.50");
    await user.click(screen.getByRole("button", { name: /Review payout/ }));

    expect(await screen.findByText("Confirm payout execution")).toBeInTheDocument();
    await user.click(screen.getByRole("button", { name: "Execute once" }));

    await waitFor(() => expect(execute).toHaveBeenCalledTimes(1));
    // The supplied QueryClient retries mutations three times. The payout
    // mutation must override that policy, because an execution may have
    // happened even if the response never arrived.
    await new Promise((resolve) => setTimeout(resolve, 250));
    expect(execute).toHaveBeenCalledTimes(1);

    const [, body] = execute.mock.calls[0] ?? [];
    expect(body).toMatchObject({
      session_id: normalSession.session_id,
      recipient_email: "beneficiary@example.test",
      amount: 125.5,
      currency: "USD",
    });
    expect(body?.idempotency_key).toMatch(/^payout-/);
    expect(body?.step_up_token).toBeNull();
  });

  it("requires a verified single-use step-up token for a restricted payout", async () => {
    const user = userEvent.setup();
    vi.spyOn(api, "listSessions").mockResolvedValue({
      items: [restrictedSession],
      total: 1,
      page: 1,
      page_size: 100,
    });
    const createStepUp = vi.spyOn(api, "createStepUp").mockResolvedValue({
      challenge_id: "aaaaaaaa-aaaa-aaaa-aaaa-aaaaaaaaaaaa",
      session_id: restrictedSession.session_id,
      expires_at: new Date(Date.now() + 300_000).toISOString(),
      simulated_otp: "123456",
    });
    const verifyStepUp = vi.spyOn(api, "verifyStepUp").mockResolvedValue({
      challenge_id: "aaaaaaaa-aaaa-aaaa-aaaa-aaaaaaaaaaaa",
      session_id: restrictedSession.session_id,
      status: "verified",
      step_up_token: "step-up-token-test",
      expires_at: new Date(Date.now() + 300_000).toISOString(),
    });
    const execute = vi.spyOn(api, "executePayout").mockRejectedValue(new TypeError("Failed to fetch"));

    renderDialog();

    await user.click(await screen.findByLabelText("Session"));
    await user.click(await screen.findByRole("option", { name: /RESTRICTED/ }));
    expect(screen.getByRole("button", { name: /Review payout/ })).toBeDisabled();

    await user.click(screen.getByRole("button", { name: "Start step-up challenge" }));
    await waitFor(() => expect(createStepUp).toHaveBeenCalledWith(
      expect.objectContaining({ token: "dev-merchant-token" }),
      restrictedSession.session_id,
    ));
    expect(await screen.findByLabelText("Verification code")).toHaveValue("123456");
    await user.click(screen.getByRole("button", { name: "Verify" }));
    await waitFor(() => expect(verifyStepUp).toHaveBeenCalledWith(
      expect.objectContaining({ token: "dev-merchant-token" }),
      restrictedSession.session_id,
      { challenge_id: "aaaaaaaa-aaaa-aaaa-aaaa-aaaaaaaaaaaa", code: "123456" },
    ));

    expect(await screen.findByText("Step-up verified. The token will be submitted once with this payout.")).toBeInTheDocument();
    expect(screen.getByRole("button", { name: /Review payout/ })).toBeEnabled();
    await user.type(screen.getByLabelText("Recipient email"), "beneficiary@example.test");
    await user.type(screen.getByLabelText("Amount"), "125.50");
    await user.click(screen.getByRole("button", { name: /Review payout/ }));
    await user.click(await screen.findByRole("button", { name: "Execute once" }));

    await waitFor(() => expect(execute).toHaveBeenCalledTimes(1));
    const [, body] = execute.mock.calls[0] ?? [];
    expect(body).toMatchObject({
      session_id: restrictedSession.session_id,
      step_up_token: "step-up-token-test",
    });
  });
});
