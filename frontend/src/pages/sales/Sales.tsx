/** Salesman: mobile-first order entry, order status and customer history. */
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { ArrowLeft, Check, ChevronRight, MapPin, Minus, Plus, Search, Send, Store, Trash2 } from "lucide-react";
import { useEffect, useMemo, useState } from "react";
import { Link, useNavigate, useParams } from "react-router-dom";
import { OrderTotals } from "@/components/OrderTotals";
import {
  Badge, Button, Card, EmptyState, ErrorBanner, Modal, PageHeader, Spinner, StatusBadge, Table, Td, Th, cx, useToast,
} from "@/components/ui";
import { api } from "@/lib/api";
import { date, inr, monthStart, qty, today } from "@/lib/format";
import type { CatalogItem, Customer, Order, OrderSummary, Page, ReportData } from "@/lib/types";

const FILTERS = [
  ["", "All"], ["DRAFT", "Drafts"], ["SUBMITTED", "Awaiting approval"], ["APPROVED", "Approved"], ["DISPATCHED", "Dispatched"],
] as const;

// ---- My orders ---------------------------------------------------------------------------
export function MyOrders() {
  const [status, setStatus] = useState("");
  const orders = useQuery({
    queryKey: ["orders", "mine", status],
    queryFn: () => api<Page<OrderSummary>>("/sales-orders", { params: { status, limit: 100 } }),
  });
  return (
    <>
      <PageHeader title="My orders" subtitle="Orders you have placed and their status"
        actions={<Link to="/sales/new" className="hidden sm:block"><Button variant="accent" icon={<Plus className="h-4 w-4" />}>New order</Button></Link>} />
      <div className="-mx-4 mb-4 flex gap-2 overflow-x-auto px-4 pb-1">
        {FILTERS.map(([v, l]) => (
          <button key={v} onClick={() => setStatus(v)}
            className={cx("whitespace-nowrap rounded-full px-3 py-1.5 text-sm font-medium",
              status === v ? "bg-navy-800 text-white" : "bg-white text-navy-600 ring-1 ring-navy-200")}>{l}</button>
        ))}
      </div>
      <ErrorBanner error={orders.error} />
      {orders.isLoading ? <Spinner /> : !orders.data?.items.length ? (
        <Card><EmptyState title="No orders here yet" hint="Tap New order to take an order from a customer." /></Card>
      ) : (
        <ul className="space-y-2">
          {orders.data.items.map((o) => (
            <li key={o.id}>
              <Link to={`/sales/orders/${o.id}`}
                className="flex items-center gap-3 rounded-xl border border-navy-100 bg-white p-4 shadow-card active:bg-navy-50">
                <div className="min-w-0 flex-1">
                  <div className="flex items-center gap-2">
                    <span className="font-medium">{o.customer_name}</span>
                  </div>
                  <div className="mt-0.5 text-xs text-navy-400">{o.order_no} · {date(o.order_date)}</div>
                  <div className="mt-2 flex flex-wrap items-center gap-1.5">
                    <StatusBadge status={o.status} />
                    {o.has_shortage && <Badge tone="amber">Stock short</Badge>}
                  </div>
                </div>
                <div className="text-right">
                  <div className="num font-semibold">{inr(o.taxable_amount)}</div>
                  <div className="text-[11px] text-navy-400">before GST</div>
                </div>
                <ChevronRight className="h-4 w-4 text-navy-200" />
              </Link>
            </li>
          ))}
        </ul>
      )}
    </>
  );
}

// ---- New / edit order -----------------------------------------------------------------------
function Stepper({ value, onChange }: { value: number; onChange: (n: number) => void }) {
  return (
    <div className="flex items-center rounded-lg border border-navy-200 bg-white">
      <button type="button" aria-label="Decrease" onClick={() => onChange(Math.max(0, value - 1))}
        className="p-2.5 text-navy-600 disabled:opacity-30" disabled={value === 0}><Minus className="h-4 w-4" /></button>
      <input inputMode="numeric" pattern="[0-9]*" aria-label="Quantity"
        className="w-14 border-x border-navy-100 py-2 text-center text-sm font-semibold tabular-nums focus:outline-none"
        value={value || ""} placeholder="0"
        onChange={(e) => onChange(Math.max(0, Math.floor(Number(e.target.value.replace(/\D/g, "")) || 0)))} />
      <button type="button" aria-label="Increase" onClick={() => onChange(value + 1)}
        className="p-2.5 text-navy-600"><Plus className="h-4 w-4" /></button>
    </div>
  );
}

