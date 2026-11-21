# Design Note: Order-to-Audit System

*Annapoorna Snacks, a small South Indian packaged-snacks manufacturer. Two pages.*

## 1. Problem

Orders are taken on paper by salesmen and re-keyed in the office. Stock is counted rather than
derived. Invoices are typed by hand, and production consumption is never compared with the recipe.
At month end nobody can say what a packet actually cost, or why the books and the shelf disagree.
The system joins **Sales → Verification → GST Invoice → Dispatch → Inventory → Production →
Costing → Audit** into one record, so every figure can be traced back to the document that caused it.

## 2. Architecture

```
Browser (React SPA, role-specific screens)
   │  HTTPS, JSON, bearer JWT
FastAPI routers  ── validate (Pydantic) · authenticate · authorise (role check)
   │
Services         ── all business rules; one request = one DB transaction
   │
PostgreSQL       ── constraints, append-only ledger trigger, row locks
```

* **Business logic lives only in the services.** The UI displays what the API returns: totals,
  GST, availability, shortages and costs are never recomputed in the browser. Routers stay thin,
  so the same services drive the API, the seed and the benchmark runner.
* **One transaction per request.** It commits on success and rolls back fully on any error, so
  a dispatch never moves stock without also updating the order and the audit log.
* **Deployment:** one container serves the API and the built SPA, alongside one PostgreSQL
  container. Being on the same origin means no CORS in production.

## 3. Key decisions

**Ledger-based inventory.** Stock is never a column someone edits. Every change is a row in
`stock_movements`: signed quantity, value, running balance and running value. One function,
`post_movement`, is the only way to write that table. It:
* locks the item row, so concurrent postings queue rather than race;
* converts the quantity to the item's base unit;
* refuses negative stock and back-dated postings;
* values issues at the weighted-average cost;
* requires a unique `posting_key`, so posting the same document twice is impossible.

The database enforces the same rules again with CHECK constraints (balance ≥ 0, sign matches
movement type) and a trigger that rejects UPDATE and DELETE. Mistakes are corrected with
reversing entries, never edits.

**Exact numbers.** Money and quantities are `Decimal` end to end: `NUMERIC` in PostgreSQL,
strings in JSON, and string formatting in the browser. Rounding rules are fixed in one
module: money 2 dp, quantity 4 dp, rate 6 dp, all half-up. Unit conversion
(1 carton = 20 packets) uses exact fractions. A conversion that cannot be represented exactly
is refused rather than silently rounded.

**Production engine.** BOMs are versioned and become immutable once used, so a run always
records the recipe it was planned against. Raw material is planned per batch. Packaging is
planned against good output: 188 packets need 188 pouches and 9 full cartons, not 10. The
variance for each component is (actual − planned) / planned. Any component outside the
tolerance raises an alert; the tolerance (3 %) is a setting, copied onto each run. Posting a
run issues every component and receives the finished goods in one transaction. The run is
costed at weighted average plus the labour and fuel entered.

**Sales and stock promises.** Approval *reserves* stock:
available = on hand − (approved − dispatched). An order larger than what is available can be
approved only partially, and the admin must give a reason. Approvals use optimistic locking
(the order version), so an admin cannot approve an order that changed after they reviewed it.

**GST invoicing.** The supply type comes from the supplier's and customer's states. Within a
state the tax is CGST + SGST (half each); between states it is IGST. Invoice numbers are
gap-free per financial year (`INV/2026-27/00001`): a locked sequence row is incremented inside
the invoice's own transaction. Invoices are never deleted. Corrections are credit notes:
cancellation, sales return (restocked at dispatch cost) or price adjustment.

**Receivables.** Payments allocate oldest invoice first, unless the admin allocates them by
hand. Any excess is held as an advance. Ageing buckets are a setting.

**Security.**
* Passwords are hashed with bcrypt.
* JWTs are signed with HS256, and the algorithm is pinned. In the browser the token lives in an
  httpOnly `SameSite=Strict` cookie that page scripts can't read. Writes must echo a CSRF token in
  a header (double-submit). API clients use a bearer header instead.
* The user's role is reloaded from the database on every request, so deactivating a user
  takes effect immediately.
* Every endpoint declares its allowed roles, and an 80-case test matrix checks them.
* Salesmen see only their own customers and orders.
* Only an owner can create or modify owner accounts.
* In production the app refuses to start without a strong JWT secret.

**Audit trail.** Every create, approval, posting, cancellation, payment and login is written in
the same transaction as the change. Each entry records who made it, when, from which IP, the
before and after values, and the reason given.

## 4. Correctness under concurrency

Small businesses still have two people clicking at once. The following run on real PostgreSQL
with genuinely overlapping transactions, and each test fails if the relevant lock is removed:
* simultaneous stock issues;
* duplicate postings;
* two competing approvals for the same stock;
* a double-clicked approval;
* the first invoice of a new financial year;
* two payments against one invoice.

That testing found two bugs, both now fixed (details in [TESTING.md](TESTING.md)):
* a locked read could return stale data that was already loaded in the session;
* the first-of-year sequence row could be created twice.

## 5. Benchmark result

Every mandatory figure is reproduced exactly: flour 120 kg, oil 19.5 L, pouches 306, finished
goods 238 then 88, yield −6 %, oil +5 %, Retailer A ₹7,875 with ₹3,875 outstanding, and
Distributor B short by 32. The run costs ₹31.14 a packet, a 37.71 % margin. It is checked by an
end-to-end HTTP test, by the scenario runner on PostgreSQL, and in the UI. Workings are in
[BENCHMARK.md](BENCHMARK.md).

## 6. Trade-offs and limits

* **Weighted average, not FIFO, for valuation.** It is simpler, stable, and acceptable for a
  small manufacturer. Batch and expiry tracking is out of scope.
* **Single company and single warehouse.** No multi-location stock.
* **No GST portal integration.** That means no e-invoice IRN, no e-way bill and no GSTR export.
  The GST summary report is the hand-off to the accountant.
* **Added after the first release:** credit limits, payment reversal and re-allocation,
  purchase returns (debit notes), master-data screens and browser tests. See
  [BILLING.md](BILLING.md), [INVENTORY.md](INVENTORY.md) and [PROJECT.md](PROJECT.md#moscow).
