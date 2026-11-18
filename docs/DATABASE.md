# Database Schema & ER Diagram

32 tables, PostgreSQL target. Source of truth: `backend/app/models/*.py`;
migration: `backend/alembic/versions/0001_initial_schema.py`.

## ER diagram

The diagram is split into three views so each stays readable. GitHub renders Mermaid natively.

### A. Masters, BOM and inventory

```mermaid
erDiagram
    roles ||--o{ users : "has"
    states ||--o{ customers : "located in"
    states ||--o{ suppliers : "located in"
    states ||--|| company_profile : "factory state"
    users ||--o{ customers : "assigned salesman"

    units ||--o{ items : "base unit"
    units ||--o{ unit_conversions : "from / to"
    items ||--o{ unit_conversions : "item-specific (e.g. CTN=20 PKT)"

    items ||--o| raw_materials : "is-a"
    items ||--o| packaging_materials : "is-a"
    items ||--o| products : "is-a"

    products ||--o{ boms : "has versions"
    boms ||--|{ bom_items : "contains"
    items ||--o{ bom_items : "component"

    items ||--o{ stock_movements : "ledger"
    users ||--o{ stock_movements : "posted by"

    items {
        int id PK
        string code UK
        string item_type "RAW_MATERIAL|PACKAGING|FINISHED_GOOD"
        int base_unit_id FK
        numeric reorder_level
    }
    products {
        int item_id PK,FK
        string hsn_code
        numeric gst_rate
        numeric selling_price "before GST"
    }
    boms {
        int id PK
        int product_id FK
        int version
        numeric batch_output_qty "e.g. 200 PKT"
        bool is_active "max 1 active per product"
    }
    bom_items {
        int id PK
        int bom_id FK
        int item_id FK
        numeric quantity "per batch"
        int unit_id FK
    }
    stock_movements {
        int id PK
        int item_id FK
        string movement_type
        numeric quantity "signed, base unit"
        numeric entered_quantity
        int entered_unit_id FK
        numeric unit_cost
        numeric balance_after "CHECK >= 0"
        numeric value_after
        string source_document_type
        int source_document_id
        string reference_no
        string posting_key UK "idempotency"
        int created_by FK
        timestamp created_at
    }
    unit_conversions {
        int id PK
        int from_unit_id FK
        int to_unit_id FK
        numeric factor
        int item_id FK "NULL = global"
    }
```

### B. Purchasing and production

```mermaid
erDiagram
    suppliers ||--o{ purchases : "bills"
    purchases ||--|{ purchase_items : "lines"
    items ||--o{ purchase_items : "received"

    products ||--o{ production_runs : "produced"
    boms ||--o{ production_runs : "recipe used"
    production_runs ||--|{ production_consumption : "planned vs actual"
    items ||--o{ production_consumption : "component"

    purchases ||..o{ stock_movements : "PURCHASE_RECEIPT"
    production_runs ||..o{ stock_movements : "ISSUE / DAMAGE / OUTPUT"

    purchases {
        int id PK
        string purchase_no UK
        int supplier_id FK
        string supplier_invoice_no "UK with supplier"
        string status "DRAFT|POSTED|CANCELLED"
        numeric taxable_amount
        numeric total_amount
    }
    purchase_items {
        int id PK
        int purchase_id FK
        int item_id FK
        numeric quantity
        int unit_id FK
        numeric base_quantity
        numeric rate
    }
    production_runs {
        int id PK
        string run_no UK
        int product_id FK
        int bom_id FK
        numeric batch_count
        numeric expected_output
        numeric actual_good_output
        numeric damaged_output
        numeric wastage_qty
        numeric labour_cost
        numeric power_gas_cost
        numeric total_cost
        numeric cost_per_good_unit
        numeric yield_variance_pct
        bool has_variance_alert
    }
    production_consumption {
        int id PK
        int run_id FK
        int item_id FK
        numeric planned_quantity
        numeric actual_quantity
        numeric damaged_quantity
        numeric unit_cost
        numeric variance_pct
        bool is_variance_alert
    }
```

### C. Sales, billing and receivables

