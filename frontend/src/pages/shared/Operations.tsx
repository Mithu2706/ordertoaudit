/** Purchases (material receipts), stock balances with stock card, and BOM viewer. */
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { AlertTriangle, PackageCheck, Plus, Send, Trash2, Undo2 } from "lucide-react";
import { useState } from "react";
import {
  Badge, Button, Card, EmptyState, ErrorBanner, Field, Modal, PageHeader, Spinner, StatusBadge, Table, Td, Th, cx, useToast,
} from "@/components/ui";
import { api } from "@/lib/api";
import { useAuth } from "@/lib/auth";
import { date, inr, label, qty, roundStr, today } from "@/lib/format";
import type { Balance, Page } from "@/lib/types";

interface Supplier { id: number; code: string; name: string; state_code: string }
interface Material { id: number; code: string; name: string; base_unit_code: string; item_type: string }
interface PurchaseSummary { id: number; purchase_no: string; supplier_id: number; supplier_invoice_no: string; received_date: string; status: string; taxable_amount: string; total_amount: string }
interface Purchase extends PurchaseSummary {
  supplier_name: string; cgst_amount: string; sgst_amount: string; igst_amount: string;
  items: { id: number; item_code: string; item_name: string; quantity: string; unit_code: string; base_quantity: string; base_unit_code: string; rate: string; taxable_amount: string; tax_amount: string; line_total: string; returned_quantity: string }[];
}
interface PurchaseReturn {
  id: number; return_no: string; return_date: string; reason: string; taxable_amount: string; cgst_amount: string;
  sgst_amount: string; igst_amount: string; total_amount: string; stock_value: string;
  items: { purchase_item_id: number; item_name: string; quantity: string; unit_code: string; line_total: string }[];
}
interface Movement { id: number; movement_date: string; movement_type: string; reference_no: string; quantity: string; unit_code: string; entered_quantity: string; entered_unit_code: string; unit_cost: string; value: string; balance_after: string; value_after: string; remarks: string | null }
interface Ledger { item_code: string; item_name: string; unit_code: string; opening_quantity: string; total_in: string; total_out: string; closing_quantity: string; closing_value: string; movements: Movement[] }
interface Bom { id: number; product_name: string; version: number; batch_output_qty: string; output_unit_code: string; is_active: boolean; notes: string | null; created_at: string; items: { id: number; item_code: string; item_name: string; component_type: string; quantity: string; unit_code: string }[] }

// ---- Purchases ---------------------------------------------------------------------------
type Line = { item_id: string; quantity: string; unit_code: string; rate: string; gst_rate: string };
const emptyLine: Line = { item_id: "", quantity: "", unit_code: "", rate: "", gst_rate: "0" };

