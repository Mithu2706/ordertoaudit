/** API shapes (decimals are strings). Mirrors backend/app/schemas. */
export type Role = "SALESMAN" | "ADMIN" | "PRODUCTION" | "OWNER" | "AUDITOR";
export type Dec = string;

export interface User {
  id: number;
  username: string;
  full_name: string;
  email: string | null;
  role: Role;
  is_active: boolean;
  last_login_at: string | null;
}

export interface Page<T> {
  items: T[];
  total: number;
  limit: number;
  offset: number;
}

export interface Customer {
  id: number;
  code: string;
  name: string;
  customer_type: string;
  gstin: string | null;
  state_code: string;
  address: string;
  city: string | null;
  phone: string | null;
  credit_limit: Dec;
  credit_days: number;
  assigned_salesman_id: number | null;
  is_active: boolean;
}

export interface CatalogItem {
  product_id: number;
  code: string;
  name: string;
  unit_code: string;
  hsn_code: string;
  gst_rate: Dec;
  selling_price: Dec;
  available: Dec;
}

export type OrderStatus =
  | "DRAFT" | "SUBMITTED" | "APPROVED" | "REJECTED" | "INVOICED" | "PARTIALLY_DISPATCHED" | "DISPATCHED" | "CANCELLED";

export interface OrderLine {
  id: number;
  product_id: number;
  product_code: string;
  product_name: string;
  unit_code: string;
  quantity_ordered: Dec;
  quantity_approved: Dec | null;
  quantity_dispatched: Dec;
  unit_price: Dec;
  line_amount: Dec;
  gst_rate: Dec;
  cgst: Dec;
  sgst: Dec;
  igst: Dec;
  line_total: Dec;
}

export interface Credit {
  limit: Dec;
  unlimited: boolean;
  credit_days: number;
  outstanding: Dec;
  open_orders: Dec;
  this_order: Dec;
  exposure: Dec;
  available: Dec | null;
  exceeds: boolean;
  excess: Dec;
  overdue: Dec;
  oldest_overdue_days: number | null;
}

export interface StockCheck {
  order_item_id: number;
  product_id: number;
  product_code: string;
  requested: Dec;
  on_hand: Dec;
  reserved_by_others: Dec;
  available: Dec;
  shortage: Dec;
  can_fulfil: boolean;
}

export interface Order {
  id: number;
  order_no: string;
  customer_id: number;
  customer_name: string;
  customer_state_code: string;
  salesman_id: number;
  salesman_name: string;
  order_date: string;
  status: OrderStatus;
  remarks: string | null;
  submitted_at: string | null;
  reviewed_at: string | null;
  rejection_reason: string | null;
  version: number;
  supply_type: "INTRA_STATE" | "INTER_STATE";
  taxable_amount: Dec;
  cgst_amount: Dec;
  sgst_amount: Dec;
  igst_amount: Dec;
  total_amount: Dec;
  has_shortage: boolean | null;
  items: OrderLine[];
  stock_check: StockCheck[] | null;
  credit: Credit | null;
}

export interface OrderSummary {
  id: number;
  order_no: string;
  customer_id: number;
  customer_name: string;
  salesman_id: number;
  order_date: string;
  status: OrderStatus;
  taxable_amount: Dec;
  has_shortage: boolean | null;
}

export interface InvoiceLine {
  id: number;
  order_item_id: number;
  description: string;
  hsn_code: string;
  quantity: Dec;
  unit_code: string;
  unit_price: Dec;
  taxable_amount: Dec;
  cgst_rate: Dec;
  cgst_amount: Dec;
  sgst_rate: Dec;
  sgst_amount: Dec;
  igst_rate: Dec;
  igst_amount: Dec;
  line_total: Dec;
}

export interface Invoice {
  id: number;
  invoice_no: string;
  invoice_date: string;
  order_id: number;
  order_no: string;
  customer_id: number;
  customer_name: string;
  customer_gstin: string | null;
  place_of_supply: string;
  supply_type: "INTRA_STATE" | "INTER_STATE";
  taxable_amount: Dec;
  cgst_amount: Dec;
  sgst_amount: Dec;
  igst_amount: Dec;
  total_amount: Dec;
  credited_amount: Dec;
  paid_amount: Dec;
  balance: Dec;
  status: "ISSUED" | "PARTIALLY_CREDITED" | "CANCELLED";
  amount_in_words: string;
  items: InvoiceLine[];
}

