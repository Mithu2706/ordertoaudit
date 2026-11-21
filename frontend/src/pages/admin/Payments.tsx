/** Admin: record receipts (auto oldest-first or explicit allocation), receipts list, outstanding + ageing. */
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { IndianRupee, Shuffle, Undo2 } from "lucide-react";
import { useEffect, useState } from "react";
import { useSearchParams } from "react-router-dom";
import {
  Badge, Button, Card, EmptyState, ErrorBanner, Field, Modal, PageHeader, Spinner, Stat, Table, Td, Th, cx, useToast,
} from "@/components/ui";
import { api } from "@/lib/api";
import { useAuth } from "@/lib/auth";
import { date, inr, isNegative, isZero, label, today } from "@/lib/format";
import type { Customer, Page, Payment, Receivable } from "@/lib/types";

const MODES = ["UPI", "BANK_TRANSFER", "CASH", "CHEQUE"];

export default function PaymentsPage() {
  const { user } = useAuth();
  const canAct = user?.role === "ADMIN";
  const [params] = useSearchParams();
  const qc = useQueryClient();
  const toast = useToast();
  const [customerId, setCustomerId] = useState<number | "">(params.get("customer") ? Number(params.get("customer")) : "");
  const [amount, setAmount] = useState("");
  const [mode, setMode] = useState("UPI");
  const [ref, setRef] = useState("");
  const [payDate, setPayDate] = useState(today());
  const [manual, setManual] = useState(false);
  const [alloc, setAlloc] = useState<Record<number, string>>({});
  const [reversing, setReversing] = useState<Payment | null>(null);
  const [moving, setMoving] = useState<Payment | null>(null);

  const customers = useQuery({ queryKey: ["customers", "all"], queryFn: () => api<Page<Customer>>("/customers", { params: { limit: 200 } }) });
  const receivables = useQuery({ queryKey: ["receivables"], queryFn: () => api<Receivable[]>("/receivables") });
  const payments = useQuery({ queryKey: ["payments"], queryFn: () => api<Page<Payment>>("/payments", { params: { limit: 50 } }) });
  const selected = receivables.data?.find((r) => r.customer_id === customerId);
  useEffect(() => setAlloc({}), [customerId]);

  const record = useMutation({
    mutationFn: () => api<Payment>("/payments", { body: {
      customer_id: customerId, amount, mode, reference_no: ref || null, payment_date: payDate,
      allocations: manual ? Object.entries(alloc).filter(([, v]) => Number(v) > 0).map(([k, v]) => ({ invoice_id: Number(k), amount: v })) : null,
    } }),
    onSuccess: (p) => {
      qc.invalidateQueries();
      toast(`${p.receipt_no}: ${inr(p.amount)} recorded`);
      setAmount(""); setRef(""); setAlloc({});
    },
  });

  return (
    <>
      <PageHeader title="Payments & receivables" subtitle="Receipts are applied to the oldest unpaid invoice first unless you allocate them yourself" />
      <div className="mb-4 grid gap-3 sm:grid-cols-3">
        <Stat label="Customers with balance" value={(receivables.data ?? []).filter((r) => !isZero(r.outstanding)).length} />
        <Stat label="Open invoices" value={(receivables.data ?? []).reduce((n, r) => n + r.open_invoices.length, 0)} />
        <Stat label="Receipts recorded" value={payments.data?.total ?? "—"} />
      </div>

      <div className="grid gap-4 lg:grid-cols-5">
        {canAct && (
          <Card title="Record a receipt" className="lg:col-span-2">
            <div className="space-y-3 p-4">
              <Field label="Customer">
                <select className="input" value={customerId} onChange={(e) => setCustomerId(e.target.value ? Number(e.target.value) : "")}>
                  <option value="">Select customer…</option>
                  {customers.data?.items.map((c) => <option key={c.id} value={c.id}>{c.name}</option>)}
                </select>
              </Field>
              {selected && (
                <div className="rounded-lg bg-navy-50 px-3 py-2 text-sm">Outstanding <b>{inr(selected.outstanding)}</b>
                  {!isZero(selected.unallocated_advance) && <span className="text-navy-400"> (after {inr(selected.unallocated_advance)} advance)</span>}</div>
              )}
              <div className="grid grid-cols-2 gap-3">
                <Field label="Amount (₹)"><input className="input" inputMode="decimal" value={amount} onChange={(e) => setAmount(e.target.value.replace(/[^\d.]/g, ""))} /></Field>
                <Field label="Date"><input type="date" className="input" value={payDate} max={today()} onChange={(e) => setPayDate(e.target.value)} /></Field>
                <Field label="Mode"><select className="input" value={mode} onChange={(e) => setMode(e.target.value)}>{MODES.map((m) => <option key={m} value={m}>{label(m)}</option>)}</select></Field>
                <Field label="UTR / cheque no"><input className="input" value={ref} onChange={(e) => setRef(e.target.value)} /></Field>
              </div>
              {selected && selected.open_invoices.length > 0 && (
                <div>
                  <label className="flex items-center gap-2 text-sm">
                    <input type="checkbox" checked={manual} onChange={(e) => setManual(e.target.checked)} /> Allocate to specific invoices
                  </label>
                  {manual && (
                    <div className="mt-2 space-y-2">
                      {selected.open_invoices.map((oi) => (
                        <div key={oi.invoice_id} className="flex items-center gap-2 text-sm">
                          <span className="flex-1">{oi.invoice_no} <span className="text-navy-400">· due {inr(oi.balance)}</span></span>
                          <input className="input w-28 text-right" inputMode="decimal" value={alloc[oi.invoice_id] ?? ""}
                            onChange={(e) => setAlloc((a) => ({ ...a, [oi.invoice_id]: e.target.value.replace(/[^\d.]/g, "") }))} />
                        </div>
                      ))}
                    </div>
                  )}
                </div>
              )}
              <ErrorBanner error={record.error} />
              <Button variant="accent" className="w-full" icon={<IndianRupee className="h-4 w-4" />} loading={record.isPending}
                disabled={!customerId || !amount} onClick={() => record.mutate()}>Record receipt</Button>
            </div>
          </Card>
        )}

        <Card title="Outstanding & ageing" className={canAct ? "lg:col-span-3" : "lg:col-span-5"}>
          {receivables.isLoading ? <Spinner /> : !receivables.data?.length ? <EmptyState title="No receivables" /> : (
            <Table>
              <thead><tr><Th>Customer</Th><Th right>Invoiced</Th><Th right>Received</Th><Th right>Outstanding</Th>
                {Object.keys(receivables.data[0].ageing).map((b) => <Th key={b} right>{b} d</Th>)}</tr></thead>
              <tbody className="divide-y divide-navy-100">
                {receivables.data.map((r) => (
                  <tr key={r.customer_id}>
                    <Td><div className="font-medium">{r.customer_name}</div><div className="text-xs text-navy-400">{r.customer_code}</div></Td>
                    <Td right>{inr(r.invoiced)}</Td><Td right>{inr(r.received)}</Td>
                    <Td right className="font-semibold">{isNegative(r.outstanding) ? <Badge tone="green">Advance {inr(r.outstanding.slice(1))}</Badge> : inr(r.outstanding)}</Td>
                    {Object.entries(r.ageing).map(([b, v]) => <Td key={b} right className={isZero(v) ? "text-navy-200" : ""}>{inr(v)}</Td>)}
                  </tr>
                ))}
              </tbody>
            </Table>
          )}
        </Card>
      </div>

      <Card title="Recent receipts" className="mt-4">
        {payments.isLoading ? <Spinner /> : !payments.data?.items.length ? <EmptyState title="No receipts yet" /> : (
          <Table>
            <thead><tr><Th>Receipt</Th><Th>Date</Th><Th>Customer</Th><Th>Mode</Th><Th>Applied to</Th><Th right>Amount</Th><Th right>Advance</Th>{canAct && <Th />}</tr></thead>
            <tbody className="divide-y divide-navy-100">
              {payments.data.items.map((p) => (
                <tr key={p.id} className={cx(p.reversed_on && "bg-red-50/40")}>
                  <Td className="font-medium">
                    <span className={cx(p.reversed_on && "text-navy-400 line-through")}>{p.receipt_no}</span>
                    {p.reversed_on && (
                      <div className="mt-0.5 flex flex-wrap items-center gap-1 text-xs font-normal">
                        <Badge tone="red">Reversed {date(p.reversed_on)}</Badge>
                        <span className="whitespace-normal text-navy-400">{p.reversal_reason}</span>
                      </div>
                    )}
                  </Td>
                  <Td className="text-navy-400">{date(p.payment_date)}</Td>
                  <Td>{p.customer_name}</Td><Td>{label(p.mode)}{p.reference_no && <span className="text-xs text-navy-400"> · {p.reference_no}</span>}</Td>
                  <Td className="text-xs">{p.allocations.map((a) => `${a.invoice_no} (${inr(a.amount)})`).join(", ") || "—"}</Td>
                  <Td right className={cx("font-medium", p.reversed_on && "text-navy-400 line-through")}>{inr(p.amount)}</Td><Td right>{inr(p.unallocated)}</Td>
                  {canAct && (
                    <Td right>
                      {!p.reversed_on && (
                        <div className="flex justify-end gap-1">
                          <Button variant="ghost" size="sm" icon={<Shuffle className="h-3.5 w-3.5" />} onClick={() => setMoving(p)}
                            aria-label={`Re-allocate ${p.receipt_no}`}>Re-allocate</Button>
                          <Button variant="ghost" size="sm" icon={<Undo2 className="h-3.5 w-3.5" />} onClick={() => setReversing(p)}
                            aria-label={`Reverse ${p.receipt_no}`}>Reverse</Button>
                        </div>
                      )}
                    </Td>
                  )}
                </tr>
              ))}
            </tbody>
          </Table>
        )}
      </Card>
      {reversing && <ReverseDialog payment={reversing} onClose={() => setReversing(null)} />}
      {moving && <ReallocateDialog payment={moving} onClose={() => setMoving(null)} />}
    </>
  );
}

