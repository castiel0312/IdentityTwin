import { chromium } from "@playwright/test";
import fs from "node:fs";
import path from "node:path";

const phase = process.argv[2] ?? "before";
const baseURL = process.env.BASE_URL ?? "http://127.0.0.1:5173";
const outDir = path.resolve(process.cwd(), "..", "docs", "screenshots", phase);
fs.mkdirSync(outDir, { recursive: true });

const browser = await chromium.launch();
const context = await browser.newContext({
  viewport: { width: 1440, height: 1000 },
  deviceScaleFactor: 1,
});
const page = await context.newPage();

async function shot(name, fullPage = true) {
  await page.waitForTimeout(900);
  await page.screenshot({ path: path.join(outDir, `${name}.png`), fullPage });
  console.log(`captured ${phase}/${name}.png`);
}

await page.goto(`${baseURL}/login`, { waitUntil: "networkidle" });
await shot("login", false);

await page.getByRole("button", { name: /Merchant operator/ }).click();
await page.getByRole("heading", { name: "Trust overview" }).waitFor();
await page.waitForTimeout(1400);
await shot("overview");

const routes = [
  ["payouts", "/payouts", "Payout operations"],
  ["risk", "/risk", "Authoritative risk configuration"],
  ["incidents", "/incidents", "Security incidents"],
  ["sessions", "/sessions", "Sessions & identities"],
  ["honey", "/honey", "Honey workspace"],
  ["evidence", "/evidence", "Tamper-evident evidence"],
  ["agents", "/agents", "Agent registry"],
  ["simulation", "/simulation", "Synthetic attack drills"],
  ["system", "/system", "Runtime context"],
];

for (const [name, route, heading] of routes) {
  await page.goto(`${baseURL}${route}`, { waitUntil: "networkidle" });
  await page.getByRole("heading", { name: heading }).waitFor();
  await page.waitForTimeout(900);
  await shot(name);
}

await page.goto(`${baseURL}/payouts`, { waitUntil: "networkidle" });
const payoutHref = await page.locator('a[href^="/payouts/"]').first().getAttribute("href");
if (payoutHref) {
  await page.goto(`${baseURL}${payoutHref}`, { waitUntil: "networkidle" });
  await page.waitForTimeout(900);
  await shot("payout-detail");
}

await page.goto(`${baseURL}/incidents`, { waitUntil: "networkidle" });
const incidentHref = await page.locator('a[href^="/incidents/"]').first().getAttribute("href");
if (incidentHref) {
  await page.goto(`${baseURL}${incidentHref}`, { waitUntil: "networkidle" });
  await page.waitForTimeout(900);
  await shot("incident-detail");
}

await page.goto(`${baseURL}/evidence`, { waitUntil: "networkidle" });
const sealHref = await page.locator('a[href^="/evidence/"]').first().getAttribute("href");
if (sealHref) {
  await page.goto(`${baseURL}${sealHref}`, { waitUntil: "networkidle" });
  await page.waitForTimeout(900);
  await shot("evidence-detail");
}

// Mobile overview
const mobile = await browser.newContext({ viewport: { width: 390, height: 844 }, deviceScaleFactor: 1 });
const mobilePage = await mobile.newPage();
await mobilePage.goto(`${baseURL}/login`, { waitUntil: "networkidle" });
await mobilePage.getByRole("button", { name: /Merchant operator/ }).click();
await mobilePage.getByRole("heading", { name: "Trust overview" }).waitFor();
await mobilePage.waitForTimeout(1200);
await mobilePage.screenshot({ path: path.join(outDir, "overview-mobile.png"), fullPage: true });
console.log(`captured ${phase}/overview-mobile.png`);

await browser.close();