export function Purchases() {
  const { user } = useAuth();
  const canAct = user?.role === "ADMIN" || user?.role === "PRODUCTION";
  const qc = useQueryClient();
  const toast = useToast();
  const [open, setOpen] = useState(false);
  const [view, setView] = useState<number | null>(null);
  const [form, setForm] = useState({ supplier_id: "", supplier_invoice_no: "", date: today(), lines: [{ ...emptyLine }] });

  const purchases = useQuery({ queryKey: ["purchases"], queryFn: () => api<Page<PurchaseSummary>>("/purchases", { params: { limit: 100 } }) });
  const suppliers = useQuery({ queryKey: ["suppliers"], queryFn: () => api<Page<Supplier>>("/suppliers", { params: { active: true, limit: 200 } }) });
  const raws = useQuery({ queryKey: ["raw-materials"], queryFn: () => api<Page<Material>>("/raw-materials", { params: { active: true, limit: 200 } }) });
  const packs = useQuery({ queryKey: ["packaging-materials"], queryFn: () => api<Page<Material>>("/packaging-materials", { params: { active: true, limit: 200 } }) });
  const detail = useQuery({ queryKey: ["purchase", view], enabled: !!view, queryFn: () => api<Purchase>(`/purchases/${view}`) });
  const returns = useQuery({ queryKey: ["purchase-returns", view], enabled: !!view && detail.data?.status === "POSTED",
    queryFn: () => api<PurchaseReturn[]>(`/purchases/${view}/returns`) });
  const [returning, setReturning] = useState(false);
  const materials = [...(raws.data?.items ?? []), ...(packs.data?.items ?? [])];
  const supplierName = Object.fromEntries((suppliers.data?.items ?? []).map((s) => [s.id, s.name]));

  const create = useMutation({
    mutationFn: () => api<Purchase>("/purchases", { body: {
      supplier_id: Number(form.supplier_id), supplier_invoice_no: form.supplier_invoice_no,
      supplier_invoice_date: form.date, received_date: form.date,
      items: form.lines.filter((l) => l.item_id).map((l) => ({ ...l, item_id: Number(l.item_id) })),
    } }),
    onSuccess: (p) => { qc.invalidateQueries({ queryKey: ["purchases"] }); setOpen(false); setView(p.id); toast(`${p.purchase_no} saved as draft`); },
  });
  const post = useMutation({
    mutationFn: (id: number) => api<Purchase>(`/purchases/${id}/post`, { method: "POST" }),
    onSuccess: (p) => { qc.invalidateQueries(); toast(`${p.purchase_no} received into stock`); },
  });
  const setLine = (i: number, patch: Partial<Line>) =>
    setForm((f) => ({ ...f, lines: f.lines.map((l, j) => (j === i ? { ...l, ...patch } : l)) }));

  return (
    <>
      <PageHeader title="Material receipts" subtitle="Purchases are drafted, then posted to the stock ledger at the taxable value (GST is input credit)"
        actions={canAct && <Button variant="accent" icon={<Plus className="h-4 w-4" />} onClick={() => setOpen(true)}>New purchase</Button>} />
      <ErrorBanner error={purchases.error ?? post.error} className="mb-3" />
      <div className="grid gap-4 xl:grid-cols-5">
        <Card className="xl:col-span-3">
          {purchases.isLoading ? <Spinner /> : !purchases.data?.items.length ? <EmptyState title="No purchases yet" /> : (
            <Table>
              <thead><tr><Th>Purchase</Th><Th>Received</Th><Th>Supplier</Th><Th>Bill</Th><Th>Status</Th><Th right>Total</Th><Th /></tr></thead>
              <tbody className="divide-y divide-navy-100">
                {purchases.data.items.map((p) => (
                  <tr key={p.id} className={cx("cursor-pointer hover:bg-navy-50/50", view === p.id && "bg-navy-50")} onClick={() => setView(p.id)}>
                    <Td className="font-medium">{p.purchase_no}</Td><Td className="text-navy-400">{date(p.received_date)}</Td>
                    <Td>{supplierName[p.supplier_id] ?? p.supplier_id}</Td><Td>{p.supplier_invoice_no}</Td>
                    <Td><StatusBadge status={p.status} /></Td><Td right>{inr(p.total_amount)}</Td>
                    <Td>{canAct && p.status === "DRAFT" && (
                      <Button size="sm" variant="accent" icon={<Send className="h-3.5 w-3.5" />} loading={post.isPending && post.variables === p.id}
                        onClick={(e) => { e.stopPropagation(); post.mutate(p.id); }}>Post</Button>)}</Td>
                  </tr>
                ))}
              </tbody>
            </Table>
          )}
        </Card>
        <Card className="xl:col-span-2" title={detail.data ? `${detail.data.purchase_no} · ${detail.data.supplier_name}` : "Purchase detail"}>
          {!view ? <EmptyState title="Select a purchase" /> : detail.isLoading ? <Spinner /> : detail.data && (
            <div className="p-4 text-sm">
              <ul className="divide-y divide-navy-100">
                {detail.data.items.map((l) => (
                  <li key={l.id} className="flex justify-between gap-2 py-2">
                    <div><div className="font-medium">{l.item_name}</div>
                      <div className="text-xs text-navy-400">{qty(l.quantity)} {l.unit_code} @ ₹{roundStr(l.rate, 2)}
                        {l.unit_code !== l.base_unit_code && ` = ${qty(l.base_quantity)} ${l.base_unit_code}`}</div>
                      {l.returned_quantity !== "0.0000" && <div className="text-xs text-terracotta-700">{qty(l.returned_quantity)} {l.unit_code} returned</div>}</div>
                    <div className="num">{inr(l.taxable_amount)}</div>
                  </li>
                ))}
              </ul>
              <dl className="mt-2 space-y-1 border-t border-navy-100 pt-2">
                <div className="flex justify-between"><dt className="text-navy-400">Taxable (stock value)</dt><dd className="num">{inr(detail.data.taxable_amount)}</dd></div>
                <div className="flex justify-between"><dt className="text-navy-400">Input GST</dt><dd className="num">{inr(String(
                  [detail.data.cgst_amount, detail.data.sgst_amount, detail.data.igst_amount].find((x) => x !== "0.00") ?? "0.00"))}{detail.data.igst_amount !== "0.00" ? " IGST" : ""}</dd></div>
                <div className="flex justify-between font-semibold"><dt>Bill total</dt><dd className="num">{inr(detail.data.total_amount)}</dd></div>
              </dl>
              {detail.data.status === "POSTED" && (
                <div className="mt-4 border-t border-navy-100 pt-3">
                  <div className="mb-2 flex items-center justify-between">
                    <span className="label mb-0">Returns to supplier</span>
                    {canAct && <Button size="sm" variant="secondary" icon={<Undo2 className="h-3.5 w-3.5" />} onClick={() => setReturning(true)}>Return goods</Button>}
                  </div>
                  {!returns.data?.length ? <p className="text-xs text-navy-400">None. Damaged or wrong goods can be sent back with a debit note.</p> : (
                    <ul className="space-y-2">
                      {returns.data.map((r) => (
                        <li key={r.id} className="rounded-lg bg-navy-50 p-2 text-xs">
                          <div className="flex justify-between font-medium"><span>{r.return_no} · {date(r.return_date)}</span><span className="num">−{inr(r.total_amount)}</span></div>
                          <div className="text-navy-600">{r.items.map((i) => `${qty(i.quantity)} ${i.unit_code} ${i.item_name}`).join(", ")}</div>
                          <div className="text-navy-400">{r.reason} · stock out at average cost {inr(r.stock_value)}</div>
                        </li>
                      ))}
                    </ul>
                  )}
                </div>
              )}
            </div>
          )}
        </Card>
      </div>

      {returning && detail.data && <ReturnDialog purchase={detail.data} onClose={() => setReturning(false)} />}
      <Modal wide open={open} onClose={() => setOpen(false)} title="New purchase (draft)"
        footer={<><Button variant="secondary" onClick={() => setOpen(false)}>Cancel</Button>
          <Button variant="accent" loading={create.isPending} disabled={!form.supplier_id || !form.supplier_invoice_no}
            onClick={() => create.mutate()}>Save draft</Button></>}>
        <ErrorBanner error={create.error} className="mb-3" />
        <div className="grid gap-3 sm:grid-cols-3">
          <Field label="Supplier"><select className="input" value={form.supplier_id} onChange={(e) => setForm({ ...form, supplier_id: e.target.value })}>
            <option value="">Select…</option>{suppliers.data?.items.map((s) => <option key={s.id} value={s.id}>{s.name}</option>)}</select></Field>
          <Field label="Supplier bill no"><input className="input" value={form.supplier_invoice_no} onChange={(e) => setForm({ ...form, supplier_invoice_no: e.target.value })} /></Field>
          <Field label="Bill / received date"><input type="date" className="input" value={form.date} max={today()} onChange={(e) => setForm({ ...form, date: e.target.value })} /></Field>
        </div>
        <div className="mt-4 space-y-2">
          {form.lines.map((l, i) => (
            <div key={i} className="grid grid-cols-12 items-end gap-2">
              <Field className="col-span-12 sm:col-span-4" label="Material">
                <select className="input" value={l.item_id} onChange={(e) => {
                  const m = materials.find((x) => x.id === Number(e.target.value));
                  setLine(i, { item_id: e.target.value, unit_code: m?.base_unit_code ?? "" });
                }}><option value="">Select…</option>{materials.map((m) => <option key={m.id} value={m.id}>{m.name} ({m.base_unit_code})</option>)}</select></Field>
              <Field className="col-span-3 sm:col-span-2" label="Qty"><input className="input" inputMode="decimal" value={l.quantity} onChange={(e) => setLine(i, { quantity: e.target.value })} /></Field>
              <Field className="col-span-3 sm:col-span-2" label="Unit"><select className="input" value={l.unit_code} onChange={(e) => setLine(i, { unit_code: e.target.value })}>
                {["KG", "G", "L", "ML", "PCS"].map((u) => <option key={u}>{u}</option>)}</select></Field>
              <Field className="col-span-3 sm:col-span-2" label="Rate ₹"><input className="input" inputMode="decimal" value={l.rate} onChange={(e) => setLine(i, { rate: e.target.value })} /></Field>
              <Field className="col-span-2 sm:col-span-1" label="GST %"><input className="input" inputMode="decimal" value={l.gst_rate} onChange={(e) => setLine(i, { gst_rate: e.target.value })} /></Field>
              <button className="col-span-1 mb-2 text-navy-400 hover:text-red-700" aria-label="Remove line"
                onClick={() => setForm((f) => ({ ...f, lines: f.lines.filter((_, j) => j !== i) }))}><Trash2 className="h-4 w-4" /></button>
            </div>
          ))}
          <Button size="sm" variant="ghost" icon={<Plus className="h-3.5 w-3.5" />} onClick={() => setForm((f) => ({ ...f, lines: [...f.lines, { ...emptyLine }] }))}>Add line</Button>
        </div>
      </Modal>
    </>
  );
}

