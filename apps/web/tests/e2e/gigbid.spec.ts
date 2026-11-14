import { expect, type Page, test } from "@playwright/test";

// Jobs that the ai_ml persona should bid on (gold label: bid) - see evals/datasets/dev/labels.jsonl
const JOB_APPROVE = "job-a532010879";
const JOB_EDIT = "job-885ee7c883";
const JOB_REJECT = "job-cb4411c3ac";
const GIGSIM = "http://127.0.0.1:8081";
const ADMIN = { Authorization: "Bearer dev-admin" };

async function signUp(page: Page) {
  const email = `e2e-${Date.now()}-${Math.floor(Math.random() * 1e6)}@example.com`;
  await page.goto("/");
  await page.getByRole("button", { name: "New here? Create an account" }).click();
  await page.getByLabel("Email").fill(email);
  await page.getByLabel("Password").fill("correct-horse-battery");
  await page.getByLabel("Profile").selectOption("ai_ml");
  await page.getByRole("button", { name: "Create account" }).click();
  await expect(page.getByRole("heading", { name: "Settings" })).toBeVisible();
  return email;
}

/** Analyse a job through the API (same session cookie), then open its proposal once the graph pauses. */
async function draftFor(page: Page, jobId: string) {
  const r = await page.request.post(`/api/jobs/${jobId}/analyze`);
  expect(r.ok()).toBeTruthy();
  const { run_id } = await r.json();
  await page.goto(`/runs/${run_id}?job=${jobId}`);
  await expect(page.getByTestId("run-status")).toHaveText(/waiting approval/, { timeout: 60_000 });
  await page.getByRole("button", { name: "Review proposal" }).click();
  await expect(page.getByTestId("approval-panel")).toBeVisible();
}

test.beforeAll(async ({ request }) => {
  await request.post(`${GIGSIM}/admin/reset`, { headers: ADMIN });
});

test("onboarding: sign up, set rates, add a saved search", async ({ page }) => {
  await signUp(page);
  await expect(page.getByText("Welcome!")).toBeVisible();
  await page.getByLabel("Search name").fill("LLM jobs");
  await page.getByLabel("Keywords").fill("chatbot");
  await page.getByRole("button", { name: "Add" }).click();
  await expect(page.getByText("LLM jobs")).toBeVisible();
  await page.getByRole("link", { name: /Inbox/ }).click();
  await expect(page.getByRole("heading", { name: "Job inbox" })).toBeVisible();
});

test("approve a proposal: evidence on hover, dry run, submitted exactly once", async ({ page }) => {
  await signUp(page);
  await draftFor(page, JOB_APPROVE);
  await expect(page.getByTestId("dry-run")).toContainText("Connects");
  await page.getByTestId("claim").first().hover();
  await expect(page.getByRole("tooltip")).toBeVisible();
  await page.getByRole("button", { name: "Approve and send" }).click();
  await expect(page.getByTestId("run-status")).toHaveText(/done/);
  await page.goto("/pipeline");
  await expect(page.getByTestId("col-submitted")).toContainText("Deep Learning");
});

test("reject a proposal with a reason", async ({ page }) => {
  await signUp(page);
  await draftFor(page, JOB_REJECT);
  await page.getByRole("button", { name: "Reject" }).click();
  const btn = page.getByRole("button", { name: "Reject with reason" });
  await expect(btn).toBeDisabled();            // a reason is required
  await page.getByLabel("Rejection reason").fill("Scope is bigger than the budget");
  await btn.click();
  await expect(page.getByTestId("run-status")).toHaveText(/done/);
  await page.goto("/analytics");
  await expect(page.getByText("scope is bigger than the budget")).toBeVisible();
});

test("edit a draft before sending (edit is re-checked and recorded)", async ({ page }) => {
  await signUp(page);
  await draftFor(page, JOB_EDIT);
  await page.getByRole("button", { name: "Edit" }).click();
  const box = page.getByLabel("Edited text");
  await box.fill("I built a churn model with a 3.4x top-decile lift for a telecom operator. Happy to start with your data this week and share a short plan with milestones before we begin the work together.");
  await page.getByRole("button", { name: "Save edit and send" }).click();
  await expect(page.getByTestId("run-status")).toHaveText(/done/);
});

test("degraded mode: marketplace outage shows a banner, recovery clears it", async ({ page, request }) => {
  await signUp(page);
  await request.post(`${GIGSIM}/admin/faults`, { headers: ADMIN, data: { error_rate: 1 } });
  try {
    await page.goto("/inbox");
    await expect(page.getByTestId("degraded-banner")).toBeVisible({ timeout: 45_000 });
    await expect(page.getByTestId("degraded-banner")).toContainText("queued");
  } finally {
    await request.post(`${GIGSIM}/admin/faults`, { headers: ADMIN, data: { error_rate: 0 } });
  }
  await page.reload();
  await expect(page.getByTestId("degraded-banner")).toHaveCount(0, { timeout: 45_000 });
});