```mermaid
erDiagram
    customers ||--o{ sales_orders : "places"
    users ||--o{ sales_orders : "salesman"
    sales_orders ||--|{ sales_order_items : "lines"
    products ||--o{ sales_order_items : "ordered"

    sales_orders ||--o{ invoices : "billed by"
    invoices ||--|{ invoice_items : "lines"
    sales_order_items ||--o{ invoice_items : "billed"

    sales_orders ||--o{ dispatches : "shipped by"
    invoices ||--o{ dispatches : "against"
    dispatches ||--|{ dispatch_items : "lines"
    sales_order_items ||--o{ dispatch_items : "shipped"
    dispatches ||..o{ stock_movements : "SALES_DISPATCH"

    invoices ||--o{ credit_notes : "reversed by"
    credit_notes ||--|{ credit_note_items : "lines"
    invoice_items ||--o{ credit_note_items : "credited"

    customers ||--o{ payments : "pays"
    payments ||--o{ payment_allocations : "allocated"
    invoices ||--o{ payment_allocations : "settled by"

    document_sequences {
        string doc_type "UK with financial_year"
        string financial_year "2026-27"
        int last_number "locked FOR UPDATE"
    }
    sales_orders {
        int id PK
        string order_no UK
        int customer_id FK
        int salesman_id FK
        string status
        int version "optimistic lock"
    }
    sales_order_items {
        int id PK
        int order_id FK
        int product_id FK
        numeric quantity_ordered
        numeric quantity_approved
        numeric quantity_dispatched
        numeric unit_price
    }
    invoices {
        int id PK
        string invoice_no UK "INV/2026-27/00001"
        string financial_year
        int sequence_no
        string place_of_supply_state_code FK
        string supply_type "INTRA_STATE|INTER_STATE"
        numeric taxable_amount
        numeric cgst_amount
        numeric sgst_amount
        numeric igst_amount
        numeric total_amount
        string status
    }
    credit_notes {
        int id PK
        string credit_note_no UK
        int invoice_id FK
        string reason_type
        bool restock
        numeric total_amount
    }
    payments {
        int id PK
        string receipt_no UK
        int customer_id FK
        numeric amount
        string mode
    }
    payment_allocations {
        int payment_id FK
        int invoice_id FK
        numeric amount
    }
```

Cross-cutting tables not drawn above: `audit_logs` (user, entity, before/after
JSON), `app_settings` (e.g. `variance_tolerance_pct = 3`), `company_profile`
(single row: GSTIN, state 33).

Dotted lines (`..`) to `stock_movements` are **logical** links via
`source_document_type` + `source_document_id`. They are not foreign keys,
because one ledger row can come from any of several document tables.

## Constraints the database enforces

| Rule | Mechanism |
|---|---|
| No negative stock | `CHECK (balance_after >= 0)` on `stock_movements`, plus an item row lock when posting |
| Quantity sign matches movement type | `CHECK` listing inbound/outbound types |
| No duplicate stock postings | `UNIQUE (posting_key)` |
| Ledger history is immutable | PostgreSQL trigger blocks `UPDATE`/`DELETE` on `stock_movements` |
| One active BOM per product | partial unique index `WHERE is_active` |
| BOM / consumption never contain finished goods | `CHECK component_type IN (RAW_MATERIAL, PACKAGING)` |
| CGST+SGST xor IGST | `CHECK` on `invoices.supply_type` vs tax columns |
| Totals add up | `CHECK total = taxable + taxes (+ round_off)` on invoices, invoice lines, credit notes, purchases |
| Gap-free invoice numbers per FY | `UNIQUE (financial_year, sequence_no)` + locked `document_sequences` row |
| Same supplier bill entered once | `UNIQUE (supplier_id, supplier_invoice_no)` |
| A posted production run has its output | `CHECK status <> 'POSTED' OR actual_good_output IS NOT NULL` |
| Global vs item-specific conversions unique | two partial unique indexes on `unit_conversions` |
| Positive quantities/amounts | `CHECK` on every line table |

Enums are stored as `VARCHAR` + `CHECK` (not native PG enums), so adding a
value is a simple migration.

## Precision

| Kind | Type |
|---|---|
| Money | `NUMERIC(14,2)` |
| Quantity | `NUMERIC(16,4)` |
| Unit cost / factor | `NUMERIC(18,6)` |
| Percent | `NUMERIC(9,4)` |

## Modelling choices worth explaining

1. **`items` supertype.** One FK target for the ledger, BOM and purchases,
   with no polymorphic nullable columns. `products.item_id` is both PK and FK.
2. **`balance_after` on each movement.** It turns "no negative stock" into a
   database rule, and it makes the stock card / ledger report a simple ordered
   read. The current balance is the latest row per item, and that always
   equals `SUM(quantity)` (an invariant the tests check).
3. **Invoice snapshots.** Customer name, GSTIN, address and place of supply
   are copied onto the invoice, because a legal document must not change
   when the customer master is edited later.
4. **`quantity_approved` vs `quantity_ordered`.** The admin's change is kept
   next to the salesman's original, and an `audit_logs` row records who
   changed it and why.
5. **Payment allocations.** These let ageing be computed per invoice, while a
   receipt can still sit partly unallocated as an advance.