/** Send goods back to the supplier. The server checks quantities and stock, and prices the debit note. */
function ReturnDialog({ purchase, onClose }: { purchase: Purchase; onClose: () => void }) {
  const [qtys, setQtys] = useState<Record<number, string>>({});
  const [reason, setReason] = useState("");
  const [when, setWhen] = useState(today());
  const qc = useQueryClient();
  const toast = useToast();
  const lines = Object.entries(qtys).filter(([, v]) => /[1-9]/.test(v));
  const save = useMutation({
    mutationFn: () => api<PurchaseReturn>(`/purchases/${purchase.id}/returns`, { body: {
      reason: reason.trim(), return_date: when, items: lines.map(([id, q]) => ({ purchase_item_id: Number(id), quantity: q.trim() })),
    } }),
    onSuccess: (r) => { qc.invalidateQueries(); toast(`${r.return_no}: goods returned, supplier debited ${inr(r.total_amount)}`); onClose(); },
  });
  return (
    <Modal wide open onClose={onClose} title={`Return goods · ${purchase.purchase_no} · ${purchase.supplier_name}`}
      footer={<>
        <Button variant="secondary" onClick={onClose}>Cancel</Button>
        <Button variant="danger" icon={<Undo2 className="h-4 w-4" />} loading={save.isPending}
          disabled={!lines.length || reason.trim().length < 3} onClick={() => save.mutate()}>Create debit note</Button>
      </>}>
      <p className="mb-3 text-xs text-navy-400">The supplier is debited at the bill rate with the same GST. The goods leave stock
        through the ledger at the current average cost. Enter only the quantities going back.</p>
      <ErrorBanner error={save.error} className="mb-3" />
      <Table>
        <thead><tr><Th>Material</Th><Th right>Received</Th><Th right>Returned</Th><Th right>Rate</Th><Th right>Return now</Th></tr></thead>
        <tbody className="divide-y divide-navy-100">
          {purchase.items.map((l) => (
            <tr key={l.id}>
              <Td>{l.item_name}</Td>
              <Td right>{qty(l.quantity)} {l.unit_code}</Td>
              <Td right className="text-navy-400">{qty(l.returned_quantity)}</Td>
              <Td right>₹{roundStr(l.rate, 2)}</Td>
              <Td right><input className="input w-24 text-right" inputMode="decimal" value={qtys[l.id] ?? ""} aria-label={`Return quantity for ${l.item_name}`}
                onChange={(e) => setQtys((q) => ({ ...q, [l.id]: e.target.value.replace(/[^\d.]/g, "") }))} /></Td>
            </tr>
          ))}
        </tbody>
      </Table>
      <div className="mt-3 grid gap-3 sm:grid-cols-3">
        <Field className="sm:col-span-2" label="Reason (required)"><input className="input" value={reason} onChange={(e) => setReason(e.target.value)} placeholder="e.g. 4 bags damp on arrival, rejected" /></Field>
        <Field label="Return date"><input type="date" className="input" value={when} min={purchase.received_date} max={today()} onChange={(e) => setWhen(e.target.value)} /></Field>
      </div>
    </Modal>
  );
}

