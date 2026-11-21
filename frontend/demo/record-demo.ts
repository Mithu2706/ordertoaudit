/**
 * The demo video, scripted: production -> salesman -> admin -> shortage -> payment -> owner -> auditor.
 * Captions replace narration. Run with demo/demo.config.ts (see there).
 */
import { mkdirSync } from "node:fs";
import { expect, test, type Page } from "@playwright/test";

const PASSWORD = process.env.E2E_PASSWORD ?? "Demo@1234";
const OUT = "../demo-video";
const SHOTS = process.env.DEMO_SHOTS; // optional folder for review screenshots

/** Caption bar along the bottom of the screen (re-created after full page loads). */
async function caption(page: Page, text: string, holdMs = 4500) {
  await page.evaluate((t) => {
    let el = document.getElementById("demo-caption");
    if (!el) {
      el = document.createElement("div");
      el.id = "demo-caption";
      Object.assign(el.style, {
        position: "fixed", left: "50%", bottom: "22px", transform: "translateX(-50%)", zIndex: "99999",
        maxWidth: "1060px", padding: "12px 20px", borderRadius: "12px", background: "rgba(15,27,45,0.92)",
        color: "#fff", font: "500 17px/1.45 Inter, system-ui, sans-serif", boxShadow: "0 8px 30px rgba(0,0,0,.35)",
        textAlign: "center", pointerEvents: "none",
      });
      document.body.appendChild(el);
    }
    el.textContent = t;
  }, text);
  await page.waitForTimeout(holdMs);
}

async function clearCaption(page: Page) {
  await page.evaluate(() => document.getElementById("demo-caption")?.remove());
}

/** Full-screen title card. */
async function card(page: Page, title: string, subtitle: string, holdMs = 5000) {
  await page.evaluate(([t, s]) => {
    const el = document.createElement("div");
    el.id = "demo-card";
    el.innerHTML = `<div style="font:700 44px/1.2 Inter,system-ui,sans-serif">${t}</div>
      <div style="margin-top:18px;font:400 22px/1.5 Inter,system-ui,sans-serif;opacity:.85;max-width:900px">${s}</div>`;
    Object.assign(el.style, {
      position: "fixed", inset: "0", zIndex: "100000", display: "flex", flexDirection: "column",
      alignItems: "center", justifyContent: "center", textAlign: "center", padding: "40px",
      background: "linear-gradient(135deg,#0f1b2d,#1d3557)", color: "#fff",
    });
    document.body.appendChild(el);
  }, [title, subtitle]);
  await page.waitForTimeout(holdMs);
  await page.evaluate(() => document.getElementById("demo-card")?.remove());
}

async function shot(page: Page, name: string) {
  if (SHOTS) await page.screenshot({ path: `${SHOTS}/${name}.png` });
}

async function signIn(page: Page, username: string, who: string) {
  await page.goto("/login");
  await caption(page, `Signing in as ${who}`, 1200);
  await page.getByLabel("Username").pressSequentially(username, { delay: 70 });
  await page.getByLabel("Password").pressSequentially(PASSWORD, { delay: 50 });
  await page.getByRole("button", { name: "Sign in" }).click();
  await expect(page).not.toHaveURL(/\/login/);
  await page.waitForTimeout(800);
}

async function signOut(page: Page) {
  await clearCaption(page);
  await page.getByRole("button", { name: /Sign out/ }).first().click();
  await expect(page).toHaveURL(/\/login/);
}

