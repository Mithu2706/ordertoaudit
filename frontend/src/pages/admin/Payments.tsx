/** Admin: record receipts (auto oldest-first or explicit allocation), receipts list, outstanding + ageing. */
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { IndianRupee } from "lucide-react";
import { useEffect, useState } from "react";
import { useSearchParams } from "react-router-dom";
import {
  Badge, Button, Card, EmptyState, ErrorBanner, Field, PageHeader, Spinner, Stat, Table, Td, Th, useToast,
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
            <thead><tr><Th>Receipt</Th><Th>Date</Th><Th>Customer</Th><Th>Mode</Th><Th>Applied to</Th><Th right>Amount</Th><Th right>Advance</Th></tr></thead>
            <tbody className="divide-y divide-navy-100">
              {payments.data.items.map((p) => (
                <tr key={p.id}>
                  <Td className="font-medium">{p.receipt_no}</Td><Td className="text-navy-400">{date(p.payment_date)}</Td>
                  <Td>{p.customer_name}</Td><Td>{label(p.mode)}{p.reference_no && <span className="text-xs text-navy-400"> · {p.reference_no}</span>}</Td>
                  <Td className="text-xs">{p.allocations.map((a) => `${a.invoice_no} (${inr(a.amount)})`).join(", ") || "—"}</Td>
                  <Td right className="font-medium">{inr(p.amount)}</Td><Td right>{inr(p.unallocated)}</Td>
                </tr>
              ))}
            </tbody>
          </Table>
        )}
      </Card>
    </>
  );
}