export function NewOrder() {
  const { id } = useParams();
  const editing = id ? Number(id) : null;
  const navigate = useNavigate();
  const qc = useQueryClient();
  const toast = useToast();
  const [customerId, setCustomerId] = useState<number | null>(null);
  const [lines, setLines] = useState<Record<number, number>>({});
  const [search, setSearch] = useState("");
  const [remarks, setRemarks] = useState("");

  const customers = useQuery({ queryKey: ["customers", "mine"], queryFn: () => api<Page<Customer>>("/customers", { params: { active: true, limit: 200 } }) });
  const catalog = useQuery({ queryKey: ["catalog"], queryFn: () => api<CatalogItem[]>("/catalog") });
  const existing = useQuery({ queryKey: ["order", editing], enabled: !!editing, queryFn: () => api<Order>(`/sales-orders/${editing}`) });

  useEffect(() => {
    if (existing.data) {
      setCustomerId(existing.data.customer_id);
      setRemarks(existing.data.remarks ?? "");
      setLines(Object.fromEntries(existing.data.items.map((l) => [l.product_id, Number(l.quantity_ordered)])));
    }
  }, [existing.data]);

  const save = useMutation({
    mutationFn: () => {
      const body = {
        customer_id: customerId, remarks: remarks || null,
        items: Object.entries(lines).filter(([, q]) => q > 0).map(([pid, q]) => ({ product_id: Number(pid), quantity: String(q) })),
      };
      return editing ? api<Order>(`/sales-orders/${editing}`, { method: "PUT", body }) : api<Order>("/sales-orders", { body });
    },
    onSuccess: (o) => {
      qc.invalidateQueries({ queryKey: ["orders"] });
      toast(editing ? "Draft updated" : "Draft saved: review and submit");
      navigate(`/sales/orders/${o.id}`, { replace: true });
    },
  });

  const filtered = useMemo(() => (customers.data?.items ?? []).filter((c) =>
    `${c.name} ${c.code} ${c.city ?? ""}`.toLowerCase().includes(search.toLowerCase())), [customers.data, search]);
  const chosen = customers.data?.items.find((c) => c.id === customerId);
  const packets = Object.values(lines).reduce((a, b) => a + b, 0);

  if (customers.isLoading || catalog.isLoading || existing.isLoading) return <Spinner />;

  // Step 1: choose the customer
  if (!chosen) {
    return (
      <>
        <PageHeader title="New order" subtitle="Step 1 of 2 · choose the customer" />
        <div className="relative mb-3">
          <Search className="absolute left-3 top-2.5 h-4 w-4 text-navy-400" />
          <input className="input pl-9" placeholder="Search your customers" value={search} onChange={(e) => setSearch(e.target.value)} />
        </div>
        <ErrorBanner error={customers.error} />
        {!filtered.length ? <Card><EmptyState title="No customers assigned to you" hint="Ask the admin to assign customers to your account." /></Card> : (
          <ul className="space-y-2">
            {filtered.map((c) => (
              <li key={c.id}>
                <button onClick={() => setCustomerId(c.id)}
                  className="flex w-full items-center gap-3 rounded-xl border border-navy-100 bg-white p-4 text-left shadow-card active:bg-navy-50">
                  <div className="rounded-lg bg-navy-50 p-2 text-navy-600"><Store className="h-5 w-5" /></div>
                  <div className="min-w-0 flex-1">
                    <div className="font-medium">{c.name}</div>
                    <div className="flex items-center gap-1 text-xs text-navy-400"><MapPin className="h-3 w-3" />{c.city ?? c.address} · {c.code}</div>
                  </div>
                  <ChevronRight className="h-4 w-4 text-navy-200" />
                </button>
              </li>
            ))}
          </ul>
        )}
      </>
    );
  }

  // Step 2: quantities
  return (
    <>
      <PageHeader title={editing ? "Edit draft" : "New order"} subtitle="Step 2 of 2 · enter quantities"
        back={!editing && (
          <button onClick={() => setCustomerId(null)} className="mb-2 flex items-center gap-1 text-sm text-navy-400">
            <ArrowLeft className="h-4 w-4" /> Change customer
          </button>
        )} />
      <Card className="mb-4 p-4">
        <div className="text-xs uppercase tracking-wide text-navy-400">Customer</div>
        <div className="font-medium">{chosen.name}</div>
        <div className="text-xs text-navy-400">{chosen.address}</div>
      </Card>

      <ErrorBanner error={catalog.error} className="mb-3" />
      <ul className="space-y-2">
        {(catalog.data ?? []).map((p) => {
          const q = lines[p.product_id] ?? 0;
          const over = q > Number(p.available); // UI hint only; the admin's approval is the real stock check
          return (
            <li key={p.product_id} className={cx("rounded-xl border bg-white p-4 shadow-card", q > 0 ? "border-terracotta-500" : "border-navy-100")}>
              <div className="flex items-start justify-between gap-3">
                <div className="min-w-0">
                  <div className="font-medium">{p.name}</div>
                  <div className="text-xs text-navy-400">{p.code} · HSN {p.hsn_code}</div>
                  <div className="mt-1 text-sm"><span className="font-semibold">{inr(p.selling_price)}</span>
                    <span className="text-navy-400"> / {p.unit_code} + {qty(p.gst_rate)}% GST</span></div>
                  <div className={cx("mt-1 text-xs", over ? "text-amber-700" : "text-navy-400")}>
                    {qty(p.available)} {p.unit_code} available{over && " (more than in stock: the admin will review)"}
                  </div>
                </div>
                <Stepper value={q} onChange={(n) => setLines((l) => ({ ...l, [p.product_id]: n }))} />
              </div>
            </li>
          );
        })}
      </ul>

      <label className="mt-4 block">
        <span className="label">Remarks (optional)</span>
        <input className="input" value={remarks} maxLength={500} onChange={(e) => setRemarks(e.target.value)} placeholder="e.g. Deliver before Friday" />
      </label>
      <ErrorBanner error={save.error} className="mt-3" />

      <div className="sticky bottom-16 z-20 mt-4 rounded-xl bg-navy-800 p-3 text-white shadow-lg lg:bottom-4">
        <div className="flex items-center justify-between gap-3">
          <div className="text-sm"><span className="font-semibold">{packets}</span> packets selected
            <div className="text-xs text-navy-200">Prices and GST are calculated on the next screen</div></div>
          <Button variant="accent" disabled={!packets} loading={save.isPending} onClick={() => save.mutate()} icon={<Check className="h-4 w-4" />}>
            {editing ? "Update" : "Review"}
          </Button>
        </div>
      </div>
    </>
  );
}