// ---- Stock --------------------------------------------------------------------------------
const TYPES = [["RAW_MATERIAL", "Raw materials"], ["PACKAGING", "Packaging"], ["FINISHED_GOOD", "Finished goods"]] as const;

export function Stock() {
  const [type, setType] = useState<string>("RAW_MATERIAL");
  const [item, setItem] = useState<Balance | null>(null);
  const balances = useQuery({ queryKey: ["balances"], queryFn: () => api<Balance[]>("/inventory/balances") });
  const ledger = useQuery({ queryKey: ["ledger", item?.item_id], enabled: !!item, queryFn: () => api<Ledger>(`/inventory/items/${item!.item_id}/ledger`) });
  const rows = (balances.data ?? []).filter((b) => b.item_type === type);
  const lows = (balances.data ?? []).filter((b) => b.low_stock);
  return (
    <>
      <PageHeader title="Stock" subtitle="Balances are derived from the stock ledger and valued at weighted-average cost" />
      {lows.length > 0 && (
        <div className="mb-4 flex flex-wrap items-center gap-2 rounded-lg border border-amber-100 bg-amber-50 px-4 py-3 text-sm text-amber-700">
          <AlertTriangle className="h-4 w-4" /> <b>Low stock:</b>
          {lows.map((l) => <span key={l.item_id}>{l.item_name} ({qty(l.quantity)} {l.unit_code}, reorder at {qty(l.reorder_level)})</span>)}
        </div>
      )}
      <div className="mb-4 inline-flex gap-1 rounded-lg bg-white p-1 shadow-card ring-1 ring-navy-100">
        {TYPES.map(([v, l]) => (
          <button key={v} onClick={() => setType(v)} className={cx("rounded-md px-3 py-1.5 text-sm font-medium", type === v ? "bg-navy-800 text-white" : "text-navy-600 hover:bg-navy-50")}>{l}</button>
        ))}
      </div>
      <ErrorBanner error={balances.error} />
      <Card>
        {balances.isLoading ? <Spinner /> : !rows.length ? <EmptyState title="No items" /> : (
          <Table>
            <thead><tr><Th>Item</Th><Th right>On hand</Th><Th>Unit</Th><Th right>Avg cost</Th><Th right>Value</Th><Th right>Reorder at</Th><Th /></tr></thead>
            <tbody className="divide-y divide-navy-100">
              {rows.map((b) => (
                <tr key={b.item_id} className="cursor-pointer hover:bg-navy-50/50" onClick={() => setItem(b)}>
                  <Td><div className="font-medium">{b.item_name}</div><div className="text-xs text-navy-400">{b.item_code}</div></Td>
                  <Td right className="text-base font-semibold">{qty(b.quantity)}</Td><Td>{b.unit_code}</Td>
                  <Td right>₹{roundStr(b.avg_cost, 2)}</Td><Td right>{inr(b.value)}</Td><Td right className="text-navy-400">{qty(b.reorder_level)}</Td>
                  <Td>{b.low_stock && <Badge tone="amber">Low</Badge>}</Td>
                </tr>
              ))}
            </tbody>
          </Table>
        )}
      </Card>

      <Modal wide open={!!item} onClose={() => setItem(null)} title={`Stock card · ${item?.item_name ?? ""}`}>
        {ledger.isLoading ? <Spinner /> : ledger.data && (
          <>
            <div className="mb-3 grid grid-cols-4 gap-2 text-center text-sm">
              {[["Opening", ledger.data.opening_quantity], ["In", ledger.data.total_in], ["Out", ledger.data.total_out], ["Closing", ledger.data.closing_quantity]].map(([l, v]) => (
                <div key={l} className="rounded-lg bg-navy-50 py-2"><div className="text-xs text-navy-400">{l}</div><div className="font-semibold">{qty(v)} {ledger.data!.unit_code}</div></div>
              ))}
            </div>
            <Table>
              <thead><tr><Th>Date</Th><Th>Reference</Th><Th>Movement</Th><Th right>Qty</Th><Th right>Balance</Th><Th right>Value</Th></tr></thead>
              <tbody className="divide-y divide-navy-100">
                {ledger.data.movements.map((m) => (
                  <tr key={m.id}>
                    <Td className="text-navy-400">{date(m.movement_date)}</Td><Td>{m.reference_no}</Td>
                    <Td><Badge tone={m.quantity.startsWith("-") ? "terracotta" : "green"}>{label(m.movement_type)}</Badge></Td>
                    <Td right>{m.quantity.startsWith("-") ? "" : "+"}{qty(m.quantity)}
                      {m.entered_unit_code !== m.unit_code && <div className="text-[10px] text-navy-400">entered {qty(m.entered_quantity)} {m.entered_unit_code}</div>}</Td>
                    <Td right className="font-medium">{qty(m.balance_after)}</Td><Td right>{inr(m.value_after)}</Td>
                  </tr>
                ))}
              </tbody>
            </Table>
            <p className="mt-3 text-xs text-navy-400">The ledger is append-only: corrections are posted as new adjustment movements.</p>
          </>
        )}
      </Modal>
    </>
  );
}

