/** Admin: approval queue with stock indicators, and order review (approve / partial / reject / invoice). */
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { AlertTriangle, ArrowLeft, CheckCircle2, FileText, XCircle } from "lucide-react";
import { useEffect, useState } from "react";
import { Link, useNavigate, useParams } from "react-router-dom";
import { OrderTotals } from "@/components/OrderTotals";
import {
  Badge, Button, Card, EmptyState, ErrorBanner, Field, Modal, PageHeader, Spinner, StatusBadge, Table, Td, Th, cx, useToast,
} from "@/components/ui";
import { api } from "@/lib/api";
import { useAuth } from "@/lib/auth";
import { date, dateTime, inr, qty } from "@/lib/format";
import type { Invoice, InvoiceSummary, Order, OrderSummary, Page } from "@/lib/types";

const TABS = [
  ["SUBMITTED", "Awaiting approval"], ["APPROVED", "Approved · to invoice"], ["INVOICED", "Invoiced · to dispatch"],
  ["DISPATCHED", "Dispatched"], ["REJECTED", "Rejected"], ["", "All"],
] as const;

export function ApprovalQueue() {
  const [status, setStatus] = useState<string>("SUBMITTED");
  const orders = useQuery({ queryKey: ["orders", "queue", status],
    queryFn: () => api<Page<OrderSummary>>("/sales-orders", { params: { status, limit: 200 } }) });
  return (
    <>
      <PageHeader title="Order approvals" subtitle="Verify quantities, prices and stock before committing goods" />
      <div className="mb-4 flex flex-wrap gap-1 rounded-lg bg-white p-1 shadow-card ring-1 ring-navy-100 sm:inline-flex">
        {TABS.map(([v, l]) => (
          <button key={v} onClick={() => setStatus(v)}
            className={cx("rounded-md px-3 py-1.5 text-sm font-medium", status === v ? "bg-navy-800 text-white" : "text-navy-600 hover:bg-navy-50")}>{l}</button>
        ))}
      </div>
      <ErrorBanner error={orders.error} />
      <Card>
        {orders.isLoading ? <Spinner /> : !orders.data?.items.length ? (
          <EmptyState title={status === "SUBMITTED" ? "Nothing waiting for approval" : "No orders"} hint="New orders from salesmen appear here." />
        ) : (
          <Table>
            <thead><tr><Th>Order</Th><Th>Date</Th><Th>Customer</Th><Th>Status</Th><Th>Stock</Th><Th right>Taxable</Th></tr></thead>
            <tbody className="divide-y divide-navy-100">
              {orders.data.items.map((o) => (
                <tr key={o.id} className="hover:bg-navy-50/50">
                  <Td><Link to={`/admin/orders/${o.id}`} className="font-medium text-navy-800 underline-offset-2 hover:underline">{o.order_no}</Link></Td>
                  <Td className="text-navy-400">{date(o.order_date)}</Td>
                  <Td>{o.customer_name}</Td>
                  <Td><StatusBadge status={o.status} /></Td>
                  <Td>{o.has_shortage === null ? <span className="text-navy-200">—</span> : o.has_shortage
                    ? <Badge tone="amber"><AlertTriangle className="h-3 w-3" />Short</Badge>
                    : <Badge tone="green"><CheckCircle2 className="h-3 w-3" />Available</Badge>}</Td>
                  <Td right>{inr(o.taxable_amount)}</Td>
                </tr>
              ))}
            </tbody>
          </Table>
        )}
      </Card>
    </>
  );
}

