import { expect, test, type Page } from "@playwright/test";

const MERCHANT_INCIDENT = "66666666-6666-6666-6666-666666666666";

async function signIn(page: Page, persona: "Merchant operator" | "Risk analyst" = "Merchant operator") {
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
