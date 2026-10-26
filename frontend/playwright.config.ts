import path from "node:path";
import { fileURLToPath } from "node:url";
import { defineConfig, devices } from "@playwright/test";

const frontendDir = path.dirname(fileURLToPath(import.meta.url));
const root = path.resolve(frontendDir, "..");
const apiDir = path.resolve(root, "apps/api");
const venv = path.resolve(root, ".venv");

export default defineConfig({
  testDir: "./e2e",
  fullyParallel: false,
  workers: 1,
  forbidOnly: Boolean(process.env.CI),
  retries: process.env.CI ? 1 : 0,
  timeout: 60_000,
  expect: { timeout: 12_000 },
  reporter: [["list"]],
  use: {
    baseURL: "http://127.0.0.1:5174",
    trace: "retain-on-failure",
    screenshot: "only-on-failure",
    video: "off",
    ...devices["Desktop Chrome"],
  },
  webServer: [
    {
      // Use a disposable database and dedicated ports so E2E runs never
      // mutate the developer's seeded database or reuse a mismatched server.
      command: `rm -f identitytwin_e2e.db && PYTHONPATH=. ${venv}/bin/python ../../scripts/seed_demo.py && PYTHONPATH=. ${venv}/bin/uvicorn app.main:app --host 127.0.0.1 --port 8010 --log-level warning`,
      cwd: apiDir,
      url: "http://127.0.0.1:8010/health",
      reuseExistingServer: false,
      timeout: 120_000,
      env: {
        DATABASE_URL: "sqlite:///./identitytwin_e2e.db",
        ENVIRONMENT: "development",
        ALLOW_DEV_AUTH: "true",
      },
    },
    {
      command: "npm run dev -- --host 127.0.0.1 --port 5174",
      cwd: frontendDir,
      url: "http://127.0.0.1:5174",
      reuseExistingServer: false,
      timeout: 120_000,
      env: { VITE_API_PROXY: "http://127.0.0.1:8010" },
    },
  ],
});