// ---- Order detail -----------------------------------------------------------------------------
export function SalesOrderDetail() {
  const { id } = useParams();
  const qc = useQueryClient();
  const toast = useToast();
  const navigate = useNavigate();
  const [cancelOpen, setCancelOpen] = useState(false);
  const [reason, setReason] = useState("");
  const order = useQuery({ queryKey: ["order", Number(id)], queryFn: () => api<Order>(`/sales-orders/${id}`) });
  const refresh = (o: Order) => { qc.setQueryData(["order", o.id], o); qc.invalidateQueries({ queryKey: ["orders"] }); };
  const submit = useMutation({ mutationFn: () => api<Order>(`/sales-orders/${id}/submit`, { method: "POST" }),
    onSuccess: (o) => { refresh(o); toast("Submitted for approval"); } });
  const cancel = useMutation({ mutationFn: () => api<Order>(`/sales-orders/${id}/cancel`, { body: { reason } }),
    onSuccess: (o) => { refresh(o); setCancelOpen(false); toast("Order cancelled"); } });

  if (order.isLoading) return <Spinner />;
  if (!order.data) return <ErrorBanner error={order.error} />;
  const o = order.data;
  return (
    <>
      <PageHeader title={o.customer_name} subtitle={`${o.order_no} · ${date(o.order_date)}`}
        back={<Link to="/sales" className="mb-2 flex items-center gap-1 text-sm text-navy-400"><ArrowLeft className="h-4 w-4" />My orders</Link>}
        actions={<StatusBadge status={o.status} />} />

      {o.status === "REJECTED" && <ErrorBanner className="mb-3" error={`Rejected: ${o.rejection_reason}`} />}
      {o.has_shortage && o.status === "SUBMITTED" && (
        <div className="mb-3 rounded-lg border border-amber-100 bg-amber-50 px-4 py-3 text-sm text-amber-700">
          Not enough stock for the full quantity right now. The admin will review and may approve part of it.
        </div>
      )}

      <Card className="mb-4">
        <ul className="divide-y divide-navy-100">
          {o.items.map((l) => (
            <li key={l.id} className="flex items-center justify-between gap-3 px-4 py-3">
              <div>
                <div className="font-medium">{l.product_name}</div>
                <div className="text-xs text-navy-400">
                  {qty(l.quantity_ordered)} {l.unit_code} × {inr(l.unit_price)}
                  {l.quantity_approved !== null && l.quantity_approved !== l.quantity_ordered &&
                    <span className="text-terracotta-700"> · approved {qty(l.quantity_approved)}</span>}
                  {Number(l.quantity_dispatched) > 0 && <span> · dispatched {qty(l.quantity_dispatched)}</span>}
                </div>
              </div>
              <div className="num font-medium">{inr(l.line_amount)}</div>
            </li>
          ))}
        </ul>
        <div className="border-t border-navy-100 p-4">
          <OrderTotals supply={o.supply_type} taxable={o.taxable_amount} cgst={o.cgst_amount} sgst={o.sgst_amount}
            igst={o.igst_amount} total={o.total_amount} totalLabel="Order value" />
        </div>
      </Card>

      <ErrorBanner error={submit.error ?? cancel.error} className="mb-3" />
      <div className="flex flex-wrap gap-2">
        {o.status === "DRAFT" && <>
          <Button variant="accent" size="lg" className="flex-1 sm:flex-none" icon={<Send className="h-4 w-4" />}
            loading={submit.isPending} onClick={() => submit.mutate()}>Submit for approval</Button>
          <Button variant="secondary" size="lg" onClick={() => navigate(`/sales/orders/${o.id}/edit`)}>Edit</Button>
        </>}
        {(o.status === "DRAFT" || o.status === "SUBMITTED") &&
          <Button variant="danger" size="lg" icon={<Trash2 className="h-4 w-4" />} onClick={() => setCancelOpen(true)}>Cancel</Button>}
      </div>

      <Modal open={cancelOpen} onClose={() => setCancelOpen(false)} title="Cancel order"
        footer={<><Button variant="secondary" onClick={() => setCancelOpen(false)}>Keep order</Button>
          <Button variant="danger" disabled={reason.trim().length < 3} loading={cancel.isPending} onClick={() => cancel.mutate()}>Cancel order</Button></>}>
        <label className="block"><span className="label">Reason</span>
          <input className="input" autoFocus value={reason} onChange={(e) => setReason(e.target.value)} placeholder="e.g. Customer changed the quantity" /></label>
      </Modal>
    </>
  );
}

