# Sales, GST Billing, Dispatch & Receivables

Code: `backend/app/services/` (`sales.py`, `availability.py`, `gst.py`,
`invoicing.py`, `dispatch.py`, `credit_notes.py`, `payments.py`) and
`app/reports/invoice_pdf.py`.

## 1. Order to cash

```
Salesman  : DRAFT ──submit──▶ SUBMITTED
Admin     : SUBMITTED ──approve (reserves stock)──▶ APPROVED      or ──reject──▶ REJECTED
Admin     : APPROVED ──invoice──▶ INVOICED ──dispatch──▶ PARTIALLY_DISPATCHED / DISPATCHED
Admin     : receipt ──▶ allocated to invoices (oldest first) ──▶ outstanding / ageing
Correction: credit note (cancellation, sales return, price adjustment). Never deletion.
```

## 2. Stock commitment

`available = on hand − reserved`. Here *reserved* is the approved quantity
not yet dispatched. Approval locks the product rows and refuses more than is
available, returning the exact shortage. Dispatch posts `SALES_DISPATCH`
through the ledger and also can't exceed approved − dispatched. So an
"invalid full dispatch" is blocked twice.

## 3. GST rules

| Rule | Implementation |
|---|---|
| Place of supply | Customer's state (snapshotted onto the invoice) |
| Intra-state (TN → TN) | CGST = SGST = rate/2, each rounded half-up to the paisa separately |
| Inter-state (TN → KA) | IGST = rate |
| Rate | From the product master (exercise: simplified flat 5 %), so it is configurable per product |
| Numbering | `INV/2026-27/00001`, gap-free per April–March financial year; invoice dates can't go backwards within a series |
| Mixing guard | DB CHECK: an intra-state invoice can't carry IGST, and vice versa |
| Round-off | Kept at 0.00; totals are exact to the paisa (the column exists if rupee rounding is ever wanted) |
| Cancellation | Credit note only. The invoice stays, with status CANCELLED / PARTIALLY_CREDITED |

## 4. Credit notes

| Type | Effect |
|---|---|
| `CANCELLATION` | Reverses everything not yet credited, using the exact original tax amounts. The order becomes CANCELLED (its reservation is released). If goods were dispatched, `restock=true` is mandatory and they return via `SALES_RETURN` at the cost they left at. Refused if payments are allocated |
| `SALES_RETURN` | Credits up to the dispatched quantity at the invoiced price. With `restock` the goods re-enter stock; without it they are written off |
| `PRICE_ADJUSTMENT` | Credits a taxable amount; quantity is 0 |

A credit can never exceed the invoice's unpaid balance.

## 5. Receipts & outstanding

* Allocation is explicit, or automatic oldest-invoice-first. It never
  exceeds an invoice's balance; any excess stays as an **advance**.
* Invoice balance = total − credit notes − allocations.
* Customer outstanding = Σ invoice balances − unallocated advances.
* Ageing buckets come from `receivable_ageing_buckets` (default `30,60,90`),
  measured in days since the invoice date.

## 6. Benchmark steps 4–7 (verified in `test_sales.py`, `test_billing.py`, and over HTTP)

| Check | Result |
|---|---:|
| Retailer A taxable (150 × ₹50) | ₹7,500.00 |
| CGST 2.5 % / SGST 2.5 % | ₹187.50 / ₹187.50 |
| Invoice total | **₹7,875.00** (Rupees Seven Thousand Eight Hundred Seventy-Five Only) |
| Finished goods after dispatch | 238 − 150 = **88** |
| Distributor B | 120 ordered, 88 available, **short by 32**; full approval refused |
| Distributor B, if invoiced (88 approved) | IGST 5 % = ₹220.00, total ₹4,620.00; dispatching 120 is refused |
| Payment from Retailer A | ₹4,000 allocated to INV/…/00001 |
| Retailer A outstanding | **₹3,875.00** (0–30 bucket) |

Dispatch value: 150 packets leave at the finished-goods weighted average,
7,297.50 × 150 / 238 = ₹4,599.26.

## 7. Credit control (at approval)

The check runs when an admin approves an order:

```
exposure = net outstanding (open invoice balances - unallocated advances)
         + other approved orders not yet invoiced (incl. GST)
         + this order at the quantities and prices being approved (incl. GST)
```

* **No limit:** `credit_limit = 0` means the customer has no limit.
* **Over the limit:** approval is refused with `credit_limit_exceeded` (HTTP 422). The response
  carries the full position: limit, outstanding, open orders, this order, exposure and excess.
* **Ways forward:** the admin can approve a smaller quantity that fits, wait for a payment (which
  lowers outstanding), or approve with a `credit_override_reason`.
* **Overrides are audited:** the audit entry stores the reason and the full credit position,
  and its summary says "approved over the credit limit".
* **Overdue invoices** (older than the customer's `credit_days`) are shown on the review screen
  as a warning. They don't block approval.
* **Concurrency:** the customer row is locked during approval, so two simultaneous approvals
  can't both fit under one limit (tested on PostgreSQL). In the benchmark both orders are for the
  same product, so the stock lock also serialises them there. A one-customer, two-product race
  isn't separately tested.
* **Who sees it:** the review screen shows the credit position to staff; salesmen don't see it.

## 8. Known limitations

* A receipt can't be reversed or re-allocated after it is saved. A
  correction workflow would be a stretch goal.
* Ageing "as of" a past date uses invoices dated up to that date, but
  their *current* balances.
* Invoices are created only from approved orders, one live invoice per
  order (re-billing after a cancellation needs a new order).
* E-invoicing (IRN/QR) and e-way bills are out of scope.
