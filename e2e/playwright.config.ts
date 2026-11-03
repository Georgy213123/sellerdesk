import { defineConfig, devices } from "@playwright/test";

// Стенд: свой PostgreSQL по DATABASE_URL, API :8101, фронт :5101.
// Если стенд уже поднят (`make up` или `make dev`), Playwright его переиспользует.
const DATABASE_URL =
  process.env.DATABASE_URL ?? "postgresql+psycopg://sellerdesk:sellerdesk@localhost:55101/sellerdesk";
const BASE_URL = process.env.E2E_BASE_URL ?? "http://127.0.0.1:5101";

export default defineConfig({
  testDir: "./tests",
  fullyParallel: false,
  workers: 1,
  retries: process.env.CI ? 1 : 0,
  reporter: [["list"], ["html", { outputFolder: "playwright-report", open: "never" }]],
  use: {
    baseURL: BASE_URL,
    trace: "retain-on-failure",
    screenshot: "only-on-failure",
  },
  projects: [
    {
      name: "desktop",
      use: { ...devices["Desktop Chrome"], viewport: { width: 1440, height: 900 } },
    },
    {
      name: "mobile",
      use: {
        ...devices["Desktop Chrome"],
        viewport: { width: 390, height: 844 },
        isMobile: true,
        hasTouch: true,
      },
    },
  ],
  webServer: process.env.E2E_BASE_URL
    ? undefined
    : [
        {
          // Чистая демо-база и API. Задержка заглушки площадок меньше, чем в демо, но не ноль.
          command:
            "cd ../backend && uv run python -m app.cli reset && uv run uvicorn app.main:app --host 127.0.0.1 --port 8101",
          url: "http://127.0.0.1:8101/api/health",
          env: { DATABASE_URL, MOCK_MARKETPLACE_DELAY_MS: "300" },
          reuseExistingServer: !process.env.CI,
          timeout: 120_000,
        },
        {
          command: "npm --prefix ../frontend run dev -- --host 127.0.0.1",
          url: BASE_URL,
          reuseExistingServer: !process.env.CI,
          timeout: 120_000,
        },
      ],
});
