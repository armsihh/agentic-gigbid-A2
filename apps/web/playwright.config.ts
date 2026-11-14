import { defineConfig, devices } from "@playwright/test";
import os from "node:os";
import path from "node:path";
import { fileURLToPath } from "node:url";

// Starts GigSim, the API (scripted models: GIGBID_FAKE_LLM=1, throwaway SQLite) and the Vite dev server.
const root = path.resolve(path.dirname(fileURLToPath(import.meta.url)), "../..");
const tmp = path.join(os.tmpdir(), `gigbid-e2e-${Date.now()}`);
const apiEnv = {
  GIGBID_FAKE_LLM: "1",
  INLINE_SCHEDULER: "0",
  DATABASE_URL: `sqlite:///${path.join(tmp, "app.db").replace(/\\/g, "/")}`,
  APP_DATA_DIR: tmp,
  AUDIT_LOG_DIR: path.join(tmp, "audit"),
  WORKSPACE_STATE_DIR: path.join(tmp, "ws"),
  RAG_VARIANT: "bm25",
  GIGSIM_BASE_URL: "http://127.0.0.1:8081",
  WEB_ORIGIN: "http://localhost:5173",
};

export default defineConfig({
  testDir: "tests/e2e",
  timeout: 90_000,
  expect: { timeout: 30_000 },
  workers: 1,
  reporter: [["list"], ["html", { open: "never" }]],
  use: { baseURL: "http://localhost:5173", trace: "retain-on-failure", screenshot: "only-on-failure" },
  projects: [
    { name: "desktop", use: { ...devices["Desktop Chrome"] } },
  ],
  webServer: [
    {
      command: "uv run uvicorn gigsim.app:app --host 127.0.0.1 --port 8081",
      cwd: root, port: 8081, reuseExistingServer: false, timeout: 120_000,
      env: { GIGSIM_ERROR_RATE: "0", GIGSIM_SLOW_RATE: "0", GIGSIM_TIME_SCALE: "60" },
    },
    {
      command: "uv run uvicorn apps.api.main:app --host 127.0.0.1 --port 8000",
      cwd: root, url: "http://127.0.0.1:8000/api/health", reuseExistingServer: false, timeout: 180_000, env: apiEnv,
    },
    { command: "npm run dev -- --port 5173 --strictPort", port: 5173, reuseExistingServer: false, timeout: 120_000 },
  ],
});
