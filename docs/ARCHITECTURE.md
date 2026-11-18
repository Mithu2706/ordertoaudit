# Architecture & Implementation Plan

Order-to-Audit Management System for a small South Indian packaged-snacks
manufacturer (benchmark product: **Murukku 200 g**).

Flow: **Sales → Order Verification → GST Invoice → Dispatch → Inventory →
Production → Costing → Monthly Audit Reports**.

---

## 1. System context

```
 ┌───────────────┐   HTTPS/JSON (JWT)   ┌──────────────────────────────┐    SQL     ┌────────────┐
 │ React + Vite  │ ───────────────────▶ │ FastAPI                      │ ─────────▶ │ PostgreSQL │
 │ (TypeScript)  │ ◀─────────────────── │  api → services → models     │ ◀───────── │            │
 │ role-based UI │   PDF / XLSX / CSV   │  (business logic lives here) │            └────────────┘
 └───────────────┘                      └──────────────────────────────┘
```

* **Frontend** renders, validates for UX, and calls the API. It contains **no
  business rules** (no GST maths, no stock maths, no costing).
* **Backend** owns every rule: permissions, stock ledger, BOM explosion, GST,
  invoice numbering, costing, variance, reports.
* **Database** is the last line of defence: foreign keys, CHECK constraints,
  unique posting keys and a non-negative running balance.

## 2. Backend layering

```
backend/app/
  core/        config (env vars), database engine/session, security (JWT, hashing)
  models/      SQLAlchemy ORM — one module per domain (schema only, no logic)
  schemas/     Pydantic request/response models (input validation)
  services/    business logic — the only place that writes stock / money
  api/         FastAPI routers — thin: auth + validation + call service
  reports/     report queries + PDF (ReportLab) / XLSX (openpyxl) / CSV writers
  seed/        master data + benchmark scenario loader
backend/alembic/  migrations
backend/tests/    pytest (unit + service + API + benchmark)
```

Rule of thumb for the interview: **routers never touch the ledger directly;
they call a service, and every service that changes stock calls
`inventory_service.post_movement()`**. That single function is where locking,
negative-stock prevention, idempotency and weighted-average valuation live.

### Transaction boundary

One HTTP request = one database transaction (`session.begin()` in a
dependency). A service such as `post_production_run()` issues raw materials,
issues/damages packaging, receives finished goods, stores consumption rows
and variance — all inside that transaction. Any exception → full rollback,
so stock and documents can never be half-posted.

## 3. Key design decisions

### 3.1 Unified item master (class-table inheritance)

`items` holds everything that can have stock: raw materials, packaging and
finished goods. Type-specific attributes live in `raw_materials`,
`packaging_materials`, `products` (1-to-1 on `item_id`). Benefit: the stock
ledger, BOM lines and purchase lines each need **one** foreign key
(`item_id`) instead of three nullable ones.

### 3.2 Ledger-based inventory (the core)

* `stock_movements` is **append-only**. No API updates or deletes it;
  on PostgreSQL a trigger rejects `UPDATE`/`DELETE`. Mistakes are fixed with
  a reversing `ADJUSTMENT` movement.
* `quantity` is **signed**, in the item's **base unit**. A CHECK constraint
  ties sign to type (receipts > 0, issues < 0, adjustments ≠ 0).
* Each row stores `balance_after` and `value_after`. The service locks the
  item row (`SELECT … FOR UPDATE`) so postings for one item are serialised,
  computes the new balance, and the DB CHECK `balance_after >= 0` makes
  **negative stock impossible even if a service has a bug**.
* Current stock = `balance_after` of the latest movement for the item
  (and it always equals `SUM(quantity)` — a test asserts this invariant).
* `posting_key` is UNIQUE (e.g. `PROD:12:ISSUE:3`). Re-posting the same
  document line fails → **no duplicate postings**.
