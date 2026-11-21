# Project Overview: Stack, Scope, Assumptions

## Stack justification

| Layer | Choice | Why |
|---|---|---|
| Database | **PostgreSQL 16** | Real transactions and row locks (`SELECT … FOR UPDATE`) for the stock ledger and numbering. Exact `NUMERIC` for money. CHECK constraints and triggers to enforce ledger rules in the database itself. Free, and runs anywhere. |
| ORM / migrations | **SQLAlchemy 2 + Alembic** | Typed models. Explicit control over transactions and locking. Versioned, reviewable schema migrations (tested down to base and back up). |
| API | **FastAPI + Pydantic 2** | Validation and OpenAPI docs come from the same type hints, and every input is validated before it reaches a service. Fast to develop, with dependency injection for the auth and DB session per request. |
| Auth | **PyJWT + bcrypt** | Standard stateless bearer tokens with the algorithm pinned, and adaptive password hashing. (python-jose was avoided because of open CVEs.) |
| Exports | **ReportLab, openpyxl, csv** | PDF invoices and reports, real `.xlsx` files, and CSV with a BOM so Excel opens Indian text correctly. No heavyweight dependencies (pandas was removed). |
| Frontend | **React 18 + Vite + TypeScript** | Typed API contracts and fast builds. Large ecosystem, easy to hire for. |
| UI | **Tailwind, Framer Motion, Lucide, Recharts** | Consistent design tokens, responsive layouts (the salesman screens are phone-first), light animation, icons and charts. |
| Data fetching | **TanStack Query** | Caching, refetch and invalidation after mutations, without hand-written state management. |
| Tests | **Pytest** (SQLite fast path and PostgreSQL authoritative run) | 287 tests, including an end-to-end HTTP benchmark and real concurrency tests. |
| Deployment | **Docker Compose** | Two containers: PostgreSQL, and the app serving both the API and the built SPA. One command to run anywhere. |

## MoSCoW

Status: ✅ done and tested · 🟡 partial · ❌ not done

### Must have
| Feature | Status |
|---|---|
| Role-based login: Salesman, Admin, Production, Owner, Auditor, enforced in the backend | ✅ 80-case permission matrix |
| Mobile-first salesman order entry (own customers only, live availability) | ✅ |
| Admin order verification with stock check, shortage flag and partial approval with a reason | ✅ |
| GST invoice: CGST + SGST within a state, IGST between states, gap-free numbering per financial year, PDF | ✅ |
| Dispatch that reduces finished-goods stock, partial dispatch | ✅ |
| Ledger-based inventory: no negative stock, no duplicate posting, transactional | ✅ also enforced by database constraints and a trigger |
| Purchases (goods receipt) at weighted-average cost | ✅ |
| BOM and production run: planned vs actual, variance %, alerts beyond tolerance | ✅ |
| Unit conversions (1 carton = 20 packets, kg/g, L/ml) | ✅ exact fractions |
| Payments and outstanding | ✅ FIFO allocation, advances |
| Monthly and audit reports with CSV, Excel and PDF export | ✅ 15 reports |
| Audit trail with before/after values | ✅ |
| Mandatory benchmark reproduced | ✅ [BENCHMARK.md](BENCHMARK.md) |

### Should have
| Feature | Status |
|---|---|
| Credit notes instead of deletion (cancellation, sales return, price adjustment) | ✅ |
| Production costing: cost per packet and gross margin | ✅ |
| Owner dashboard computed live from the books | ✅ |
| Receivables ageing | ✅ |
| Low-stock alerts (reorder levels) | ✅ dashboard and stock screen |
| Versioned, immutable BOMs | ✅ |
| Concurrency safety (simultaneous approvals, postings, numbering, payments) | ✅ tested on PostgreSQL |
| Master-data screens (customers, suppliers, products, raw materials, packaging, users, company, settings) | ✅ one screen with a tab per record type and role-aware tabs and buttons; edits send only changed fields; server validation shown inline |

### Could have
| Feature | Status |
|---|---|
| Stock adjustments with a reason | ✅ API; 🟡 no dedicated UI form |
| Credit-limit enforcement at approval | ✅ exposure includes outstanding and approved-not-invoiced orders; audited override with a reason; overdue warning |
| Payment reversal (bounced cheque, failed transfer) | ✅ receipt kept and marked reversed; invoices re-open; collections show a negative line; audited |
| Re-allocating a receipt to other invoices | ❌ reverse it and record a new receipt instead |
| Purchase returns (debit notes) | ✅ against posted purchases, line by line; stock out through the ledger at average cost; supplier debited at bill rate and GST; register shows negative lines |
| Code-split routes and a smaller first load | 🟡 vendor chunks split; routes are not lazy-loaded |
| Automated browser (UI) tests | ❌ checked by hand |

### Won't have (this prototype)
* GST portal integration: e-invoice IRN and QR, e-way bill, GSTR filing exports.
* Multi-warehouse stock, batch or lot and expiry tracking, FIFO valuation.
* Offline mode for salesmen, SMS or WhatsApp notifications.
* Multi-company or multi-currency.

## Assumptions

**Stock and production**
1. **Opening finished goods** (50 packets) are valued at the standard batch cost at opening
   rates: ₹28.85 per packet. The brief gives no figure.
2. **Labour and gas/power are entered with a run's actuals**, so that finished goods enter stock
   at their full cost.
3. **Packaging is planned against good output**, and count items (cartons) round down to full
   units: 188 packets need 9 cartons.
4. **Damaged pouches are a cost of the run** and show up as packaging variance. Damaged finished
   packets are never stocked.
5. **Purchase cost excludes GST**, because input tax credit is claimed. Stock is valued net of tax.
6. **Weighted-average cost** is used for all items. Issues are valued at the average at the moment
   of posting.

**Sales and billing**

7. **Approval reserves stock.** Available = on hand − (approved but not yet dispatched).
8. **GST is decided by the place of supply**, which is the customer's state, against the
   company's state (Tamil Nadu, 33). Rates come from the product master, 5 % for Murukku.
9. **No invoice round-off.** Totals are exact to the paisa (the `round_off` field exists, set to 0).
10. **Indian financial year** April–March for numbering: `INV/2026-27/00001`.
11. **Payments allocate oldest invoice first** unless they are allocated by hand. The excess becomes an advance.
12. **Variance tolerance is 3 %**. It is a setting, copied onto each run when it is created.

## Known limitations

* Ageing "as of" a past date uses invoices dated up to that date, but with their *current* balances.
* One live invoice per order. Re-billing after a cancellation needs a new order.
* JWTs are kept in `localStorage`. httpOnly cookies with CSRF protection would be the hardening step for internet exposure.
* The JWT has no refresh token. Users sign in again after 8 hours (configurable).
* Recharts 2.x is in maintenance mode. It works, but upgrading to v3 is a future task.
* The Docker image and Compose file were written and checked by running the same commands
  outside Docker (see [DEPLOYMENT.md](DEPLOYMENT.md#what-has-been-verified)), but **`docker compose up` itself has not
  been run** in the development environment, because Docker isn't installed there.
