# BOM & Production Engine

Code: `backend/app/services/bom.py`, `production.py`, `variance.py` (pure maths).

## 1. BOMs are versioned and immutable

A BOM holds the finished product, its batch yield (e.g. 200 PKT) and its
components with a quantity per batch in any convertible unit. **There is no
edit.** A production run that used v1 must always show v1's standard, so a
change means creating v2. Activating v2 retires v1, and a partial unique index
guarantees at most one active version per product. Components must be raw or
packaging materials, and their units are validated through the unit converter
(so 10 CTN = 200 PKT is a valid way to state the yield).

## 2. Run lifecycle

```
POST /production-runs            DRAFT: planned quantities from the BOM
PUT  /production-runs/{id}/actuals  DRAFT: actual usage, damaged packaging, output, costs
POST /production-runs/{id}/post     POSTED: one transaction, then immutable
POST /production-runs/{id}/cancel   CANCELLED (drafts only)
```

## 3. What "planned" means

| Component | Planned quantity | Reason |
|---|---|---|
| Raw materials | BOM qty × batch count, fixed at creation | Ingredients are committed when the batch starts |
| Packaging | BOM qty per packet × **actual good output**, rounded **down** for count items, set at posting | Pouches and cartons are used per packet packed. The yield shortfall is already measured by yield variance, so it shouldn't count twice |
| Expected output | BOM yield × batch count | |

This is a design decision. Measuring packaging against the BOM batch quantity
(200 pouches, 10 cartons) would report cartons at −10 %, an "under-use" that
is really just the lower yield.

## 4. Posting (one transaction)

1. `PRODUCTION_ISSUE` for each raw material's actual quantity.
2. `PRODUCTION_ISSUE` for packaging used, plus `DAMAGE` for packaging spoiled
   while packing.
3. `PRODUCTION_OUTPUT` of the **good** output only, valued at the run's total
   cost.
4. Costs, consumption rows, variance % and alert flags are saved on the run.

All movements go through `post_movement()`, so a shortage at any step (e.g.
oil) raises an error and rolls back the flour already issued in the same
request. A test asserts exactly this. Posting keys
(`PRD:{run}:ISSUE:{item}`, `PRD:{run}:DAMAGE:{item}`, `PRD:{run}:OUTPUT`)
make double posting impossible.

## 5. Variance

* Consumption variance % = (actual + damaged − planned) / planned × 100
* Yield variance % = (good output − expected) / expected × 100

An alert is raised when |variance| is **strictly greater** than the tolerance.
The tolerance comes from `app_settings.variance_tolerance_pct` (default 3 %,
editable by admin or owner) and is **snapshotted onto the run** when it is
created, so changing the setting later doesn't rewrite past alerts.

## 6. Benchmark run (verified by `test_benchmark_production_run` and over HTTP)

| Component | Planned | Used | Variance | Alert | Cost ₹ |
|---|---:|---:|---:|:-:|---:|
| Flour | 40 kg | 40 kg | 0 % | | 1,725.00 (40 × 43.125 weighted avg) |
| Oil | 10 L | 10.5 L | **+5 %** | ✔ | 1,470.00 |
| Spice mix | 1.2 kg | 1.2 kg | 0 % | | 240.00 |
| Pouches | 188 | 188 + 6 damaged = **194** | +3.19 % | ✔ | 485.00 |
| Cartons | 9 | **9** | 0 % | | 135.00 |
| **Yield** | 200 | 188 | **−6 %** | ✔ | |

* **Pouches: 188 good + 6 damaged = 194 consumed.** Each good packet uses one
  pouch, and 6 pouches were spoiled while packing. They are posted as
  `PRODUCTION_ISSUE 188` and `DAMAGE 6`, so 500 − 194 = **306** remain. The
  6 spoiled pouches exceed the 3 % tolerance against a standard of 188, so
  they raise an alert. That is the expected outcome of the rule, not a defect.
* **Cartons: 9.** One carton holds 20 packets (BOM: 10 cartons per 200
  packets). 188 packets fill 9 cartons (180 packets) with 8 packets loose.
  A part-filled carton isn't packed, so the standard is ⌊9.4⌋ = 9 and
  30 − 9 = **21** remain.
* **Stock after posting:** flour 120 kg, oil 19.5 L, spice 3.8 kg,
  pouches 306, cartons 21, finished goods 50 + 188 = **238 packets**.

## 7. Run costing

| Element | ₹ |
|---|---:|
| Raw material (at weighted-average cost) | 3,435.00 |
| Packaging, including the 6 damaged pouches | 620.00 |
| Labour | 1,200.00 |
| Gas & power | 600.00 |
| **Total** | **5,855.00** |
| **Cost per good packet** (÷ 188) | **31.143617** |

Treatment:

* **Damaged pouches** are a normal production loss, charged to the run.
* **Damaged finished packets** never enter stock. Their cost is absorbed by
  the good packets.
* **Unused cartons (21)** stay in stock at cost and are not charged.
* **Overheads** (labour, gas/power) are charged to the run's good output.
* The finished-goods receipt is valued at the full run cost, so finished
  goods carry a true weighted-average cost:
  (50 × 28.85 + 5,855) / 238 = **₹30.661765** per packet.

## 8. Assumptions

* **Opening finished goods (50 packets)** have no cost in the brief. They are
  valued at the BOM standard at opening rates, including a batch's labour and
  gas: (40×42 + 10×140 + 1.2×200 + 200×2.50 + 10×15 + 1,200 + 600) / 200 =
  **₹28.85**. See `app/seed/benchmark.py`.
* **Labour and gas/power are entered with the run's actuals**, i.e. when the
  run is closed. The brief lists costing as step 8, but the finished-goods
  value has to include these costs when they enter stock, so they can't be
  added after posting.
* **Spoiled raw material** is part of a raw material's actual consumption. A
  separate damaged quantity is only accepted for packaging.
* **Substitutions are not supported.** A run consumes exactly the components
  of its BOM.
* **HSN 21069099** is used for Murukku with the exercise's simplified 5 % GST.

## 9. Seeding

```powershell
cd backend
.venv\Scripts\python -m app.seed --benchmark
```

This loads suppliers, the three raw materials, two packaging items, the
product (1 CTN = 20 PKT), Retailer A (Tamil Nadu, `salesman_a`), Distributor
B (Karnataka, `salesman_b`), the opening stock dated the 1st of the current
month, and BOM v1. It is idempotent.
