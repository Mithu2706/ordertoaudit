# Demo Video Script (8 minutes)

## Setup (before recording)

1. Start fresh, with production already posted (benchmark steps 1–3):
   `docker compose down -v`, then `docker compose up -d` (default `SEED=scenario`, `SCENARIO_UNTIL=3`).
   Without Docker, run `python -m app.prepare` on an empty database with `SEED=scenario`.
2. Open two browser windows:
   * **left:** phone size (DevTools device mode, 375 px) for the salesman;
   * **right:** desktop for everyone else.
3. Every demo account's password is `Demo@1234`. The login screen has buttons that fill in the username.

Timings are cumulative. The **bold** lines are what to say; the rest is what to click.

---

### 0:00–0:40 · The problem and the promise
**"Annapoorna Snacks makes Murukku in Coimbatore. Orders arrive on paper and stock is counted,
not known. Invoices are typed by hand, and nobody knows what a packet really costs. This system
connects the whole chain, from order to audit, in one set of books. Every number on screen is
derived from posted documents. There is no hand-typed figure anywhere."**

Show the login screen, with role buttons for Salesman, Admin, Production, Owner and Auditor.

### 0:40–1:50 · Production already happened (steps 1–3)
Sign in as **production** (desktop) → **Production** → open **PRD/…/00001**.

- **"This morning we bought 60 kg of flour at ₹45 and ran one batch planned at 200 packets."**
- Point to the planned vs actual table:
  * oil 10.5 L vs 10 L: **+5 %**, red alert;
  * yield 188 vs 200: **−6 %**;
  * pouches +3.19 % (6 damaged);
  * cartons 9, not 10. **"188 packets fill 9 cartons; the system plans packaging against good output."**
- Point to costing: **"₹5,855 total, so ₹31.14 a packet against a ₹50 selling price: a 37.7 % margin.
  Flour is costed at the weighted average of old and new stock, ₹43.125."**
- **Stock** screen: flour 120 kg, oil 19.5 L, pouches 306, Murukku 238. Click Murukku to open its
  **ledger**: **"Stock is never edited. It is the running sum of these movements, and the database
  itself refuses updates or deletes."**

### 1:50–2:50 · Salesman takes an order on the phone (step 4)
Phone window: sign in as **salesman_a** → **New order**.

- **"Salesman A only sees his own customers."** Pick **Retailer A (Sri Murugan Stores)**.
- The catalogue shows **238 available**. Tap **+** up to 150 (or type 150) → **Review**.
- **"GST is worked out by the server, not the phone: ₹7,500 plus 2.5 % CGST and 2.5 % SGST, because
  the customer is in Tamil Nadu like us. Total ₹7,875."** → **Submit**.

### 2:50–4:10 · Admin verifies, invoices and dispatches (step 5)
Desktop: sign in as **admin** → **Orders** (approval queue).

- Open the order. The stock check shows on hand 238, reserved 0, **available 238**, no shortage.
  → **Approve**.
- **Generate invoice** → **INV/2026-27/00001**. **"Numbering is gap-free per financial year. Even two
  admins invoicing at the same second get 00001 and 00002; we test exactly that."**
- **Download PDF** and show it: GSTINs, HSN code, CGST/SGST split, amount in words.
- **Dispatch** (vehicle `TN37 AB 1234`). **"Dispatch is what moves stock: 238 to 88."**

### 4:10–5:10 · The shortage (step 6)
Phone: sign out → **salesman_b** → order **120** packets for **Distributor B** (Karnataka) → submit.
**"He sees only 88 available, but can still place the order. The admin decides."**

Desktop admin → **Orders**: the order shows an amber **short** badge. Open it:
* requested 120, available 88, **short by 32**;
* the tax is **IGST**, because Karnataka is another state.

- Try **Approve** for the full quantity: the backend refuses. **"This isn't just a disabled button;
  the API itself won't promise stock it doesn't have."**
- Show the partial-approval option (88, with a mandatory reason), then leave the order **pending**,
  as in the benchmark.

### 5:10–5:50 · Payment (step 7)
Admin → **Payments** → Retailer A → **₹4,000**, UPI, reference `UTR-1` → save.
**"It is allocated to the oldest invoice. Outstanding is now ₹3,875, and ageing puts it in the
0–30 day bucket."**

### 5:50–6:50 · Owner's view
Sign in as **owner** → **Dashboard**.
- **"All live from the books":**
  * net sales ₹7,500;
  * collected ₹4,000;
  * receivables ₹3,875;
  * one order awaiting approval, flagged short;
  * production yield 94 %, with one run carrying variance alerts;
  * latest cost ₹31.14 per packet at a 37.71 % margin;
  * stock value by category.
- Click the latest run to drill down to the production detail.

### 6:50–7:40 · Auditor: reports and the trail
Sign in as **auditor** (read-only).
- **Reports** → **GST summary**: CGST ₹187.50, SGST ₹187.50. Click **Excel**, then **PDF**.
- **Consumption variance**: the oil line is flagged. **Outstanding & ageing**: ₹3,875.
- **Audit trail**: expand the approval entry. **"Who did it, when, from where, and the before and
  after values. The auditor can see everything and change nothing; every endpoint checks the role
  on the server."**

### 7:40–8:00 · Close
**"One set of books from order to audit, with exact decimal money and a ledger the database
protects. 263 automated tests, including the full benchmark over HTTP and real concurrency tests
on PostgreSQL. It deploys with one `docker compose up`."**

---

## Backup lines (if asked)
* **What stops a customer running up unpaid bills?** Credit control at approval. Exposure is
  what they owe, plus approved orders not yet invoiced, plus this order. Above the limit the
  server refuses, unless the admin records an override reason, which is audited. Demo it by
  setting Retailer A's limit to ₹5,000 in Master data, then ordering 50 packets.
* **How do you add a new customer?** Admin → **Master data** → **New customer**. Enter a
  Karnataka GSTIN for a Tamil Nadu customer and the server refuses it: the GSTIN's state digits
  and check digit are both verified. Every edit then shows up in the audit trail as before → after.
* **Why weighted average?** It's simple and stable for a small manufacturer, and the cost changes
  only when stock is bought or made.
* **What if two admins approve at once?** One wins. The other gets "order changed, reload".
  This is tested on real PostgreSQL with overlapping transactions.
* **Can an invoice be deleted?** No. You raise a credit note: cancellation, return or price
  adjustment. Returns go back into stock at their dispatch cost.