* The original entry (`entered_quantity`, `entered_unit_id`) is kept beside
  the base-unit quantity for traceability ("issued 10.5 L").

### 3.3 Units & conversions

`units` has a dimension (MASS / VOLUME / COUNT). `unit_conversions` holds
global factors (1 kg = 1000 g, 1 L = 1000 ml) and **item-specific** factors
(1 carton of Murukku = 20 packets). Conversion across dimensions is refused.
All conversions use `Decimal`.

### 3.4 Money & quantities

| Kind | Column type | Python |
|---|---|---|
| Money | `NUMERIC(14,2)` | `Decimal`, quantised to 0.01 with `ROUND_HALF_UP` |
| Quantity | `NUMERIC(16,4)` | `Decimal` |
| Unit cost / rate | `NUMERIC(16,6)` | `Decimal` (weighted average needs precision) |
| Percent | `NUMERIC(9,4)` | `Decimal` |

Floats are never used for money or stock.

### 3.5 Weighted-average valuation

On every receipt: `new_avg = (value_before + qty_in × rate) / (qty_before + qty_in)`.
Issues are valued at the current average and reduce `value_after`
proportionally. For the benchmark, flour = (100×42 + 60×45) / 160 = **₹43.125/kg**.

### 3.6 GST

* Company state comes from `company_profile` (Tamil Nadu, code 33).
* Place of supply = customer's state. Same state → **CGST + SGST** (rate/2
  each); different → **IGST**. A CHECK constraint on `invoices` prevents
  mixing both on one invoice.
* Tax computed per line, rounded half-up to paise, summed to header.
* Invoice numbers: `INV/2026-27/00001`, gap-free per financial year
  (April–March) using a locked row in `document_sequences`.
* Cancellation = **credit note** (never deletion). Optional restock posts a
  `SALES_RETURN` movement.

### 3.7 Orders, availability and shortage

`available = on_hand − reserved`, where *reserved* = **approved** but not yet
dispatched quantity (orders APPROVED / INVOICED / PARTIALLY_DISPATCHED).
Approval is the commitment point. It locks the product rows, and approving
more than is available is refused with the exact shortage (Distributor B:
120 ordered − 88 available = **32 short**). The admin may approve a reduced
quantity or correct a price, but must give a reason, which is audited.
Otherwise the order stays pending. Approval also checks the order `version`
the admin reviewed (optimistic lock). Implemented in
`services/availability.py` and `services/sales.py` (Phase 5).

### 3.8 Production engine

1. Create run from active BOM × batch count → planned consumption rows
   (`planned = bom_qty × batch_count`), expected output.
2. Supervisor enters actual issues, good output, damaged output, wastage,
   packaging damage, labour and gas/power cost.
3. `post_production_run()` (one transaction):
   raw-material `PRODUCTION_ISSUE` → packaging `PRODUCTION_ISSUE` (+ `DAMAGE`
   for damaged packaging) → finished-goods `PRODUCTION_OUTPUT` (good output
   only) → cost roll-up → variance % → alert flags against tolerance
   (`app_settings.variance_tolerance_pct`, default 3 %).

### 3.9 Security

* Passwords hashed with bcrypt; JWT access tokens (short expiry, secret from
  env). 
* Every router declares `require_roles(...)`; checked server-side. Salesmen
  see only customers assigned to them and only their own orders.
* Auditor role is read-only (no write endpoints accept it).
* `audit_logs` records who changed what (before/after JSON) for order edits,
  approvals, master-data edits, postings, cancellations.

## 4. Roles → capabilities

| Capability | Salesman | Admin | Production | Owner | Auditor |
|---|:-:|:-:|:-:|:-:|:-:|
| Own customers, create/submit orders | ✔ | | | | |
| Approve/modify/reject orders | | ✔ | | | |
| Invoices, dispatch, credit notes, payments | | ✔ | | | |
| Customer/product/supplier masters | | ✔ | | | |
| Purchases (raw-material receipts) | | ✔ | ✔ | | |
| BOM view / production runs | | view | ✔ | view | view |
| Dashboard | | ✔ | ✔ | ✔ | |
| Reports & exports (read-only) | own sales | ✔ | production | ✔ | ✔ |

