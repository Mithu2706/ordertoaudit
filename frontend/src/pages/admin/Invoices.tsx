/** Admin: GST invoices, PDF, dispatch and credit notes. */
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { ArrowLeft, Download, FileMinus, IndianRupee, Search, Truck } from "lucide-react";
import { useState } from "react";
import { Link, useParams } from "react-router-dom";
import { OrderTotals } from "@/components/OrderTotals";
import {
  Badge, Button, Card, EmptyState, ErrorBanner, Field, Modal, PageHeader, Spinner, StatusBadge, Table, Td, Th, useToast,
} from "@/components/ui";
import { api, download } from "@/lib/api";
import { useAuth } from "@/lib/auth";
import { date, inr, isZero, label, qty } from "@/lib/format";
import type { Invoice, InvoiceSummary, Order, Page } from "@/lib/types";

interface DispatchRow { id: number; dispatch_no: string; dispatch_date: string; vehicle_no: string | null; items: { order_item_id: number; quantity: string }[] }
interface CreditNoteRow { id: number; credit_note_no: string; credit_note_date: string; reason_type: string; reason: string; restock: boolean; total_amount: string }

export function InvoiceList() {
  const [q, setQ] = useState("");
  const invoices = useQuery({ queryKey: ["invoices", q], queryFn: () => api<Page<InvoiceSummary>>("/invoices", { params: { q, limit: 200 } }) });
  return (
    <>
      <PageHeader title="Invoices & dispatch" subtitle="GST tax invoices. Corrections go through credit notes; invoices are never deleted." />
      <div className="relative mb-4 max-w-sm">
        <Search className="absolute left-3 top-2.5 h-4 w-4 text-navy-400" />
        <input className="input pl-9" placeholder="Invoice no or customer" value={q} onChange={(e) => setQ(e.target.value)} />
      </div>
      <ErrorBanner error={invoices.error} />
      <Card>
        {invoices.isLoading ? <Spinner /> : !invoices.data?.items.length ? (
          <EmptyState title="No invoices yet" hint="Approve an order and generate its invoice from the approval screen." />
        ) : (
          <Table>
            <thead><tr><Th>Invoice</Th><Th>Date</Th><Th>Customer</Th><Th>Supply</Th><Th right>Taxable</Th><Th right>Total</Th><Th right>Balance</Th><Th>Status</Th></tr></thead>
            <tbody className="divide-y divide-navy-100">
              {invoices.data.items.map((i) => (
                <tr key={i.id} className="hover:bg-navy-50/50">
                  <Td><Link to={`/admin/invoices/${i.id}`} className="font-medium hover:underline">{i.invoice_no}</Link></Td>
                  <Td className="text-navy-400">{date(i.invoice_date)}</Td>
                  <Td>{i.customer_name}</Td>
                  <Td><Badge tone={i.supply_type === "INTRA_STATE" ? "blue" : "terracotta"}>{i.supply_type === "INTRA_STATE" ? "CGST+SGST" : "IGST"}</Badge></Td>
                  <Td right>{inr(i.taxable_amount)}</Td>
                  <Td right className="font-medium">{inr(i.total_amount)}</Td>
                  <Td right className={isZero(i.balance) ? "text-emerald-700" : ""}>{inr(i.balance)}</Td>
                  <Td><StatusBadge status={i.status} /></Td>
                </tr>
              ))}
            </tbody>
          </Table>
        )}
      </Card>
    </>
  );
}

