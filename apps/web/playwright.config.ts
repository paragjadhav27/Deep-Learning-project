import { rmSync } from "node:fs";
import { resolve } from "node:path";

import { defineConfig, devices } from "@playwright/test";

/**
 * End-to-end tests against the REAL API (YuNet face detection, mock estimators) and a
 * production build of the web app. Requires `facelens-api fetch-models` to have run.
 */
const API_PORT = 8010;
const WEB_PORT = 3100;
const apiDir = resolve(__dirname, "../api");
const dataDir = resolve(__dirname, "e2e/.data");
const python =
  process.env.E2E_PYTHON ??
  resolve(apiDir, process.platform === "win32" ? ".venv/Scripts/python.exe" : ".venv/bin/python");

// Every run starts with no stored photos. The config is also loaded inside test workers,
// where the API already holds the database open: only clean up in the main process.
if (!process.env.TEST_WORKER_INDEX) rmSync(dataDir, { recursive: true, force: true });

export default defineConfig({
  testDir: "./e2e",
  timeout: 60_000,
  expect: { timeout: 15_000 },
  fullyParallel: false,
  workers: 1,
  forbidOnly: !!process.env.CI,
  retries: process.env.CI ? 1 : 0,
  reporter: process.env.CI ? [["github"], ["html", { open: "never" }]] : "list",
  use: {
    baseURL: `http://127.0.0.1:${WEB_PORT}`,
    trace: "retain-on-failure",
  },
  projects: [
    { name: "desktop", use: { ...devices["Desktop Chrome"] } },
    { name: "mobile", use: { ...devices["Pixel 7"] }, grep: /@mobile/ },
  ],
  webServer: [
    {
      command: `"${python}" -m facelens_api.cli serve --port ${API_PORT}`,
      cwd: apiDir,
      url: `http://127.0.0.1:${API_PORT}/readyz`,
      reuseExistingServer: false,
      timeout: 60_000,
      env: {
        FACELENS_ENVIRONMENT: "development",
        FACELENS_DATABASE_URL: `sqlite:///${dataDir.replace(/\\/g, "/")}/e2e.db`,
        FACELENS_STORAGE_DIR: `${dataDir}/blobs`,
        FACELENS_FACE_DETECTOR: "yunet",
        FACELENS_JOB_BACKEND: "thread",
        FACELENS_RATE_LIMIT_UPLOADS_PER_MINUTE: "1000",
        FACELENS_RATE_LIMIT_JOBS_PER_MINUTE: "1000",
        FACELENS_LOG_LEVEL: "WARNING",
      },
    },
    {
      // The same standalone server the Docker image runs.
      command: process.env.E2E_SKIP_BUILD
        ? "node scripts/serve-standalone.mjs"
        : "npx next build && node scripts/serve-standalone.mjs",
      url: `http://127.0.0.1:${WEB_PORT}/privacy`,
      reuseExistingServer: false,
      timeout: 300_000,
      env: {
        API_ORIGIN: `http://127.0.0.1:${API_PORT}`,
        PORT: String(WEB_PORT),
        NEXT_TELEMETRY_DISABLED: "1",
      },
    },
  ],
});