// ---- Customer-wise sales history --------------------------------------------------------------
export function CustomerHistory() {
  const [from, setFrom] = useState(monthStart());
  const [to, setTo] = useState(today());
  const report = useQuery({ queryKey: ["report", "customer-sales", from, to],
    queryFn: () => api<ReportData>("/reports/customer-sales", { params: { date_from: from, date_to: to } }) });
  return (
    <>
      <PageHeader title="Customer sales" subtitle="Invoiced sales to your customers" />
      <div className="mb-4 grid grid-cols-2 gap-3 sm:max-w-md">
        <label><span className="label">From</span><input type="date" className="input" value={from} max={to} onChange={(e) => setFrom(e.target.value)} /></label>
        <label><span className="label">To</span><input type="date" className="input" value={to} min={from} max={today()} onChange={(e) => setTo(e.target.value)} /></label>
      </div>
      <ErrorBanner error={report.error} />
      <Card>
        {report.isLoading ? <Spinner /> : !report.data?.rows.length ? <EmptyState title="No invoiced sales in this period" /> : (
          <Table>
            <thead><tr><Th>Customer</Th><Th right>Invoices</Th><Th right>Invoiced</Th><Th right>Credit notes</Th><Th right>Net sales</Th></tr></thead>
            <tbody className="divide-y divide-navy-100">
              {report.data.rows.map((r) => (
                <tr key={String(r.code)}>
                  <Td><div className="font-medium">{String(r.customer)}</div><div className="text-xs text-navy-400">{String(r.code)}</div></Td>
                  <Td right>{String(r.invoices)}</Td>
                  <Td right>{inr(String(r.total))}</Td>
                  <Td right>{inr(String(r.credited))}</Td>
                  <Td right className="font-semibold">{inr(String(r.net))}</Td>
                </tr>
              ))}
            </tbody>
          </Table>
        )}
      </Card>
    </>
  );
}