export function InvoiceDetail() {
  const { id } = useParams();
  const { user } = useAuth();
  const canAct = user?.role === "ADMIN";
  const qc = useQueryClient();
  const toast = useToast();
  const inv = useQuery({ queryKey: ["invoice", Number(id)], queryFn: () => api<Invoice>(`/invoices/${id}`) });
  const order = useQuery({ queryKey: ["order", inv.data?.order_id], enabled: !!inv.data, queryFn: () => api<Order>(`/sales-orders/${inv.data!.order_id}`) });
  const dispatches = useQuery({ queryKey: ["dispatches", inv.data?.order_id], enabled: !!inv.data,
    queryFn: () => api<Page<DispatchRow>>("/dispatches", { params: { order_id: inv.data!.order_id } }) });
  const credits = useQuery({ queryKey: ["credit-notes", Number(id)], queryFn: () => api<CreditNoteRow[]>(`/invoices/${id}/credit-notes`) });

  const [dispatchOpen, setDispatchOpen] = useState(false);
  const [creditOpen, setCreditOpen] = useState(false);
  const [vehicle, setVehicle] = useState("");
  const [transporter, setTransporter] = useState("");
  const [dispatchQty, setDispatchQty] = useState<Record<number, string>>({});
  const [cn, setCn] = useState({ type: "SALES_RETURN", reason: "", restock: true, lines: {} as Record<number, string> });
  const [pdfError, setPdfError] = useState<unknown>(null);

  const refreshAll = () => qc.invalidateQueries();
  const dispatch = useMutation({
    mutationFn: () => api("/dispatches", { body: {
      order_id: inv.data!.order_id, vehicle_no: vehicle || null, transporter: transporter || null,
      items: Object.entries(dispatchQty).filter(([, v]) => Number(v) > 0).map(([k, v]) => ({ order_item_id: Number(k), quantity: v })),
    } }),
    onSuccess: () => { refreshAll(); setDispatchOpen(false); toast("Dispatched: stock updated"); },
  });
  const credit = useMutation({
    mutationFn: () => api(`/invoices/${id}/credit-notes`, { body: {
      reason_type: cn.type, reason: cn.reason, restock: cn.type === "PRICE_ADJUSTMENT" ? false : cn.restock,
      lines: cn.type === "CANCELLATION" ? [] : Object.entries(cn.lines).filter(([, v]) => Number(v) > 0).map(([k, v]) =>
        cn.type === "SALES_RETURN" ? { invoice_item_id: Number(k), quantity: v } : { invoice_item_id: Number(k), taxable_amount: v }),
    } }),
    onSuccess: () => { refreshAll(); setCreditOpen(false); toast("Credit note issued"); },
  });

  if (inv.isLoading) return <Spinner />;
  if (!inv.data) return <ErrorBanner error={inv.error} />;
  const i = inv.data;
  const o = order.data;
  const pending = (o?.items ?? []).map((l) => ({ line: l, pending: Number(l.quantity_approved ?? 0) - Number(l.quantity_dispatched) }));
  const canDispatch = canAct && o && ["INVOICED", "PARTIALLY_DISPATCHED"].includes(o.status) && i.status !== "CANCELLED";

  function openDispatch() {
    setDispatchQty(Object.fromEntries(pending.filter((p) => p.pending > 0).map((p) => [p.line.id, String(p.pending)])));
    setDispatchOpen(true);
  }

  return (
    <>
      <PageHeader title={i.invoice_no} subtitle={`${i.customer_name} · ${date(i.invoice_date)} · order ${i.order_no}`}
        back={<Link to="/admin/invoices" className="mb-2 flex items-center gap-1 text-sm text-navy-400"><ArrowLeft className="h-4 w-4" />Invoices</Link>}
        actions={<>
          <StatusBadge status={i.status} />
          <Button variant="secondary" icon={<Download className="h-4 w-4" />}
            onClick={() => download(`/invoices/${i.id}/pdf`).catch(setPdfError)}>PDF</Button>
          {canDispatch && <Button variant="accent" icon={<Truck className="h-4 w-4" />} onClick={openDispatch}>Dispatch</Button>}
          {canAct && i.status !== "CANCELLED" && <Button variant="secondary" icon={<FileMinus className="h-4 w-4" />} onClick={() => setCreditOpen(true)}>Credit note</Button>}
          {canAct && !isZero(i.balance) && <Link to={`/admin/payments?customer=${i.customer_id}`}><Button variant="secondary" icon={<IndianRupee className="h-4 w-4" />}>Record payment</Button></Link>}
        </>} />
      <ErrorBanner error={pdfError} className="mb-3" />

      <div className="grid gap-4 lg:grid-cols-3">
        <Card className="lg:col-span-2" title={<span>Tax invoice · place of supply <b>{i.place_of_supply}</b></span>}>
          <Table>
            <thead><tr><Th>Item</Th><Th>HSN</Th><Th right>Qty</Th><Th right>Rate</Th><Th right>Taxable</Th>
              {i.supply_type === "INTRA_STATE" ? <><Th right>CGST</Th><Th right>SGST</Th></> : <Th right>IGST</Th>}<Th right>Total</Th></tr></thead>
            <tbody className="divide-y divide-navy-100">
              {i.items.map((l) => (
                <tr key={l.id}>
                  <Td className="font-medium">{l.description}</Td><Td>{l.hsn_code}</Td>
                  <Td right>{qty(l.quantity)} {l.unit_code}</Td><Td right>{inr(l.unit_price)}</Td><Td right>{inr(l.taxable_amount)}</Td>
                  {i.supply_type === "INTRA_STATE" ? <>
                    <Td right><span className="text-xs text-navy-400">{qty(l.cgst_rate)}%</span> {inr(l.cgst_amount)}</Td>
                    <Td right><span className="text-xs text-navy-400">{qty(l.sgst_rate)}%</span> {inr(l.sgst_amount)}</Td>
                  </> : <Td right><span className="text-xs text-navy-400">{qty(l.igst_rate)}%</span> {inr(l.igst_amount)}</Td>}
                  <Td right className="font-medium">{inr(l.line_total)}</Td>
                </tr>
              ))}
            </tbody>
          </Table>
          <div className="grid gap-4 border-t border-navy-100 p-4 sm:grid-cols-2">
            <div className="text-sm">
              <div className="label">Billed to</div>
              <div className="font-medium">{i.customer_name}</div>
              <div className="text-navy-400">GSTIN {i.customer_gstin ?? "Unregistered"}</div>
              <p className="mt-3 text-xs italic text-navy-400">{i.amount_in_words}</p>
            </div>
            <OrderTotals supply={i.supply_type} taxable={i.taxable_amount} cgst={i.cgst_amount} sgst={i.sgst_amount}
              igst={i.igst_amount} total={i.total_amount} totalLabel="Invoice total" />
          </div>
        </Card>

        <div className="space-y-4">
          <Card title="Settlement" className="p-0">
            <dl className="space-y-1.5 p-4 text-sm">
              <div className="flex justify-between"><dt className="text-navy-400">Invoice total</dt><dd className="num">{inr(i.total_amount)}</dd></div>
              <div className="flex justify-between"><dt className="text-navy-400">Credit notes</dt><dd className="num">{isZero(i.credited_amount) ? inr(i.credited_amount) : `−${inr(i.credited_amount)}`}</dd></div>
              <div className="flex justify-between"><dt className="text-navy-400">Payments received</dt><dd className="num">{isZero(i.paid_amount) ? inr(i.paid_amount) : `−${inr(i.paid_amount)}`}</dd></div>
              <div className="flex justify-between border-t border-navy-100 pt-2 text-base font-semibold"><dt>Balance due</dt><dd className="num">{inr(i.balance)}</dd></div>
            </dl>
          </Card>
          <Card title="Dispatches" className="p-0">
            {!dispatches.data?.items.length ? <p className="p-4 text-sm text-navy-400">Not dispatched yet.</p> : (
              <ul className="divide-y divide-navy-100 text-sm">
                {dispatches.data.items.map((d) => (
                  <li key={d.id} className="px-4 py-2.5">
                    <div className="flex justify-between"><span className="font-medium">{d.dispatch_no}</span><span className="text-navy-400">{date(d.dispatch_date)}</span></div>
                    <div className="text-xs text-navy-400">{d.items.map((x) => `${qty(x.quantity)} packets`).join(", ")}{d.vehicle_no && ` · ${d.vehicle_no}`}</div>
                  </li>
                ))}
              </ul>
            )}
          </Card>
          {!!credits.data?.length && (
            <Card title="Credit notes" className="p-0">
              <ul className="divide-y divide-navy-100 text-sm">
                {credits.data.map((c) => (
                  <li key={c.id} className="px-4 py-2.5">
                    <div className="flex justify-between"><span className="font-medium">{c.credit_note_no}</span><span className="num">{inr(c.total_amount)}</span></div>
                    <div className="text-xs text-navy-400">{label(c.reason_type)}{c.restock && " · restocked"} · {c.reason}</div>
                  </li>
                ))}
              </ul>
            </Card>
          )}
        </div>
      </div>

      <Modal open={dispatchOpen} onClose={() => setDispatchOpen(false)} title="Record dispatch"
        footer={<><Button variant="secondary" onClick={() => setDispatchOpen(false)}>Cancel</Button>
          <Button variant="accent" loading={dispatch.isPending} onClick={() => dispatch.mutate()}>Dispatch & update stock</Button></>}>
        <ErrorBanner error={dispatch.error} className="mb-3" />
        <div className="space-y-3">
          {pending.filter((p) => p.pending > 0).map(({ line, pending: max }) => (
            <Field key={line.id} label={`${line.product_name} (pending ${max})`}>
              <input className="input" inputMode="numeric" value={dispatchQty[line.id] ?? ""}
                onChange={(e) => setDispatchQty((d) => ({ ...d, [line.id]: e.target.value.replace(/\D/g, "") }))} />
            </Field>
          ))}
          <div className="grid grid-cols-2 gap-3">
            <Field label="Vehicle no"><input className="input" value={vehicle} onChange={(e) => setVehicle(e.target.value.toUpperCase())} placeholder="TN37 AB 1234" /></Field>
            <Field label="Transporter"><input className="input" value={transporter} onChange={(e) => setTransporter(e.target.value)} /></Field>
          </div>
          <p className="text-xs text-navy-400">Posts a SALES_DISPATCH movement for each line at weighted-average cost. More than the approved, undispatched quantity is refused.</p>
        </div>
      </Modal>

      <Modal open={creditOpen} onClose={() => setCreditOpen(false)} title="Issue credit note"
        footer={<><Button variant="secondary" onClick={() => setCreditOpen(false)}>Cancel</Button>
          <Button variant="danger" disabled={cn.reason.trim().length < 3} loading={credit.isPending} onClick={() => credit.mutate()}>Issue credit note</Button></>}>
        <ErrorBanner error={credit.error} className="mb-3" />
        <div className="space-y-3">
          <Field label="Type">
            <select className="input" value={cn.type} onChange={(e) => setCn({ ...cn, type: e.target.value, lines: {} })}>
              <option value="SALES_RETURN">Sales return (goods returned)</option>
              <option value="PRICE_ADJUSTMENT">Price adjustment</option>
              <option value="CANCELLATION">Cancel invoice (full reversal)</option>
            </select>
          </Field>
          {cn.type !== "CANCELLATION" && i.items.map((l) => (
            <Field key={l.id} label={cn.type === "SALES_RETURN" ? `${l.description}: quantity returned` : `${l.description}: taxable amount to credit`}>
              <input className="input" inputMode="decimal" value={cn.lines[l.id] ?? ""}
                onChange={(e) => setCn({ ...cn, lines: { ...cn.lines, [l.id]: e.target.value.replace(/[^\d.]/g, "") } })} />
            </Field>
          ))}
          {cn.type !== "PRICE_ADJUSTMENT" && (
            <label className="flex items-center gap-2 text-sm">
              <input type="checkbox" checked={cn.restock} onChange={(e) => setCn({ ...cn, restock: e.target.checked })} />
              Return the goods to stock (SALES_RETURN movement)
            </label>
          )}
          <Field label="Reason"><input className="input" value={cn.reason} onChange={(e) => setCn({ ...cn, reason: e.target.value })} /></Field>
          <p className="text-xs text-navy-400">GST is reversed using the invoice's own supply type and rates.</p>
        </div>
      </Modal>
    </>
  );
}
