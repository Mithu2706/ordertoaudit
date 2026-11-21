/**
 * Benchmark steps 4-7 clicked through the real UI, one fresh browser context per role.
 * Needs a fresh instance with benchmark steps 1-3 seeded (see playwright.config.ts).
 */
import { expect, test, type Browser, type Page } from "@playwright/test";

const PASSWORD = process.env.E2E_PASSWORD ?? "Demo@1234";
const PHONE = { width: 390, height: 844 };

async function signIn(browser: Browser, username: string, viewport?: { width: number; height: number }): Promise<Page> {
  const context = await browser.newContext(viewport ? { viewport, isMobile: true, hasTouch: true } : {});
  const page = await context.newPage();
  await page.goto("/login");
  await page.getByLabel("Username").fill(username);
  await page.getByLabel("Password").fill(PASSWORD);
  await page.getByRole("button", { name: "Sign in" }).click();
  await expect(page).not.toHaveURL(/\/login/);
  return page;
}

async function placeOrder(page: Page, customer: RegExp, packets: string): Promise<string> {
  await page.goto("/sales/new");
  await page.getByRole("button", { name: customer }).click();
  await page.getByLabel("Quantity").first().fill(packets);
  await page.getByRole("button", { name: "Review" }).click();
  await page.getByRole("button", { name: "Submit for approval" }).click();
  await expect(page.getByText("Submitted", { exact: true }).first()).toBeVisible();
  const text = await page.locator("main").innerText();
  const orderNo = text.match(/SO\/\d{4}-\d{2}\/\d{5}/)?.[0];
  expect(orderNo, "order number shown on the order page").toBeTruthy();
  return orderNo!; // SO/2026-27/00001
}

test.describe.configure({ mode: "serial" });

test("steps 1-3 are already posted: stock as per the benchmark", async ({ browser }) => {
  const page = await signIn(browser, "production");
  await page.goto("/stock");
  const row = (name: string) => page.getByRole("row", { name: new RegExp(name) });
  await expect(row("Flour")).toContainText("120");
  await expect(row("Cooking oil")).toContainText("19.5");
  await page.getByRole("button", { name: "Packaging" }).click();
  await expect(row("200 g printed pouch")).toContainText("306");
  await page.getByRole("button", { name: "Finished goods" }).click();
  await expect(row("Murukku 200 g")).toContainText("238");
});

test("step 4-5: salesman orders 150 on a phone; admin approves, invoices Rs 7,875 and dispatches", async ({ browser }) => {
  const sales = await signIn(browser, "salesman_a", PHONE);
  const orderNo = await placeOrder(sales, /Retailer A/, "150");
  await expect(sales.getByText("₹7,875.00").first()).toBeVisible();

  const admin = await signIn(browser, "admin");
  await admin.goto("/admin/orders");
  await admin.getByRole("link", { name: orderNo }).click();
  await admin.getByRole("button", { name: "Approve as ordered" }).click();
  await expect(admin.getByText("Approved", { exact: true }).first()).toBeVisible();
  await admin.getByRole("button", { name: "Generate invoice" }).click();
  await expect(admin).toHaveURL(/\/admin\/invoices\/\d+/);
  await expect(admin.getByText("₹7,875.00").first()).toBeVisible();
  await expect(admin.getByText("₹187.50").first()).toBeVisible(); // CGST = SGST

  await admin.getByRole("button", { name: "Dispatch" }).click();
  await admin.getByPlaceholder("TN37 AB 1234").fill("TN37 AB 1234");
  await admin.getByRole("button", { name: "Dispatch & update stock" }).click();
  await expect(admin.getByText("TN37 AB 1234").first()).toBeVisible();

  await admin.goto("/stock");
  await admin.getByRole("button", { name: "Finished goods" }).click();
  await expect(admin.getByRole("row", { name: /Murukku 200 g/ })).toContainText("88");
});

test("step 6: distributor B orders 120; admin sees the 32-packet shortage and cannot approve it all", async ({ browser }) => {
  const sales = await signIn(browser, "salesman_b", PHONE);
  const orderNo = await placeOrder(sales, /Distributor B/, "120");

  const admin = await signIn(browser, "admin");
  await admin.goto("/admin/orders");
  await admin.getByRole("link", { name: orderNo }).click();
  await expect(admin.getByText("Insufficient stock.")).toBeVisible();
  await expect(admin.getByRole("row", { name: /Murukku 200 g/ })).toContainText("32");
  // The form pre-fills the available 88; asking for all 120 is refused by the server.
  await admin.getByLabel("Approved quantity").fill("120");
  await admin.getByRole("button", { name: "Approve as ordered" }).click();
  await expect(admin.getByRole("alert").filter({ hasText: "short by 32" })).toBeVisible();
  await expect(admin.getByText("Submitted", { exact: true }).first()).toBeVisible();
});

test("step 7: Rs 4,000 from Retailer A leaves Rs 3,875 outstanding; owner and auditor see it", async ({ browser }) => {
  const admin = await signIn(browser, "admin");
  await admin.goto("/admin/payments");
  await admin.getByRole("combobox").first().selectOption({ label: "Retailer A (Sri Murugan Stores)" });
  await admin.getByLabel("Amount (₹)").fill("4000");
  await admin.getByRole("button", { name: "Record receipt" }).click();
  await expect(admin.getByRole("row", { name: /Retailer A/ }).first()).toContainText("₹3,875.00");

  const owner = await signIn(browser, "owner");
  await owner.goto("/dashboard");
  await expect(owner.getByText("₹7,500.00").first()).toBeVisible(); // net sales
  await expect(owner.getByText("₹3,875.00").first()).toBeVisible(); // receivables

  const auditor = await signIn(browser, "auditor");
  await auditor.goto("/reports?key=gst-summary");
  await expect(auditor.getByRole("cell", { name: "187.50" }).first()).toBeVisible();
  await auditor.goto("/admin/payments");
  await expect(auditor.getByRole("button", { name: "Record receipt" })).toHaveCount(0); // read-only
});
