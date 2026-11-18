# Reports, Exports & Costing

Code: `backend/app/reports/` (`framework.py`, `builders.py`, `exporters.py`) and
`app/services/costing.py`.

## 1. How it works

Each report is one function that returns a `Report`: typed columns (text,
date, qty, money, rate, pct, bool) plus rows of exact `Decimal` values. The
same object is rendered four ways, so the formats can't disagree:

| Format | Notes |
|---|---|
| JSON | Amounts are exact strings, never floats, and include a totals row |
| CSV | UTF-8 with BOM (opens correctly in Excel), plain numbers, TOTAL row |
| Excel (.xlsx) | Title, filter line, frozen header, numeric cells with number formats (`#,##0.00`), TOTAL row |
| PDF | Landscape A4, company and period header, wrapped text, right-aligned numbers, notes |

```
GET /api/reports                                   reports your role can run
GET /api/reports/{key}?date_from=&date_to=&format=json|csv|xlsx|pdf
                       [&item_id=|customer_id=|product_id=]
```

The default period is the 1st of the current month to today, i.e. a monthly
report. Role access is declared on each report and checked server-side.

## 2. Catalogue

| Key | Report | Roles |
|---|---|---|
| `sales-register` | Every GST invoice with its tax split | Admin, Owner, Auditor |
| `customer-sales` | Invoiced, credited and net per customer | + Salesman (own customers only) |
| `product-sales` | Quantity, average rate and value per product | Admin, Owner, Auditor |
| `gst-summary` | Outward supplies by place of supply, supply type, HSN and rate, **net of credit notes** | Admin, Owner, Auditor |
| `purchase-register` | Posted receipts with input GST | Admin, Production, Owner, Auditor |
| `raw-material-stock` / `packaging-stock` / `finished-goods-stock` | Opening, in, out, closing, weighted-average cost, value, low-stock flag | Admin, Production, Owner, Auditor |
| `stock-ledger` | Every movement with running balance and value (`item_id` → stock card) | Admin, Production, Owner, Auditor |
| `production` | Runs: expected / good / damaged, yield variance, cost | Admin, Production, Owner, Auditor |
| `consumption-variance` | Planned vs actual per component, variance %, tolerance, alert | Admin, Production, Owner, Auditor |
| `yield-wastage` | Yield %, damaged output, process wastage, packaging spoilage | Admin, Production, Owner, Auditor |
| `product-costing` | Cost build-up, cost per good unit, **gross margin** | Admin, Production, Owner, Auditor |
| `collections` | Receipts and their allocation | Admin, Owner, Auditor |
| `outstanding-ageing` | Balance per customer as at period end, with ageing buckets | Admin, Owner, Auditor |

All figures are read from posted documents and the stock ledger. Nothing is
hard-coded.

## 3. Costing (benchmark)

| Element | ₹ |
|---|---:|
| Material (flour 1,725 + oil 1,470 + spice 240, at weighted average) | 3,435.00 |
| Packaging (pouches 485 incl. 6 damaged + cartons 135) | 620.00 |
| Labour | 1,200.00 |
| Gas & power | 600.00 |
| **Total** | **5,855.00** |
| **Cost per good packet** (÷ 188) | **31.143617** |
| Selling price (before GST) | 50.00 |
| **Gross margin per packet** | **18.856383** |
| **Gross margin %** | **37.71 %** |

Margin % = (price − cost per unit) / price × 100. The margin is also shown on
each production run (`GET /production-runs/{id}`).

## 4. Benchmark step 9, verified by `tests/test_reports.py`

| Report | Benchmark figure |
|---|---|
| Sales register | 1 invoice: 7,500.00 + 187.50 + 187.50 = 7,875.00 (Distributor B is pending, so not invoiced) |
| GST summary | 33 Tamil Nadu, intra-state, HSN 21069099 @ 5 %: taxable 7,500, tax 375 |
| Purchase register | Kovai Flour Mills, KFM-001, 2,700.00 |
| Raw-material stock | Flour 100 + 60 − 40 = 120 kg @ 43.125 = 5,175.00; oil 19.5 L; spice 3.8 kg |
| Packaging stock | Pouches 306 (194 out); cartons 21 |
| Finished goods | 238 in, 150 out, **88** closing, value 2,698.24 |
| Stock ledger (pouch) | Opening 500 → issue 188 → damage 6 → 306 |
| Production / variance | Yield −6 %, oil +5 % (alert), pouches +3.19 % (alert) |
| Product costing | 5,855.00, 31.143617 per packet, margin 37.7128 % |
| Collections / outstanding | 4,000 received → Retailer A **3,875.00** outstanding (0–30 days) |

## 5. Notes

* `pandas` was dropped: openpyxl writes Excel directly, and pandas would add
  around 50 MB to the image with no benefit here.
* GST summary rows for credit notes are negative. The totals row is the net
  outward liability.
* For the period end, outstanding/ageing includes invoices dated up to that
  date at their **current** balances (see BILLING.md, known limitations).