/** Reverse a receipt (bounced cheque, failed transfer). The server re-opens the invoices it paid. */
function ReverseDialog({ payment, onClose }: { payment: Payment; onClose: () => void }) {
  const [reason, setReason] = useState(payment.mode === "CHEQUE" ? `Cheque ${payment.reference_no ?? ""} returned: ` : "");
  const [when, setWhen] = useState(today());
  const qc = useQueryClient();
  const toast = useToast();
  const reverse = useMutation({
    mutationFn: () => api<Payment>(`/payments/${payment.id}/reverse`, { body: { reason: reason.trim(), reversal_date: when } }),
    onSuccess: (p) => { qc.invalidateQueries(); toast(`${p.receipt_no} reversed; the invoices it paid are due again`); onClose(); },
  });
  return (
    <Modal open onClose={onClose} title={`Reverse receipt ${payment.receipt_no}`}
      footer={<>
        <Button variant="secondary" onClick={onClose}>Back</Button>
        <Button variant="danger" icon={<Undo2 className="h-4 w-4" />} loading={reverse.isPending}
          disabled={reason.trim().length < 3} onClick={() => reverse.mutate()}>Reverse receipt</Button>
      </>}>
      <div className="space-y-3 text-sm">
        <p className="text-navy-600">
          {inr(payment.amount)} from <b>{payment.customer_name}</b> ({label(payment.mode)}{payment.reference_no ? ` · ${payment.reference_no}` : ""}, {date(payment.payment_date)}).
        </p>
        {payment.allocations.length > 0 && (
          <p className="rounded-lg bg-amber-50 p-2 text-xs text-amber-700">
            These invoices become due again: {payment.allocations.map((a) => `${a.invoice_no} (${inr(a.amount)})`).join(", ")}.
          </p>
        )}
        <p className="text-xs text-navy-400">The receipt stays on record and in the audit trail. Collections reports show a negative line on the reversal date.</p>
        <ErrorBanner error={reverse.error} />
        <Field label="Reason (required)"><input className="input" autoFocus value={reason} onChange={(e) => setReason(e.target.value)} placeholder="e.g. Cheque 004512 returned: insufficient funds" /></Field>
        <Field label="Reversal date"><input type="date" className="input" value={when} min={payment.payment_date} max={today()} onChange={(e) => setWhen(e.target.value)} /></Field>
      </div>
    </Modal>
  );
}