## 5. Benchmark — arithmetic checked up front

| Check | Working | Result |
|---|---|---:|
| Flour closing | 100 + 60 − 40 | 120 kg |
| Oil closing | 30 − 10.5 | 19.5 L |
| Spice closing | 5 − 1.2 | 3.8 kg |
| Pouches closing | 500 − (188 good + 6 damaged) | 306 |
| Cartons closing | 30 − 9 | 21 |
| FG after production | 50 + 188 | 238 |
| FG after Retailer A | 238 − 150 | 88 |
| Yield variance | (188 − 200)/200 | −6 % |
| Oil variance | (10.5 − 10)/10 | +5 % |
| Taxable (A) | 150 × 50 | ₹7,500.00 |
| CGST / SGST | 7,500 × 2.5 % | ₹187.50 each |
| Invoice total | 7,500 + 375 | ₹7,875.00 |
| Outstanding (A) | 7,875 − 4,000 | ₹3,875.00 |
| Shortage (B) | 120 − 88 | 32 packets |

Cartons: BOM = 10 cartons per 200 packets → 20 packets/carton.
188 good packets = 9 full cartons (180 packets) + 8 loose packets, so 9
cartons are consumed.

Costing preview (weighted average, to be confirmed by tests in Phase 7):

| Element | Working | ₹ |
|---|---|---:|
| Flour | 40 × 43.125 | 1,725.00 |
| Oil | 10.5 × 140 | 1,470.00 |
| Spice | 1.2 × 200 | 240.00 |
| Pouches | 194 × 2.50 (damaged pouches are a normal production cost) | 485.00 |
| Cartons | 9 × 15 | 135.00 |
| Labour | | 1,200.00 |
| Gas & power | | 600.00 |
| **Total** | | **5,855.00** |
| **Cost per good packet** | 5,855 / 188 | **31.14** (31.143617…) |
| Gross margin | (50 − 31.14)/50 | ≈ 37.7 % |

Unused cartons (21) stay in stock at cost; they are not charged to the run.
All overhead is charged to the run's good output.

## 6. Implementation plan (phases)

| Phase | Scope | Exit criteria |
|---|---|---|
| 1 | Architecture, schema (ORM models + initial migration), ER diagram | Schema creates; constraint tests pass |
| 2 | Auth (JWT, bcrypt), roles, master-data CRUD + audit log | Permission tests pass |
| 3 | Unit conversion, inventory ledger service, purchases | Receipt / negative-stock / duplicate / rollback tests |
| 4 | BOM + production engine, variance | Consumption, output, variance tests |
| 5 | Sales orders, approval, stock validation | Shortage test (32) |
| 6 | GST invoice, numbering, PDF, dispatch, credit notes, payments | GST / numbering / outstanding tests |
| 7 | Costing + reports + CSV/XLSX/PDF exports | Cost-per-packet test, report tests |
| 8 | Frontend: role dashboards, polish | Manual walkthrough of every role |
| 9 | Benchmark end-to-end test, bug fixing | All 13 test areas + benchmark green |
| 10 | README, design note, Docker Compose, demo script | Fresh clone → `docker compose up` works (container steps verified outside Docker; the image build itself is unrun, see DEPLOYMENT.md) |

## 7. Environment notes

* Developed on Windows with Python 3.11 / Node 22.
* PostgreSQL is the target database (via Docker Compose). The schema is kept
  dialect-portable so the fast unit tests also run on SQLite; PostgreSQL-only
  extras (append-only trigger on `stock_movements`) are applied only on
  PostgreSQL. **The authoritative test run is against PostgreSQL.**
