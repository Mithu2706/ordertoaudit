# Inventory Engine

Code: `backend/app/services/inventory.py` (ledger), `units.py` (conversion),
`purchases.py` (receipts), `numbering.py` (document numbers).

## 1. The one rule

**Stock only changes by posting a movement through `post_movement()`.**
No endpoint sets a quantity, and balances are always derived from the ledger.
Production (Phase 4) and dispatch (Phase 6) will call the same function.

## 2. What `post_movement()` does

| Step | Action | Why |
|---|---|---|
| 1 | `SELECT … FROM items WHERE id = ? FOR UPDATE OF items` | Postings for one item are serialised: two dispatches can't both see the last 88 packets |
| 2 | Refuse an already-used `posting_key` (`PUR:12:LINE:3`, `PRD:7:ISSUE:1`, …) | No duplicate postings. The unique index backs this up |
| 3 | Convert the entered quantity to the item's base unit (exact) | The ledger is in one unit per item; what the user typed is stored too |
| 4 | Read the item's latest movement: `balance_after`, `value_after` | Running balance |
| 5a | **Inbound**: value = given cost; avg = total value ÷ total qty | Weighted average |
| 5b | **Outbound**: refuse if qty > balance (error carries `available` / `required` / `shortage`); value = value_before × qty ÷ balance_before | Weighted-average issue cost |
| 6 | Insert the row with the new balance and value | The DB `CHECK (balance_after >= 0)` backs up 5b |

It never commits. The caller's request transaction commits or rolls back
everything together, so a three-line purchase or a production run is
all-or-nothing.

### Extra rules

* **No back-dating** before an item's last movement. This keeps ledger order
  equal to date order, so every `balance_after` is a true point-in-time
  balance and "stock as of date X" is just the last row on or before X.
* **Count items move in whole units** (no 0.5 pouch).
* **Inactive items cannot move.**
* **Taking the last unit clears the value.** Issuing the entire balance
  takes the entire remaining value, so rounding residue never lingers
  (e.g. 3 kg costing ₹100 issued as 1 + 2).

## 3. Weighted-average valuation (benchmark flour)

| Movement | Qty | Value | Balance | Value after | Avg ₹/kg |
|---|---:|---:|---:|---:|---:|
| Opening @ ₹42 | +100 | 4,200.00 | 100 | 4,200.00 | 42.000 |
| Purchase 60 kg @ ₹45 | +60 | 2,700.00 | 160 | 6,900.00 | **43.125** |
| Production issue | −40 | −1,725.00 | 120 | 5,175.00 | 43.125 |

Issue value = 6,900 × 40 / 160 = 1,725.00. The issue value is computed from
the *total value*, not from a rounded unit rate, to avoid drift.

**Purchase cost excludes GST.** A registered manufacturer claims input tax
credit, so the inventory cost is the taxable value (2,700, not 2,835 at 5 %).

## 4. Unit conversion

Conversions form a graph: global edges (1 KG = 1000 G, 1 L = 1000 ML) plus
item-specific edges (1 CTN of Murukku = 20 PKT). A breadth-first search finds
a path, and the factors are multiplied as **exact fractions** (`Fraction`),
so 1/3 × 3 is exactly 1. A result needing more than 4 decimal places is
refused, never silently rounded. Different dimensions (kg ↔ L) only connect
through an item-specific edge.

| Conversion | Result |
|---|---|
| 10,500 ML → L | 10.5 |
| 9 CTN → PKT (Murukku) | 180 |
| 188 PKT → CTN | 9.4 (= 9 full cartons + 8 loose packets) |
| 1 CTN → KG with PKT→G = 200 | 4 (CTN → PKT → G → KG) |

## 5. Purchases

`DRAFT` → (`POST /purchases/{id}/post`) → `POSTED`, or `DRAFT` → `CANCELLED`.

* GST is computed per line. A supplier in the factory's state gets CGST + SGST
  (each half rounded separately); otherwise IGST.
* The same supplier bill can't be entered twice, and finished goods can't
  be purchased.
* Posting writes one `PURCHASE_RECEIPT` per line, with
  `posting_key = PUR:{purchase}:LINE:{line}` and
  `reference_no = PUR/2026-27/00001`.
* A posted purchase can't be edited or cancelled. Reversal will be a purchase
  return (stretch goal).

## 6. Manual movements

| Endpoint | Who | Movement |
|---|---|---|
| `POST /inventory/opening-stock` | Admin | `OPENING`, once per item and only as its first movement |
| `POST /inventory/adjustments` `kind=DAMAGE` | Admin, Production | write-off (`DAMAGE`), numbered `ADJ/2026-27/nnnnn` |
| `POST /inventory/adjustments` `kind=ADJUSTMENT` | Admin only | signed stock-count correction; gains valued at current average |

Every manual movement requires a reason and is audit-logged.

## 7. Document numbering

`document_sequences` keeps one row per (document type, financial year). The
row is locked `FOR UPDATE` and incremented inside the same transaction as
the document, so numbers are unique under concurrency and **gap-free**: a
rolled-back document does not burn a number. The financial year runs
April–March (`2026-11-18` falls in `2026-27`).

## 8. Purchase returns (debit notes)

`POST /purchases/{id}/returns` sends goods back to the supplier against a posted purchase.
Admins and production supervisors can do it. Each return is a debit note numbered
`DN/2026-27/00001`, created and posted in one step, and never edited or deleted.

**Limits**
* Per purchase line, you can return at most what was received minus earlier returns.
* The purchase row is locked, so two simultaneous returns can't over-return. This is tested on
  PostgreSQL, and the test fails without the lock.
* The return date can't be in the future or before the goods were received.
* Count units (pieces) must be whole.

**Stock:** one `PURCHASE_RETURN` movement per line, through `post_movement`. That means no
negative stock, a unique posting key, and valuation at the current weighted-average cost like
every issue. That value is stored on the return as `stock_value`.

**What the supplier is debited:** the original bill rate with the same GST split (CGST + SGST,
or IGST). Returning the rest of a line uses its exact remaining taxable and tax amounts, so all
the returns together never differ from the bill by a paisa.

**Why the two amounts can differ:** the supplier debit (bill rate) and the stock value (average
cost) won't match when prices have moved. Example from the benchmark: 10 kg of flour is debited
at ₹45, which is ₹450, but leaves stock at the ₹43.125 average, which is ₹431.25. The average
cost of the remaining stock doesn't change. Posting the ₹18.75 difference to the books is the
accountant's job; this system doesn't keep a general ledger.

**Reports:** the purchase register shows returns as negative lines, so input GST is net of
returns. The stock ledger shows each `PURCHASE_RETURN` movement with its DN number.

## 9. Known limitations

* Row locks are a no-op on SQLite (the fast test database), where writes are already
  serialised. Concurrency is tested on PostgreSQL (`tests/test_postgres.py`).