/** Move a receipt to different invoices of the same customer. The server checks every limit. */
function ReallocateDialog({ payment, onClose }: { payment: Payment; onClose: () => void }) {
  const qc = useQueryClient();
  const toast = useToast();
  const rec = useQuery({ queryKey: ["receivables", payment.customer_id],
    queryFn: () => api<Receivable[]>("/receivables", { params: { customer_id: payment.customer_id } }) });
  const current = Object.fromEntries(payment.allocations.map((a) => [a.invoice_id, a]));
  // Invoices this receipt could go to: the customer's open invoices plus the ones it pays now.
  const rows = [
    ...(rec.data?.[0]?.open_invoices ?? []).map((oi) => ({ id: oi.invoice_id, no: oi.invoice_no, due: oi.balance })),
    ...payment.allocations.filter((a) => !(rec.data?.[0]?.open_invoices ?? []).some((oi) => oi.invoice_id === a.invoice_id))
      .map((a) => ({ id: a.invoice_id, no: a.invoice_no, due: "0.00" })),
  ];
  const [amounts, setAmounts] = useState<Record<number, string>>(
    Object.fromEntries(payment.allocations.map((a) => [a.invoice_id, a.amount])));
  const [reason, setReason] = useState("");
  const save = useMutation({
    mutationFn: () => api<Payment>(`/payments/${payment.id}/reallocate`, { body: {
      reason: reason.trim(),
      allocations: Object.entries(amounts).filter(([, v]) => /[1-9]/.test(v)).map(([id, v]) => ({ invoice_id: Number(id), amount: v })),
    } }),
    onSuccess: (p) => { qc.invalidateQueries(); toast(`${p.receipt_no} re-allocated; advance now ${inr(p.unallocated)}`); onClose(); },
  });
  return (
    <Modal wide open onClose={onClose} title={`Re-allocate receipt ${payment.receipt_no}`}
      footer={<>
        <Button variant="secondary" onClick={onClose}>Cancel</Button>
        <Button variant="accent" icon={<Shuffle className="h-4 w-4" />} loading={save.isPending}
          disabled={reason.trim().length < 3} onClick={() => save.mutate()}>Save allocation</Button>
      </>}>
      <p className="mb-3 text-sm text-navy-600">{inr(payment.amount)} from <b>{payment.customer_name}</b>. Whatever you don't
        allocate stays as an advance. The receipt itself (number, date, amount) doesn't change.</p>
      <ErrorBanner error={save.error ?? rec.error} className="mb-3" />
      {rec.isLoading ? <Spinner /> : !rows.length ? <EmptyState title="This customer has no open invoices" /> : (
        <Table>
          <thead><tr><Th>Invoice</Th><Th right>Due now</Th><Th right>From this receipt now</Th><Th right>New amount</Th></tr></thead>
          <tbody className="divide-y divide-navy-100">
            {rows.map((r) => (
              <tr key={r.id}>
                <Td className="font-medium">{r.no}</Td>
                <Td right>{inr(r.due)}</Td>
                <Td right className="text-navy-400">{current[r.id] ? inr(current[r.id].amount) : "—"}</Td>
                <Td right><input className="input w-28 text-right" inputMode="decimal" value={amounts[r.id] ?? ""} aria-label={`New amount for ${r.no}`}
                  onChange={(e) => setAmounts((a) => ({ ...a, [r.id]: e.target.value.replace(/[^\d.]/g, "") }))} /></Td>
              </tr>
            ))}
          </tbody>
        </Table>
      )}
      <Field className="mt-3" label="Reason (required)"><input className="input" value={reason} onChange={(e) => setReason(e.target.value)}
        placeholder="e.g. Customer's remittance advice names INV/2026-27/00002" /></Field>
    </Modal>
  );
}
