import { expect, test, type Page } from "@playwright/test";

const MERCHANT_INCIDENT = "66666666-6666-6666-6666-666666666666";
const NORMAL_SESSION = "22222222-2222-2222-2222-222222222222";
const RESTRICTED_SESSION = "33333333-3333-3333-3333-333333333333";
const DECOY_SESSION = "44444444-4444-4444-4444-444444444444";
const MERCHANT_USER = "11111111-1111-1111-1111-111111111111";
const API_BASE_URL = "http://127.0.0.1:8010";

async function signIn(
  page: Page,
  persona: "Merchant operator" | "Risk analyst" | "Other merchant" = "Merchant operator",
) {
  await page.goto("/login");
  await expect(page.getByRole("heading", { name: "Sign in to the console" })).toBeVisible();
  await page.getByRole("button", { name: new RegExp(persona) }).click();
  await expect(page.getByRole("heading", { name: "Trust overview" })).toBeVisible();
}

test.describe("merchant console", () => {
  test("signs in and reaches every module without a fabricated fallback", async ({ page }) => {
    await signIn(page);

    const routes = [
      ["Payouts", "Payout operations"],
      ["Incidents", "Security incidents"],
      ["Risk Intelligence", "Authoritative risk configuration"],
      ["Sessions & Identities", "Sessions & identities"],
      ["Honey Workspace", "Honey workspace"],
      ["Evidence Vault", "Tamper-evident evidence"],
      ["Agentic Commerce", "Agent registry"],
      ["Simulation & Calibration", "Synthetic attack drills"],
      ["System & Access", "Runtime context"],
      ["Overview", "Trust overview"],
    ] as const;

    for (const [link, heading] of routes) {
      await page.getByRole("link", { name: link, exact: true }).click();
      await expect(page.getByRole("heading", { name: heading })).toBeVisible();
      await expect(page.getByText("Backend unreachable")).toHaveCount(0);
    }

    const storage = await page.evaluate(() => ({
      localKeys: Object.keys(localStorage),
      tabSession: sessionStorage.getItem("identitytwin.console.session.v1"),
    }));
    expect(storage.localKeys).toEqual([]);
    expect(storage.tabSession).toContain("dev-merchant-token");
  });

  test("filters and opens a server-backed payout record", async ({ page }) => {
    await signIn(page);
    await page.getByRole("link", { name: "Payouts", exact: true }).click();

    await page.getByLabel("Search payouts").fill("INV-1001");
    await expect(page.getByText("1 matching payout")).toBeVisible();
    await expect(page.getByText("finance@northwind.example")).toBeVisible();

    await page.locator('a[href^="/payouts/"]').first().click();
    await expect(page.getByText("Authoritative decision")).toBeVisible();
    await expect(page.getByRole("heading", { name: "$1,840.00" })).toBeVisible();
    await expect(page.getByText("Allow", { exact: true })).toBeVisible();
  });

  test("executes a payout once after review and displays the gateway result", async ({ page }) => {
    await signIn(page);
    await page.getByRole("link", { name: "Payouts", exact: true }).click();
    await page.getByRole("button", { name: "New payout" }).click();

    await expect(page.getByRole("heading", { name: "Execute protected payout" })).toBeVisible();
    await page.getByLabel("Session").click();
    await page.getByRole("option", { name: /NORMAL/ }).click();
    await page.getByLabel("Recipient email").fill("finance@northwind.example");
    await page.getByLabel("Amount").fill("1.25");
    await page.getByLabel("Reference note").fill("E2E-ONE-SHOT");
    await page.getByRole("button", { name: /Review payout/ }).click();

    await expect(page.getByText("Confirm payout execution")).toBeVisible();
    await expect(page.getByText("The console does not retry this mutation.")).toBeVisible();
    await page.getByRole("button", { name: "Execute once" }).click();

    await expect(page.getByRole("heading", { name: "Gateway outcome recorded" })).toBeVisible();
    await expect(page.getByText("These values come directly from the authoritative gateway response.")).toBeVisible();
    const outcome = page.getByRole("dialog", { name: "Gateway outcome recorded" });
    await expect(outcome.getByText("Completed", { exact: true })).toBeVisible();
    await expect(outcome.getByText("Provider reference")).toBeVisible();

    await page.getByRole("link", { name: /Open payout record/ }).click();
    await expect(page).toHaveURL(/\/payouts\/[0-9a-f-]+$/);
    await expect(page.getByText("Authoritative decision")).toBeVisible();
  });

  test("verifies chain consistency without overstating immutability", async ({ page }) => {
    await signIn(page);
    await page.getByRole("link", { name: "Evidence Vault", exact: true }).click();

    await page.getByRole("button", { name: "Verify current chain" }).click();
    const result = page.getByTestId("chain-verification-result");
    await expect(result).toContainText("Chain is consistent across");
    await expect(page.getByText("does not prove database immutability", { exact: false })).toBeVisible();

    await page.locator('a[href^="/evidence/"]').first().click();
    await expect(page).toHaveURL(/\/evidence\/[0-9a-f-]+$/);
    const seal = page.getByTestId("seal-verification");
    await expect(seal).toContainText("Seal range is internally consistent");
    await expect(seal).toContainText("not proof of immutability or independent custody");
  });

  test("submits an agent payout once with a server-resolved grant and shows the recorded outcome", async ({ page }) => {
    await signIn(page);
    await page.getByRole("link", { name: "Agentic Commerce", exact: true }).click();
    await page.getByRole("button", { name: "Agent payout" }).click();

    const dialog = page.getByRole("dialog", { name: "Agent-initiated payout" });
    await expect(dialog).toBeVisible();
    await dialog.getByRole("combobox", { name: "Agent", exact: true }).click();
    await page.getByRole("option", { name: /Acme Shopping Assistant/ }).click();
    await dialog.getByRole("combobox", { name: "Authorization grant", exact: true }).click();
    await page.getByRole("option", { name: /exp/ }).first().click();
    await dialog.getByRole("combobox", { name: "Session", exact: true }).click();
    await page.getByRole("option", { name: /NORMAL/ }).click();
    await dialog.getByLabel("Recipient email", { exact: true }).fill("finance@northwind.example");
    await dialog.getByLabel("Amount", { exact: true }).fill("1.25");
    await dialog.getByLabel("Agent intent (optional)", { exact: true }).fill("E2E agent settlement");
    await dialog.getByRole("button", { name: "Review agent payout" }).click();

    await expect(page.getByText("Confirm agent-initiated payout")).toBeVisible();
    await expect(page.getByText("No automatic retry", { exact: true })).toBeVisible();
    await page.getByRole("button", { name: "Submit agent payout" }).click();

    const outcome = page.getByRole("dialog", { name: "Authoritative agent outcome" });
    await expect(outcome).toBeVisible();
    await expect(outcome.getByText("Completed", { exact: true })).toBeVisible();
    await expect(outcome.getByText("Acme Shopping Assistant")).toBeVisible();
    await outcome.locator('a[href^="/payouts/"]').click();
    await expect(page).toHaveURL(/\/payouts\/[0-9a-f-]+$/);
    await expect(page.getByText("Authoritative decision")).toBeVisible();
  });

  test("runs only the implemented synthetic drill and links to its real records", async ({ page }) => {
    await signIn(page);
    await page.getByRole("link", { name: "Simulation & Calibration", exact: true }).click();

    await page.getByRole("button", { name: "Run synthetic drill" }).click();
    await page.getByRole("dialog", { name: "Run synthetic account-takeover drill?" }).getByRole("button", { name: "Run drill once" }).click();

    const result = page.getByTestId("simulation-result");
    await expect(result).toBeVisible();
    await expect(result).toContainText("Drill completed: synthetic records created");
    await expect(result).toContainText("does not prove production fraud prevention");
    await expect(result.getByRole("link", { name: "Review incident" })).toBeVisible();
  });

  test("shows role-denied incident actions without hiding the server policy", async ({ page }) => {
    await signIn(page);
    await page.goto(`/incidents/${MERCHANT_INCIDENT}`);

    await expect(page.getByRole("heading", { name: "Suspicious Rapid Device Fingerprint Shift" })).toBeVisible();
    await expect(page.getByText("No actions available")).toBeVisible();
    await page.getByText("Unavailable actions (3)").click();
    await expect(page.getByText("Analyst or admin role is required.").first()).toBeVisible();
    await expect(page.getByRole("button", { name: "Approve review" })).toHaveCount(0);
  });

  test("discloses development auth and clears the tab session on sign-out", async ({ page }) => {
    await signIn(page);
    await page.getByRole("link", { name: "System & Access", exact: true }).click();

    await expect(page.getByRole("heading", { name: "Runtime context" })).toBeVisible();
    await expect(page.getByText("Development authentication is active", { exact: true })).toBeVisible();
    await expect(page.getByText("OIDC not configured", { exact: true })).toBeVisible();
    await expect(page.getByText("sessionStorage", { exact: false }).first()).toBeVisible();

    await page.getByRole("button", { name: "Sign out of this tab" }).click();
    await expect(page.getByRole("heading", { name: "Sign in to the console" })).toBeVisible();
    const storage = await page.evaluate(() => ({
      localKeys: Object.keys(localStorage),
      tabSession: sessionStorage.getItem("identitytwin.console.session.v1"),
    }));
    expect(storage.localKeys).toEqual([]);
    expect(storage.tabSession).toBeNull();
  });

  test("shows a real backend failure instead of demo data when the API is unreachable", async ({ page }) => {
    await page.route("**/v1/analytics/overview*", (route) => route.abort("failed"));
    await signIn(page);

    await expect(page.getByRole("alert").getByText("Backend unreachable")).toBeVisible();
    await expect(page.getByRole("button", { name: "Retry request" })).toBeVisible();
    await expect(page.getByText("No analytics data returned")).toHaveCount(0);
  });

  test("projects seeded honey workspaces and redacts canary secrets across merchants", async ({ page }) => {
    await signIn(page);
    const auth = { Authorization: "Bearer dev-merchant-token" };

    const unauthorized = await page.request.get(`${API_BASE_URL}/v1/honey/operator/workspaces`);
    expect(unauthorized.status()).toBe(401);

    const workspacesResponse = await page.request.get(
      `${API_BASE_URL}/v1/honey/operator/workspaces`,
      { headers: auth },
    );
    expect(workspacesResponse.status()).toBe(200);
    const workspaces = await workspacesResponse.json();
    expect(workspaces.items.map((item: { session_id: string }) => item.session_id)).toContain(
      DECOY_SESSION,
    );

    const canariesResponse = await page.request.get(
      `${API_BASE_URL}/v1/honey/operator/canaries`,
      { headers: auth },
    );
    expect(canariesResponse.status()).toBe(200);
    const canaries = await canariesResponse.json();
    expect(canaries.total).toBeGreaterThan(0);
    expect(JSON.stringify(canaries)).not.toContain("secret_value");

    await page.getByRole("link", { name: "Honey Workspace", exact: true }).click();
    await expect(
      page.getByRole("heading", { name: "Honey workspace", exact: true }),
    ).toBeVisible();
    const decoyWorkspace = page.locator(`a[href="/honey/${DECOY_SESSION}"]`).first();
    await expect(decoyWorkspace).toBeVisible();
    await decoyWorkspace.click();
    await expect(page.getByText("Synthetic decoy", { exact: true })).toBeVisible();
    await expect(page.getByText("5 / 0", { exact: true })).toBeVisible();
    const visibleWorkspace = await page.locator("body").innerText();
    expect(visibleWorkspace).not.toContain("secret_value");
    expect(visibleWorkspace).not.toContain("client_secret");

    const otherMerchantPage = await page.context().newPage();
    await signIn(otherMerchantPage, "Other merchant");
    await otherMerchantPage.getByRole("link", { name: "Honey Workspace", exact: true }).click();
    await expect(otherMerchantPage.getByText("No honey workspaces")).toBeVisible();
    await expect(otherMerchantPage.getByText("No canaries issued.")).toBeVisible();
    await otherMerchantPage.close();
  });

  test("contains a canary hit only in its owning session and seals the resulting incident", async ({
    page,
  }) => {
    await signIn(page);
    const auth = { Authorization: "Bearer dev-merchant-token" };
    const scope = `session_id=${NORMAL_SESSION}&identity_id=${MERCHANT_USER}`;

    // Call apps endpoint to ensure canary exists (seeded with known secret)
    const issuedResponse = await page.request.get(
      `${API_BASE_URL}/v1/honey/developer/apps?${scope}`,
      { headers: auth },
    );
    expect(issuedResponse.status()).toBe(200);
    // Known secret seeded in _seed_demo_honey for NORMAL_SESSION
    const canarySecret = "E2E_TEST_CANARY_SECRET_KNOWN_VALUE";

    const crossSessionAttempt = await page.request.post(
      `${API_BASE_URL}/v1/honey/developer/credentials/reveal`,
      {
        headers: auth,
        data: {
          session_id: RESTRICTED_SESSION,
          identity_id: MERCHANT_USER,
          client_secret: canarySecret,
        },
      },
    );
    expect(crossSessionAttempt.status()).toBe(200);
    const untouchedWorkspace = await page.request.get(
      `${API_BASE_URL}/v1/honey/operator/workspaces/${RESTRICTED_SESSION}`,
      { headers: auth },
    );
    expect(untouchedWorkspace.status()).toBe(200);
    const untouchedDetail = await untouchedWorkspace.json();
    expect(untouchedDetail.workspace.session_status).toBe("active");
    expect(untouchedDetail.workspace.canaries_triggered).toBe(0);

    const hit = await page.request.post(
      `${API_BASE_URL}/v1/honey/developer/credentials/reveal`,
      {
        headers: auth,
        data: {
          session_id: NORMAL_SESSION,
          identity_id: MERCHANT_USER,
          client_secret: canarySecret,
        },
      },
    );
    expect(hit.status()).toBe(403);

    const containedWorkspace = await page.request.get(
      `${API_BASE_URL}/v1/honey/operator/workspaces/${NORMAL_SESSION}`,
      { headers: auth },
    );
    expect(containedWorkspace.status()).toBe(200);
    const detail = await containedWorkspace.json();
    expect(detail.workspace.session_status).toBe("revoked");
    expect(detail.workspace.containment_incident_id).toBeTruthy();
    expect(
      detail.canaries.some((canary: { triggered_at: string | null }) => canary.triggered_at),
    ).toBe(true);

    await page.getByRole("link", { name: "Honey Workspace", exact: true }).click();
    await page.locator(`a[href="/honey/${NORMAL_SESSION}"]`).first().click();
    await expect(
      page.getByRole("link", { name: /Incident [0-9a-f]{8}/i }),
    ).toBeVisible();
    await expect(page.getByText("Triggered", { exact: true })).toBeVisible();
  });
});

test.describe("analyst console", () => {
  test("shows only the server-authorized incident actions", async ({ page }) => {
    await page.goto("/login");
    await page.getByRole("button", { name: /Risk analyst/ }).click();
    await expect(page.getByRole("heading", { name: "Trust overview" })).toBeVisible();
    await page.goto(`/incidents/${MERCHANT_INCIDENT}`);

    await expect(page.getByRole("heading", { name: "Suspicious Rapid Device Fingerprint Shift" })).toBeVisible();
    await expect(page.getByText("Authorization-aware actions")).toBeVisible();
    await expect(page.getByRole("button", { name: "Approve review" })).toBeVisible();
    await expect(page.getByText("No actions available")).toHaveCount(0);
  });
});