export function OrderReview() {
  const { id } = useParams();
  const { user } = useAuth();
  const canAct = user?.role === "ADMIN";
  const qc = useQueryClient();
  const toast = useToast();
  const navigate = useNavigate();
  const order = useQuery({ queryKey: ["order", Number(id)], queryFn: () => api<Order>(`/sales-orders/${id}`) });
  const invoices = useQuery({ queryKey: ["invoices", "order", Number(id)],
    enabled: !!order.data && ["INVOICED", "PARTIALLY_DISPATCHED", "DISPATCHED", "CANCELLED"].includes(order.data.status),
    queryFn: () => api<Page<InvoiceSummary>>("/invoices", { params: { order_id: id } }) });

  const [approved, setApproved] = useState<Record<number, string>>({});
  const [prices, setPrices] = useState<Record<number, string>>({});
  const [reason, setReason] = useState("");
  const [rejectOpen, setRejectOpen] = useState(false);
  const [rejectReason, setRejectReason] = useState("");
  const [cancelOpen, setCancelOpen] = useState(false);

  useEffect(() => {
    if (order.data) {
      // Default the approval to what is actually available (never more than ordered).
      setApproved(Object.fromEntries(order.data.items.map((l) => {
        const check = order.data!.stock_check?.find((c) => c.order_item_id === l.id);
        const fallback = qty(l.quantity_ordered).replace(/,/g, "");
        const avail = check && !check.can_fulfil ? qty(check.available).replace(/,/g, "") : fallback;
        return [l.id, avail];
      })));
      setPrices(Object.fromEntries(order.data.items.map((l) => [l.id, l.unit_price])));
    }
  }, [order.data]);

  const after = (o: Order) => { qc.setQueryData(["order", o.id], o); qc.invalidateQueries({ queryKey: ["orders"] }); };
  const approve = useMutation({
    mutationFn: () => api<Order>(`/sales-orders/${id}/approve`, { body: {
      version: order.data!.version, reason: reason.trim() || null,
      lines: order.data!.items.map((l) => ({ order_item_id: l.id, quantity_approved: approved[l.id] || "0",
        ...(prices[l.id] !== l.unit_price ? { unit_price: prices[l.id] } : {}) })),
    } }),
    onSuccess: (o) => { after(o); toast("Order approved: stock reserved"); },
  });
  const reject = useMutation({
    mutationFn: () => api<Order>(`/sales-orders/${id}/reject`, { body: { version: order.data!.version, reason: rejectReason } }),
    onSuccess: (o) => { after(o); setRejectOpen(false); toast("Order rejected"); },
  });
  const cancel = useMutation({
    mutationFn: () => api<Order>(`/sales-orders/${id}/cancel`, { body: { reason: rejectReason } }),
    onSuccess: (o) => { after(o); setCancelOpen(false); toast("Order cancelled, reservation released"); },
  });
  const invoice = useMutation({
    mutationFn: () => api<Invoice>("/invoices", { body: { order_id: Number(id) } }),
    onSuccess: (inv) => { qc.invalidateQueries(); toast(`Invoice ${inv.invoice_no} generated`); navigate(`/admin/invoices/${inv.id}`); },
  });

  if (order.isLoading) return <Spinner />;
  if (!order.data) return <ErrorBanner error={order.error} />;
  const o = order.data;
  const reviewing = o.status === "SUBMITTED" && canAct;
  const modified = o.items.some((l) => approved[l.id] !== qty(l.quantity_ordered).replace(/,/g, "") || prices[l.id] !== l.unit_price);

  return (
    <>
      <PageHeader title={`${o.order_no}`} subtitle={`${o.customer_name} · by ${o.salesman_name} · ${date(o.order_date)}`}
        back={<Link to="/admin/orders" className="mb-2 flex items-center gap-1 text-sm text-navy-400"><ArrowLeft className="h-4 w-4" />Approvals</Link>}
        actions={<StatusBadge status={o.status} />} />

      {o.has_shortage && o.status === "SUBMITTED" && (
        <div className="mb-4 flex gap-3 rounded-lg border border-amber-100 bg-amber-50 px-4 py-3 text-sm text-amber-700">
          <AlertTriangle className="mt-0.5 h-4 w-4 flex-none" />
          <div><b>Insufficient stock.</b> Approving the full quantity will be refused. Approve what is available
            (pre-filled below, with a reason) or reject / keep the order pending.</div>
        </div>
      )}
      {o.status === "REJECTED" && <ErrorBanner className="mb-4" error={`Rejected: ${o.rejection_reason}`} />}

      <div className="grid gap-4 lg:grid-cols-3">
        <Card className="lg:col-span-2" title="Lines and stock verification">
          <Table>
            <thead><tr>
              <Th>Product</Th><Th right>Ordered</Th>
              {o.stock_check && <><Th right>On hand</Th><Th right>Reserved</Th><Th right>Available</Th><Th right>Shortage</Th></>}
              <Th right>{reviewing ? "Approve qty" : "Approved"}</Th><Th right>Rate</Th><Th right>Amount</Th>
            </tr></thead>
            <tbody className="divide-y divide-navy-100">
              {o.items.map((l) => {
                const c = o.stock_check?.find((s) => s.order_item_id === l.id);
                return (
                  <tr key={l.id}>
                    <Td><div className="font-medium">{l.product_name}</div><div className="text-xs text-navy-400">{l.product_code} · {l.unit_code}</div></Td>
                    <Td right>{qty(l.quantity_ordered)}</Td>
                    {o.stock_check && <>
                      <Td right>{qty(c?.on_hand)}</Td>
                      <Td right className="text-navy-400">{qty(c?.reserved_by_others)}</Td>
                      <Td right className="font-medium">{qty(c?.available)}</Td>
                      <Td right>{c && !c.can_fulfil ? <span className="font-semibold text-red-700">{qty(c.shortage)}</span> : <span className="text-emerald-700">0</span>}</Td>
                    </>}
                    <Td right>{reviewing ? (
                      <input className="input w-20 text-right" inputMode="numeric" value={approved[l.id] ?? ""}
                        onChange={(e) => setApproved((a) => ({ ...a, [l.id]: e.target.value.replace(/[^\d]/g, "") }))} aria-label="Approved quantity" />
                    ) : qty(l.quantity_approved)}</Td>
                    <Td right>{reviewing ? (
                      <input className="input w-24 text-right" inputMode="decimal" value={prices[l.id] ?? ""}
                        onChange={(e) => setPrices((p) => ({ ...p, [l.id]: e.target.value.replace(/[^\d.]/g, "") }))} aria-label="Unit price" />
                    ) : inr(l.unit_price)}</Td>
                    <Td right>{inr(l.line_amount)}</Td>
                  </tr>
                );
              })}
            </tbody>
          </Table>
          {reviewing && (
            <div className="space-y-3 border-t border-navy-100 p-4">
              <Field label={modified ? "Reason for change (required)" : "Reason for change"}
                hint={modified ? "Quantities or prices differ from the order; this goes into the audit trail." : "Only needed if you change a quantity or price."}>
                <input className="input" value={reason} onChange={(e) => setReason(e.target.value)} placeholder="e.g. Only 88 packets available; balance to follow" />
              </Field>
              <ErrorBanner error={approve.error} />
              <div className="flex flex-wrap gap-2">
                <Button variant="accent" icon={<CheckCircle2 className="h-4 w-4" />} loading={approve.isPending}
                  disabled={modified && reason.trim().length < 3} onClick={() => approve.mutate()}>
                  {modified ? "Approve with changes" : "Approve as ordered"}
                </Button>
                <Button variant="danger" icon={<XCircle className="h-4 w-4" />} onClick={() => setRejectOpen(true)}>Reject</Button>
              </div>
            </div>
          )}
        </Card>

        <div className="space-y-4">
          <Card title="Value (GST as calculated by the server)" className="p-0">
            <div className="p-4">
              <OrderTotals supply={o.supply_type} taxable={o.taxable_amount} cgst={o.cgst_amount} sgst={o.sgst_amount}
                igst={o.igst_amount} total={o.total_amount} />
              <p className="mt-3 text-xs text-navy-400">Customer state {o.customer_state_code}; factory in Tamil Nadu (33).</p>
            </div>
          </Card>
          <Card title="Timeline" className="p-0">
            <ul className="space-y-2 p-4 text-sm">
              <li>Created {date(o.order_date)}</li>
              {o.submitted_at && <li>Submitted {dateTime(o.submitted_at)}</li>}
              {o.reviewed_at && <li>Reviewed {dateTime(o.reviewed_at)}</li>}
            </ul>
          </Card>
          {canAct && o.status === "APPROVED" && (
            <Card className="p-4">
              <p className="mb-3 text-sm text-navy-600">Approved quantities are reserved. Generate the GST invoice before dispatch.</p>
              <ErrorBanner error={invoice.error ?? cancel.error} className="mb-3" />
              <div className="flex flex-wrap gap-2">
                <Button variant="accent" icon={<FileText className="h-4 w-4" />} loading={invoice.isPending} onClick={() => invoice.mutate()}>Generate invoice</Button>
                <Button variant="danger" onClick={() => setCancelOpen(true)}>Cancel order</Button>
              </div>
            </Card>
          )}
          {!!invoices.data?.items.length && (
            <Card title="Invoices" className="p-0">
              <ul className="divide-y divide-navy-100 text-sm">
                {invoices.data.items.map((i) => (
                  <li key={i.id} className="flex items-center justify-between px-4 py-2.5">
                    <Link className="font-medium text-terracotta-700 hover:underline" to={`/admin/invoices/${i.id}`}>{i.invoice_no}</Link>
                    <StatusBadge status={i.status} />
                  </li>
                ))}
              </ul>
            </Card>
          )}
        </div>
      </div>

      <Modal open={rejectOpen} onClose={() => setRejectOpen(false)} title="Reject order"
        footer={<><Button variant="secondary" onClick={() => setRejectOpen(false)}>Back</Button>
          <Button variant="danger" disabled={rejectReason.trim().length < 3} loading={reject.isPending} onClick={() => reject.mutate()}>Reject order</Button></>}>
        <ErrorBanner error={reject.error} className="mb-3" />
        <Field label="Reason (shown to the salesman)"><input className="input" autoFocus value={rejectReason} onChange={(e) => setRejectReason(e.target.value)} /></Field>
      </Modal>
      <Modal open={cancelOpen} onClose={() => setCancelOpen(false)} title="Cancel approved order"
        footer={<><Button variant="secondary" onClick={() => setCancelOpen(false)}>Back</Button>
          <Button variant="danger" disabled={rejectReason.trim().length < 3} loading={cancel.isPending} onClick={() => cancel.mutate()}>Cancel order</Button></>}>
        <p className="mb-3 text-sm text-navy-600">The reserved stock will be released.</p>
        <Field label="Reason"><input className="input" autoFocus value={rejectReason} onChange={(e) => setRejectReason(e.target.value)} /></Field>
      </Modal>
    </>
  );
}
