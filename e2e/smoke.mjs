import assert from "node:assert/strict";
import { chromium } from "playwright";

const baseUrl =
  process.env.BASE_URL ??
  "https://multi-hospital-outreach-production.up.railway.app";

const browser = await chromium.launch({ headless: true });
const page = await browser.newPage({ viewport: { width: 1440, height: 1000 } });

try {
  const health = await page.request.get(`${baseUrl}/api/v1/health`);
  assert.equal(health.status(), 200);
  assert.equal((await health.json()).status, "healthy");

  await page.goto(baseUrl, { waitUntil: "networkidle" });
  await page.getByRole("heading", { name: "Operations overview" }).waitFor();

  for (const section of [
    "Outreach Queue",
    "Campaigns",
    "Patients",
    "Escalations",
    "Safety Evaluation",
    "System Health",
    "Audit Trail",
  ]) {
    await page.getByRole("button", { name: section }).click();
    await page.waitForTimeout(150);
    assert.equal(
      await page.getByText("Demo access is unavailable.").count(),
      0,
      `${section} lost evaluation access`,
    );
  }

  console.log("Playwright smoke test passed");
} finally {
  await browser.close();
}