export interface InvoiceSummary {
  id: number;
  invoice_no: string;
  invoice_date: string;
  customer_id: number;
  customer_name: string;
  supply_type: string;
  taxable_amount: Dec;
  total_amount: Dec;
  balance: Dec;
  status: string;
}

export interface Payment {
  id: number;
  receipt_no: string;
  customer_id: number;
  customer_name: string;
  payment_date: string;
  amount: Dec;
  mode: string;
  reference_no: string | null;
  unallocated: Dec;
  allocations: { invoice_id: number; invoice_no: string; amount: Dec }[];
}

export interface Receivable {
  customer_id: number;
  customer_code: string;
  customer_name: string;
  invoiced: Dec;
  credited: Dec;
  received: Dec;
  invoice_outstanding: Dec;
  unallocated_advance: Dec;
  outstanding: Dec;
  ageing: Record<string, Dec>;
  open_invoices: { invoice_id: number; invoice_no: string; invoice_date: string; total_amount: Dec; balance: Dec; age_days: number }[];
}

export interface Balance {
  item_id: number;
  item_code: string;
  item_name: string;
  item_type: "RAW_MATERIAL" | "PACKAGING" | "FINISHED_GOOD";
  unit_code: string;
  quantity: Dec;
  value: Dec;
  avg_cost: Dec;
  reorder_level: Dec;
  low_stock: boolean;
}

export interface Consumption {
  item_id: number;
  item_code: string;
  item_name: string;
  component_type: "RAW_MATERIAL" | "PACKAGING";
  unit_code: string;
  planned_quantity: Dec;
  actual_quantity: Dec | null;
  damaged_quantity: Dec;
  total_consumed: Dec | null;
  variance_quantity: Dec | null;
  variance_pct: Dec | null;
  is_variance_alert: boolean;
  unit_cost: Dec | null;
  total_cost: Dec | null;
}

export interface ProductionRun {
  id: number;
  run_no: string;
  product_id: number;
  product_code: string;
  product_name: string;
  output_unit_code: string;
  bom_id: number;
  bom_version: number;
  production_date: string;
  status: "DRAFT" | "POSTED" | "CANCELLED";
  batch_count: Dec;
  expected_output: Dec;
  actual_good_output: Dec | null;
  damaged_output: Dec;
  wastage_qty: Dec;
  wastage_unit_code: string | null;
  labour_cost: Dec;
  power_gas_cost: Dec;
  material_cost: Dec | null;
  packaging_cost: Dec | null;
  total_cost: Dec | null;
  cost_per_good_unit: Dec | null;
  yield_variance_pct: Dec | null;
  variance_tolerance_pct: Dec;
  has_variance_alert: boolean;
  selling_price: Dec | null;
  gross_margin_per_unit: Dec | null;
  gross_margin_pct: Dec | null;
  remarks: string | null;
  posted_at: string | null;
  consumption: Consumption[];
}

export interface RunSummary {
  id: number;
  run_no: string;
  product_id: number;
  production_date: string;
  status: string;
  expected_output: Dec;
  actual_good_output: Dec | null;
  yield_variance_pct: Dec | null;
  has_variance_alert: boolean;
  total_cost: Dec | null;
  cost_per_good_unit: Dec | null;
}

export interface Product {
  id: number;
  code: string;
  name: string;
  base_unit_code: string;
  hsn_code: string;
  gst_rate: Dec;
  selling_price: Dec;
  is_active: boolean;
}

export interface ReportColumn {
  key: string;
  label: string;
  kind: "text" | "date" | "int" | "qty" | "money" | "rate" | "pct" | "bool";
  total: boolean;
}

export interface ReportData {
  key: string;
  title: string;
  filters: Record<string, string>;
  notes: string[];
  columns: ReportColumn[];
  rows: Record<string, string | number | boolean | null>[];
  totals: Record<string, string> | null;
  row_count: number;
}
