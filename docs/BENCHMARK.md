# Benchmark Scenario: Expected Results and How They Arise

The mandatory scenario runs on a fresh database. It is verified in three places:

| Where | How |
|---|---|
| `tests/test_e2e_benchmark.py` | The whole scenario over HTTP with real logins, on SQLite and PostgreSQL |
| `python -m app.seed.scenario` | Prints expected vs actual. On PostgreSQL, 17 of 17 checks match |
| The UI | Phase 8 walkthrough; the [demo script](DEMO_SCRIPT.md) repeats steps 4–7 live |

## Starting position (seed)

| Item | Opening stock | Unit cost |
|---|---:|---:|
| Flour (RM-FLOUR) | 100 kg | ₹42.00 |
| Cooking oil (RM-OIL) | 30 L | ₹140.00 |
| Salt and spice mix (RM-SPICE) | 5 kg | ₹200.00 |
| 200 g pouch (PM-POUCH200) | 500 pcs | ₹2.50 |
| Shipper carton (PM-CARTON), 20 packets each | 30 pcs | ₹15.00 |
| Murukku 200 g (FG-MUR200) | 50 packets | ₹28.85 * |

\* The brief gives no cost for the opening packets. They are valued at the standard batch cost
at opening rates, including the stated labour and gas: ₹5,770 / 200 = ₹28.85.

**BOM v1, per batch of 200 packets:**
* flour 40 kg;
* oil 10 L;
* spice 1.2 kg;
* 200 pouches;
* 10 cartons.

**Selling price and tax:** ₹50 per packet. GST is 5 % and the HSN code is 21069099.

**The company is in Tamil Nadu (state code 33):**
* Retailer A is in Tamil Nadu (33), handled by `salesman_a`;
* Distributor B is in Karnataka (29), handled by `salesman_b`.

## Step by step

| Step | Action | Effect |
|---|---|---|
| 1 | Purchase 60 kg flour at ₹45 | Flour 100 → **160 kg**. Average cost becomes (100×42 + 60×45) / 160 = **₹43.125** |
| 2 | Production run: 1 batch, planned 200 packets | Plan: flour 40, oil 10, spice 1.2, pouches 200, cartons 10 |
| 3 | Actuals: flour 40, oil **10.5**, spice 1.2, **188 good** packets, 6 pouches damaged, 9 cartons, labour ₹1,200, gas ₹600 | Components issued, 188 packets received (see below) |
| 4 | Salesman A orders 150 packets for Retailer A | Order submitted. Available stock is 238, so there is no shortage |
| 5 | Admin approves, invoices and dispatches | Invoice ₹7,875 (intra-state). Finished goods 238 → **88** |
| 6 | Salesman B orders 120 packets for Distributor B | Admin review shows available 88, **short by 32**. Full approval is refused |
| 7 | Retailer A pays ₹4,000 by UPI | Allocated to the invoice. Outstanding **₹3,875** |
| 8–9 | Reports and costing | Stock, GST, variance, ageing, cost per packet |

## Expected results

| Check | Working | Result |
|---|---|---:|
| Flour closing | 100 + 60 − 40 | **120 kg** |
| Oil closing | 30 − 10.5 | **19.5 L** |
| Spice closing | 5 − 1.2 | 3.8 kg |
| Pouch closing | 500 − (188 used + 6 damaged) | **306** |
| Carton closing | 30 − 9 | 21 |
| Finished goods after production | 50 + 188 | **238** |
| Finished goods after Retailer A dispatch | 238 − 150 | **88** |
| Yield variance | (188 − 200) / 200 | **−6 %** |
| Oil variance | (10.5 − 10) / 10 | **+5 %** (above the 3 % tolerance, so it alerts) |
| Pouch variance | (194 − 188) / 188 | +3.19 % (alert) |
| Retailer A taxable value | 150 × ₹50 | **₹7,500.00** |
| CGST / SGST (Tamil Nadu → Tamil Nadu) | 7,500 × 2.5 % each | **₹187.50 + ₹187.50** |
| Invoice total | 7,500 + 375 | **₹7,875.00** |
| Retailer A outstanding | 7,875 − 4,000 | **₹3,875.00** |
| Distributor B shortage | 120 − 88 | **32 packets** |
| IGST if B's 88 packets were approved (Tamil Nadu → Karnataka) | 88 × 50 × 5 % | ₹220.00 |

### Why some of these come out the way they do

* **Cartons: 9, not 10.** Packaging is planned against *good output*. 188 packets make 9 full
  cartons (180 packets) plus 8 loose packets. A part-carton is not used, so it isn't planned.
  Rounding down applies only to items counted in whole units.
* **Pouches: variance is measured against good output.** 194 pouches were consumed (188 filled
  plus 6 damaged) against 188 planned. The damaged pouches are a real cost of the run and show
  up as variance.
* **Yield is measured against the batch plan.** The BOM promises 200 packets per batch, so
  188 is −6 %.
* **The shortage blocks approval in the backend, not just the screen.** The API refuses to
  approve the full 120 (HTTP 422, with the shortage in the message). The admin may approve up
  to 88 with a reason, or leave the order pending.
* **Outstanding.** The ₹4,000 is allocated oldest-invoice-first to INV/…/00001. Any excess
  would be held as an advance, not lost.

## Production costing (step 9)

Components are issued at weighted-average cost at the moment of posting:

| Element | Working | ₹ |
|---|---|---:|
| Flour | 40 × 43.125 | 1,725.00 |
| Oil | 10.5 × 140 | 1,470.00 |
| Spice | 1.2 × 200 | 240.00 |
| Pouches | 194 × 2.50 (damaged pouches included) | 485.00 |
| Cartons | 9 × 15 | 135.00 |
| Labour | entered with the run | 1,200.00 |
| Gas and power | entered with the run | 600.00 |
| **Total run cost** | | **5,855.00** |
| **Cost per good packet** | 5,855 / 188 | **31.143617** (displayed as ₹31.14) |
| Gross margin per packet | 50 − 31.143617 | 18.856383 |
| **Gross margin** | 18.856383 / 50 | **37.7128 %** |

The 188 new packets enter stock at ₹31.143617. The 50 opening packets were at ₹28.85. The
finished-goods average after production is therefore (50 × 28.85 + 5,855) / 238 = ₹7,297.50 / 238 =
₹30.661765 per packet. That is the cost at which Retailer A's 150 packets leave stock.
