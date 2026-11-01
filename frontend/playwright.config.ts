import { existsSync } from "node:fs";
import path from "node:path";
import { fileURLToPath } from "node:url";
import { defineConfig, devices } from "@playwright/test";

const frontendDir = path.dirname(fileURLToPath(import.meta.url));
const root = path.resolve(frontendDir, "..");
const apiDir = path.resolve(root, "apps/api");
const venvPython = path.resolve(
  root,
  ".venv",
  process.platform === "win32" ? "Scripts/python.exe" : "bin/python",
);
const pythonExecutable =
  process.env.IDENTITYTWIN_PYTHON ??
  (existsSync(venvPython) ? venvPython : process.platform === "win32" ? "py" : "python3");
const pythonCommand = `"${pythonExecutable}"${
  !process.env.IDENTITYTWIN_PYTHON &&
  !existsSync(venvPython) &&
  process.platform === "win32"
    ? " -3"
    : ""
}`;
const seedScript = path.resolve(root, "scripts/seed_demo.py");

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
      command: `${pythonCommand} -c "from pathlib import Path; Path('identitytwin_e2e.db').unlink(missing_ok=True)" && ${pythonCommand} "${seedScript}" && ${pythonCommand} -m uvicorn app.main:app --host 127.0.0.1 --port 8010 --log-level warning`,
      cwd: apiDir,
      url: "http://127.0.0.1:8010/health",
      reuseExistingServer: false,
      timeout: 120_000,
      env: {
        PYTHONPATH: apiDir,
        DATABASE_URL: "sqlite:///./identitytwin_e2e.db",
        HONEY_DB_URL: "sqlite:///./identitytwin_e2e.db",
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