test("demo video", async ({ page }) => {
  mkdirSync(OUT, { recursive: true });
  if (SHOTS) mkdirSync(SHOTS, { recursive: true });

  // ---- 0:00 The problem ----------------------------------------------------------------------
  await page.goto("/login");
  await card(page, "Annapoorna Snacks · Order-to-Audit",
    "Sales → Verification → GST Invoice → Dispatch → Inventory → Production → Costing → Audit, in one set of books.", 6000);
  await caption(page, "Orders used to arrive on paper, stock was counted rather than known, and nobody knew what a packet really cost.", 5500);
  await caption(page, "Every number in this system is derived from posted documents. Five roles: salesman, admin, production, owner and auditor.", 5500);
  await shot(page, "01-login");

  // ---- Production already happened (benchmark steps 1-3) ---------------------------------------
  await signIn(page, "production", "the production supervisor");
  await caption(page, "This morning: 60 kg of flour bought at ₹45, and one batch planned at 200 packets of Murukku.", 4500);
  await page.getByRole("link", { name: /PRD\// }).first().click();
  await page.waitForTimeout(1200);
  await caption(page, "Planned vs actual: oil 10.5 L against 10 L is +5 %, above the 3 % tolerance, so it is flagged.", 5500);
  await caption(page, "Yield: 188 good packets against 200 planned, −6 %. Cartons: 9, not 10, because 188 packets fill 9 cartons.", 5500);
  await page.mouse.wheel(0, 500);
  await page.waitForTimeout(800);
  await caption(page, "Costing at weighted average: ₹5,855 for the run, ₹31.14 a packet against a ₹50 price, a 37.7 % margin.", 5500);
  await shot(page, "02-production-run");
  await page.goto("/stock");
  await page.waitForTimeout(800);
  await caption(page, "Stock: flour 120 kg, oil 19.5 L. Balances are the running sum of the stock ledger.", 4500);
  await page.getByRole("button", { name: "Finished goods" }).click();
  await page.getByRole("row", { name: /Murukku 200 g/ }).click();
  await page.waitForTimeout(1000);
  await caption(page, "The ledger for Murukku: 50 opening + 188 produced = 238. Rows are never edited; the database refuses updates and deletes.", 6000);
  await shot(page, "03-stock-card");
  await page.getByRole("button", { name: "Close" }).click();
  await signOut(page);

  // ---- Step 4: salesman takes an order -------------------------------------------------------
  await signIn(page, "salesman_a", "Salesman A");
  await page.goto("/sales/new");
  await caption(page, "Salesman A only sees his own customers. The order screens are built for a phone.", 4000);
  await page.getByRole("button", { name: /Retailer A/ }).click();
  await page.waitForTimeout(800);
  await caption(page, "The catalogue shows live availability: 238 packets.", 3500);
  await page.getByLabel("Quantity").first().fill("");
  await page.getByLabel("Quantity").first().pressSequentially("150", { delay: 150 });
  await page.getByRole("button", { name: "Review" }).click();
  await page.waitForTimeout(1000);
  await caption(page, "GST is calculated by the server: ₹7,500 + 2.5 % CGST + 2.5 % SGST (both in Tamil Nadu) = ₹7,875.", 6000);
  await shot(page, "04-order-review");
  await page.getByRole("button", { name: "Submit for approval" }).click();
  await page.waitForTimeout(1000);
  const orderA = (await page.locator("main").innerText()).match(/SO\/\d{4}-\d{2}\/\d{5}/)?.[0] ?? "";
  await caption(page, `Order ${orderA} submitted for approval.`, 3000);
  await signOut(page);

  // ---- Step 5: admin verifies, invoices, dispatches ------------------------------------------
  await signIn(page, "admin", "the admin");
  await caption(page, "The approval queue.", 2500);
  await page.getByRole("link", { name: orderA }).click();
  await page.waitForTimeout(1000);
  await caption(page, "Stock check: 238 on hand, nothing reserved, 238 available. The credit check shows Retailer A is well within its limit.", 6000);
  await shot(page, "05-admin-review");
  await page.getByRole("button", { name: "Approve as ordered" }).click();
  await page.waitForTimeout(1000);
  await caption(page, "Approved: the 150 packets are now reserved for this order.", 3500);
  await page.getByRole("button", { name: "Generate invoice" }).click();
  await expect(page).toHaveURL(/\/admin\/invoices\/\d+/);
  await page.waitForTimeout(1200);
  await caption(page, "Invoice INV/2026-27/00001: gap-free numbering per financial year, even when two admins invoice at the same second.", 6000);
  await caption(page, "Taxable ₹7,500, CGST ₹187.50, SGST ₹187.50, total ₹7,875. A GST-compliant PDF is one click away.", 5000);
  await shot(page, "06-invoice");
  await page.getByRole("button", { name: "Dispatch" }).click();
  await page.getByPlaceholder("TN37 AB 1234").pressSequentially("TN37 AB 1234", { delay: 60 });
  await caption(page, "Dispatch is what moves the stock.", 2500);
  await page.getByRole("button", { name: "Dispatch & update stock" }).click();
  await page.waitForTimeout(1200);
  await page.goto("/stock");
  await page.getByRole("button", { name: "Finished goods" }).click();
  await page.waitForTimeout(800);
  await caption(page, "Murukku: 238 − 150 = 88 packets.", 4000);
  await signOut(page);

  // ---- Step 6: the shortage ------------------------------------------------------------------
  await signIn(page, "salesman_b", "Salesman B");
  await page.goto("/sales/new");
  await page.getByRole("button", { name: /Distributor B/ }).click();
  await page.getByLabel("Quantity").first().fill("");
  await page.getByLabel("Quantity").first().pressSequentially("120", { delay: 150 });
  await caption(page, "Distributor B in Karnataka wants 120 packets. Only 88 are available, but the salesman can still place the order.", 5000);
  await page.getByRole("button", { name: "Review" }).click();
  await page.getByRole("button", { name: "Submit for approval" }).click();
  await page.waitForTimeout(1000);
  const orderB = (await page.locator("main").innerText()).match(/SO\/\d{4}-\d{2}\/\d{5}/)?.[0] ?? "";
  await signOut(page);

  await signIn(page, "admin", "the admin");
  await page.getByRole("link", { name: orderB }).click();
  await page.waitForTimeout(1000);
  await caption(page, "Requested 120, available 88: short by 32. And it's IGST, because Karnataka is another state.", 5500);
  await shot(page, "07-shortage");
  await page.getByLabel("Approved quantity").fill("120");
  await page.getByRole("button", { name: "Approve as ordered" }).click();
  await page.waitForTimeout(1500);
  await caption(page, "Trying to approve all 120 is refused by the server itself, not just the screen. The order stays pending.", 5500);
  await shot(page, "08-refused");

  // ---- Step 7: payment -----------------------------------------------------------------------
  await page.goto("/admin/payments");
  await page.waitForTimeout(800);
  await page.getByRole("combobox").first().selectOption({ label: "Retailer A (Sri Murugan Stores)" });
  await page.getByLabel("Amount (₹)").pressSequentially("4000", { delay: 120 });
  await page.getByLabel("UTR / cheque no").pressSequentially("UTR-1", { delay: 60 });
  await caption(page, "Retailer A pays ₹4,000 by UPI.", 2500);
  await page.getByRole("button", { name: "Record receipt" }).click();
  await page.waitForTimeout(1500);
  await caption(page, "It goes to the oldest invoice first. Outstanding: ₹3,875. A bounced cheque can be reversed later, with a reason.", 6000);
  await shot(page, "09-payment");
  await signOut(page);

  // ---- Owner ---------------------------------------------------------------------------------
  await signIn(page, "owner", "the owner");
  await expect(page).toHaveURL(/\/dashboard/); // own home page, not the page the admin left
  await page.waitForTimeout(1500);
  await caption(page, "The owner's dashboard, live from the books: net sales ₹7,500, collected ₹4,000, receivables ₹3,875.", 6000);
  await page.mouse.wheel(0, 450);
  await page.waitForTimeout(800);
  await caption(page, "One order waiting with a shortage, production yield 94 %, cost ₹31.14 a packet, and stock value by category.", 6000);
  await shot(page, "10-dashboard");
  await signOut(page);

  // ---- Auditor -------------------------------------------------------------------------------
  await signIn(page, "auditor", "the accountant / auditor (read-only)");
  await page.goto("/reports?key=gst-summary");
  await page.waitForTimeout(1500);
  await caption(page, "15 reports, each exportable to CSV, Excel and PDF. GST summary: CGST ₹187.50, SGST ₹187.50.", 5500);
  await shot(page, "11-gst-report");
  await page.goto("/reports?key=consumption-variance");
  await page.waitForTimeout(1500);
  await caption(page, "Consumption variance: the oil line is flagged.", 3500);
  await page.goto("/audit");
  await page.waitForTimeout(1200);
  await page.locator("tr.cursor-pointer", { hasText: "APPROVE" }).first().click();
  await page.waitForTimeout(800);
  await caption(page, "The audit trail: who did what, when, from where, with before and after values. The auditor can see everything and change nothing.", 6500);
  await shot(page, "12-audit");
  await clearCaption(page);

  // ---- Close ---------------------------------------------------------------------------------
  await card(page, "One set of books, from order to audit",
    "Exact decimal money · a stock ledger the database protects · 301 backend tests and 5 browser tests · deploys with docker compose up", 7000);

  const video = page.video();
  await page.close();
  if (video) await video.saveAs(`${OUT}/annapoorna-order-to-audit-demo.webm`);
});