// ---- BOMs ---------------------------------------------------------------------------------
export function Boms() {
  const boms = useQuery({ queryKey: ["boms"], queryFn: () => api<Page<Bom>>("/boms", { params: { limit: 100 } }) });
  return (
    <>
      <PageHeader title="Bills of materials" subtitle="Versioned and immutable: a change is a new version; the active version drives new runs" />
      <ErrorBanner error={boms.error} />
      {boms.isLoading ? <Spinner /> : !boms.data?.items.length ? <Card><EmptyState title="No BOMs" /></Card> : (
        <div className="grid gap-4 lg:grid-cols-2">
          {boms.data.items.map((b) => (
            <Card key={b.id} title={<span className="flex items-center gap-2"><PackageCheck className="h-4 w-4 text-terracotta-600" />{b.product_name} · v{b.version}</span>}
              actions={b.is_active ? <Badge tone="green">Active</Badge> : <Badge>Retired</Badge>}>
              <div className="px-4 pt-3 text-sm text-navy-600">Yield per batch: <b>{qty(b.batch_output_qty)} {b.output_unit_code}</b>{b.notes && <span className="text-navy-400"> · {b.notes}</span>}</div>
              <Table>
                <thead><tr><Th>Component</Th><Th>Type</Th><Th right>Per batch</Th></tr></thead>
                <tbody className="divide-y divide-navy-100">
                  {b.items.map((i) => (
                    <tr key={i.id}><Td>{i.item_name}</Td><Td className="text-navy-400">{label(i.component_type)}</Td><Td right>{qty(i.quantity)} {i.unit_code}</Td></tr>
                  ))}
                </tbody>
              </Table>
            </Card>
          ))}
        </div>
      )}
    </>
  );
}
