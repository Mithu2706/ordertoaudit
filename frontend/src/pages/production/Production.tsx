/** Production supervisor: BOM-based runs, actuals entry, posting, planned vs actual and variance. */
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { AlertTriangle, ArrowLeft, CheckCircle2, Factory, Plus, Save, Send } from "lucide-react";
import { useEffect, useState } from "react";
import { Link, useNavigate, useParams } from "react-router-dom";
import { Bar, BarChart, CartesianGrid, Cell, ReferenceLine, ResponsiveContainer, Tooltip, XAxis, YAxis } from "recharts";
import {
  Badge, Button, Card, EmptyState, ErrorBanner, Field, Modal, PageHeader, Spinner, Stat, StatusBadge, Table, Td, Th, cx, useToast,
} from "@/components/ui";
import { api } from "@/lib/api";
import { useAuth } from "@/lib/auth";
import { date, inr, isNegative, pct, qty, roundStr, today } from "@/lib/format";
import type { Page, Product, ProductionRun, RunSummary } from "@/lib/types";

function VarianceBadge({ value, alert }: { value: string | null; alert: boolean }) {
  if (value === null) return <span className="text-navy-200">—</span>;
  return <Badge tone={alert ? (isNegative(value) ? "red" : "amber") : "green"}>{alert && <AlertTriangle className="h-3 w-3" />}{pct(value, true)}</Badge>;
}

// ---- Run list ------------------------------------------------------------------------------
export function RunList() {
  const { user } = useAuth();
  const canAct = user?.role === "PRODUCTION" || user?.role === "ADMIN";
  const navigate = useNavigate();
  const qc = useQueryClient();
  const [alertsOnly, setAlertsOnly] = useState(false);
  const [open, setOpen] = useState(false);
  const [form, setForm] = useState({ product_id: "", batch_count: "1", production_date: today() });
  const runs = useQuery({ queryKey: ["runs", alertsOnly], queryFn: () => api<Page<RunSummary>>("/production-runs", { params: { alerts_only: alertsOnly, limit: 100 } }) });
  const products = useQuery({ queryKey: ["products"], queryFn: () => api<Page<Product>>("/products", { params: { active: true } }) });
  const names = Object.fromEntries((products.data?.items ?? []).map((p) => [p.id, p.name]));
  const create = useMutation({
    mutationFn: () => api<ProductionRun>("/production-runs", { body: { ...form, product_id: Number(form.product_id) } }),
    onSuccess: (r) => { qc.invalidateQueries({ queryKey: ["runs"] }); navigate(`/production/${r.id}`); },
  });

  return (
    <>
      <PageHeader title="Production runs" subtitle="Plan from the BOM, record actual usage and output, post to stock"
        actions={canAct && <Button variant="accent" icon={<Plus className="h-4 w-4" />} onClick={() => setOpen(true)}>New run</Button>} />
      <label className="mb-3 inline-flex items-center gap-2 text-sm">
        <input type="checkbox" checked={alertsOnly} onChange={(e) => setAlertsOnly(e.target.checked)} /> Show only runs with variance alerts
      </label>
      <ErrorBanner error={runs.error} />
      <Card>
        {runs.isLoading ? <Spinner /> : !runs.data?.items.length ? (
          <EmptyState icon={<Factory className="h-5 w-5" />} title={alertsOnly ? "No variance alerts" : "No production runs yet"} hint="Start a run from the product's active BOM." />
        ) : (
          <Table>
            <thead><tr><Th>Run</Th><Th>Date</Th><Th>Product</Th><Th>Status</Th><Th right>Expected</Th><Th right>Good</Th><Th>Yield var.</Th><Th right>Cost / unit</Th></tr></thead>
            <tbody className="divide-y divide-navy-100">
              {runs.data.items.map((r) => (
                <tr key={r.id} className="hover:bg-navy-50/50">
                  <Td><Link to={`/production/${r.id}`} className="font-medium hover:underline">{r.run_no}</Link></Td>
                  <Td className="text-navy-400">{date(r.production_date)}</Td>
                  <Td>{names[r.product_id] ?? r.product_id}</Td>
                  <Td><StatusBadge status={r.status} /></Td>
                  <Td right>{qty(r.expected_output)}</Td>
                  <Td right>{qty(r.actual_good_output)}</Td>
                  <Td><VarianceBadge value={r.yield_variance_pct} alert={r.has_variance_alert} /></Td>
                  <Td right>{r.cost_per_good_unit ? inr(roundStr(r.cost_per_good_unit, 2)) : "—"}</Td>
                </tr>
              ))}
            </tbody>
          </Table>
        )}
      </Card>

      <Modal open={open} onClose={() => setOpen(false)} title="New production run"
        footer={<><Button variant="secondary" onClick={() => setOpen(false)}>Cancel</Button>
          <Button variant="accent" disabled={!form.product_id} loading={create.isPending} onClick={() => create.mutate()}>Create from BOM</Button></>}>
        <ErrorBanner error={create.error} className="mb-3" />
        <div className="space-y-3">
          <Field label="Product">
            <select className="input" value={form.product_id} onChange={(e) => setForm({ ...form, product_id: e.target.value })}>
              <option value="">Select…</option>
              {products.data?.items.map((p) => <option key={p.id} value={p.id}>{p.name}</option>)}
            </select>
          </Field>
          <div className="grid grid-cols-2 gap-3">
            <Field label="Batches" hint="Planned quantities = BOM × batches"><input className="input" inputMode="decimal" value={form.batch_count} onChange={(e) => setForm({ ...form, batch_count: e.target.value })} /></Field>
            <Field label="Production date"><input type="date" className="input" value={form.production_date} max={today()} onChange={(e) => setForm({ ...form, production_date: e.target.value })} /></Field>
          </div>
        </div>
      </Modal>
    </>
  );
}

// ---- Run detail: actuals entry (draft) or results (posted) ------------------------------------
export function RunDetail() {
  const { id } = useParams();
  const { user } = useAuth();
  const canAct = user?.role === "PRODUCTION" || user?.role === "ADMIN";
  const qc = useQueryClient();
  const toast = useToast();
  const run = useQuery({ queryKey: ["run", Number(id)], queryFn: () => api<ProductionRun>(`/production-runs/${id}`) });
  const [actual, setActual] = useState<Record<number, string>>({});
  const [damaged, setDamaged] = useState<Record<number, string>>({});
  const [out, setOut] = useState({ good: "", damaged: "0", wastage: "0", wastageUnit: "KG", labour: "", power: "" });
  const [confirm, setConfirm] = useState(false);

  useEffect(() => {
    const r = run.data;
    if (!r || r.status !== "DRAFT") return;
    setActual(Object.fromEntries(r.consumption.map((c) => [c.item_id, qty(c.actual_quantity ?? c.planned_quantity).replace(/,/g, "")])));
    setDamaged(Object.fromEntries(r.consumption.map((c) => [c.item_id, qty(c.damaged_quantity).replace(/,/g, "")])));
    setOut({
      good: r.actual_good_output ? qty(r.actual_good_output).replace(/,/g, "") : "", damaged: qty(r.damaged_output),
      wastage: qty(r.wastage_qty), wastageUnit: r.wastage_unit_code ?? "KG",
      labour: r.labour_cost === "0.00" ? "" : r.labour_cost, power: r.power_gas_cost === "0.00" ? "" : r.power_gas_cost,
    });
  }, [run.data]);

  const actualsBody = () => ({
    consumption: run.data!.consumption.map((c) => ({ item_id: c.item_id, actual_quantity: actual[c.item_id] || "0",
      damaged_quantity: c.component_type === "PACKAGING" ? damaged[c.item_id] || "0" : "0" })),
    actual_good_output: out.good || "0", damaged_output: out.damaged || "0", wastage_qty: out.wastage || "0",
    wastage_unit_code: Number(out.wastage) > 0 ? out.wastageUnit : null,
    labour_cost: out.labour || "0", power_gas_cost: out.power || "0",
  });
  const save = useMutation({ mutationFn: () => api<ProductionRun>(`/production-runs/${id}/actuals`, { method: "PUT", body: actualsBody() }),
    onSuccess: (r) => { qc.setQueryData(["run", r.id], r); toast("Actuals saved"); } });
  const post = useMutation({
    mutationFn: async () => {
      await api(`/production-runs/${id}/actuals`, { method: "PUT", body: actualsBody() });
      return api<ProductionRun>(`/production-runs/${id}/post`, { method: "POST" });
    },
    onSuccess: (r) => { qc.setQueryData(["run", r.id], r); qc.invalidateQueries({ queryKey: ["runs"] }); setConfirm(false); toast("Run posted: stock updated"); },
  });

  if (run.isLoading) return <Spinner />;
  if (!run.data) return <ErrorBanner error={run.error} />;
  const r = run.data;
  const draft = r.status === "DRAFT" && canAct;

  return (
    <>
      <PageHeader title={r.run_no} subtitle={`${r.product_name} · ${date(r.production_date)} · BOM v${r.bom_version} · ${qty(r.batch_count)} batch(es)`}
        back={<Link to="/production" className="mb-2 flex items-center gap-1 text-sm text-navy-400"><ArrowLeft className="h-4 w-4" />Production runs</Link>}
        actions={<><StatusBadge status={r.status} />{r.has_variance_alert && <Badge tone="amber"><AlertTriangle className="h-3 w-3" />Variance alert</Badge>}</>} />

      {r.status === "POSTED" && (
        <div className="mb-4 grid gap-3 sm:grid-cols-2 lg:grid-cols-4">
          <Stat label="Good output" value={`${qty(r.actual_good_output)} ${r.output_unit_code}`} hint={`Expected ${qty(r.expected_output)}`} />
          <Stat label="Yield variance" value={pct(r.yield_variance_pct, true)} tone={r.yield_variance_pct && Math.abs(Number(r.yield_variance_pct)) > Number(r.variance_tolerance_pct) ? "bad" : "good"}
            hint={`Tolerance ±${pct(r.variance_tolerance_pct)}`} />
          <Stat label="Cost per good unit" value={r.cost_per_good_unit ? inr(roundStr(r.cost_per_good_unit, 2)) : "—"} hint={`Total ${inr(r.total_cost)}`} />
          <Stat label="Gross margin" value={pct(r.gross_margin_pct)} hint={`vs selling price ${inr(r.selling_price)}`} tone="good" />
        </div>
      )}

      <div className="grid gap-4 xl:grid-cols-3">
        <Card className="xl:col-span-2" title={draft ? "Record actual consumption" : "Planned vs actual consumption"}>
          <Table>
            <thead><tr><Th>Component</Th><Th right>Planned</Th><Th right>{draft ? "Used" : "Used"}</Th><Th right>Damaged</Th>
              {!draft && <><Th right>Total</Th><Th>Variance</Th><Th right>Cost</Th></>}</tr></thead>
            <tbody className="divide-y divide-navy-100">
              {r.consumption.map((c) => (
                <tr key={c.item_id} className={cx(c.is_variance_alert && "bg-amber-50/40")}>
                  <Td><div className="font-medium">{c.item_name}</div><div className="text-xs text-navy-400">{c.component_type === "RAW_MATERIAL" ? "Raw material" : "Packaging"} · {c.unit_code}</div></Td>
                  <Td right>{qty(c.planned_quantity)}{draft && c.component_type === "PACKAGING" && <div className="text-[10px] text-navy-400">re-based to good output on posting</div>}</Td>
                  <Td right>{draft ? <input className="input w-24 text-right" inputMode="decimal" aria-label={`${c.item_name} used`}
                    value={actual[c.item_id] ?? ""} onChange={(e) => setActual({ ...actual, [c.item_id]: e.target.value.replace(/[^\d.]/g, "") })} /> : qty(c.actual_quantity)}</Td>
                  <Td right>{c.component_type !== "PACKAGING" ? <span className="text-navy-200">—</span> : draft
                    ? <input className="input w-20 text-right" inputMode="decimal" aria-label={`${c.item_name} damaged`}
                        value={damaged[c.item_id] ?? ""} onChange={(e) => setDamaged({ ...damaged, [c.item_id]: e.target.value.replace(/[^\d.]/g, "") })} />
                    : qty(c.damaged_quantity)}</Td>
                  {!draft && <>
                    <Td right className="font-medium">{qty(c.total_consumed)}</Td>
                    <Td><VarianceBadge value={c.variance_pct} alert={c.is_variance_alert} /></Td>
                    <Td right>{inr(c.total_cost)}</Td>
                  </>}
                </tr>
              ))}
            </tbody>
          </Table>
          {!draft && r.status === "POSTED" && (
            <div className="h-56 border-t border-navy-100 p-4">
              <ResponsiveContainer>
                <BarChart data={r.consumption.map((c) => ({ name: c.item_name.split(" ")[0], v: Number(c.variance_pct ?? 0), alert: c.is_variance_alert }))}>
                  <CartesianGrid strokeDasharray="3 3" stroke="#E3E7ED" vertical={false} />
                  <XAxis dataKey="name" tick={{ fontSize: 12, fill: "#5B6B82" }} />
                  <YAxis unit="%" tick={{ fontSize: 12, fill: "#5B6B82" }} width={44} />
                  <Tooltip formatter={(v: number) => [`${v.toFixed(2)}%`, "Variance"]} />
                  <ReferenceLine y={Number(r.variance_tolerance_pct)} stroke="#B4532A" strokeDasharray="4 4" />
                  <ReferenceLine y={-Number(r.variance_tolerance_pct)} stroke="#B4532A" strokeDasharray="4 4" />
                  <Bar dataKey="v" radius={[4, 4, 0, 0]}>
                    {r.consumption.map((c) => <Cell key={c.item_id} fill={c.is_variance_alert ? "#C2643A" : "#2C3E57"} />)}
                  </Bar>
                </BarChart>
              </ResponsiveContainer>
            </div>
          )}
        </Card>

        <Card title={draft ? "Output and run costs" : "Output and costing"}>
          {draft ? (
            <div className="space-y-3 p-4">
              <div className="grid grid-cols-2 gap-3">
                <Field label={`Good output (${r.output_unit_code})`} hint={`Expected ${qty(r.expected_output)}`}>
                  <input className="input" inputMode="numeric" value={out.good} onChange={(e) => setOut({ ...out, good: e.target.value.replace(/\D/g, "") })} /></Field>
                <Field label="Damaged packets" hint="Never enters stock"><input className="input" inputMode="numeric" value={out.damaged} onChange={(e) => setOut({ ...out, damaged: e.target.value.replace(/\D/g, "") })} /></Field>
                <Field label="Process wastage"><input className="input" inputMode="decimal" value={out.wastage} onChange={(e) => setOut({ ...out, wastage: e.target.value.replace(/[^\d.]/g, "") })} /></Field>
                <Field label="Wastage unit"><select className="input" value={out.wastageUnit} onChange={(e) => setOut({ ...out, wastageUnit: e.target.value })}><option>KG</option><option>G</option><option>L</option></select></Field>
                <Field label="Labour (₹)"><input className="input" inputMode="decimal" value={out.labour} onChange={(e) => setOut({ ...out, labour: e.target.value.replace(/[^\d.]/g, "") })} /></Field>
                <Field label="Gas & power (₹)"><input className="input" inputMode="decimal" value={out.power} onChange={(e) => setOut({ ...out, power: e.target.value.replace(/[^\d.]/g, "") })} /></Field>
              </div>
              <ErrorBanner error={save.error ?? post.error} />
              <div className="flex flex-wrap gap-2 pt-1">
                <Button variant="secondary" icon={<Save className="h-4 w-4" />} loading={save.isPending} onClick={() => save.mutate()}>Save draft</Button>
                <Button variant="accent" icon={<Send className="h-4 w-4" />} disabled={!out.good} onClick={() => setConfirm(true)}>Post run</Button>
              </div>
            </div>
          ) : r.status === "POSTED" ? (
            <dl className="space-y-1.5 p-4 text-sm">
              <div className="flex justify-between"><dt className="text-navy-400">Expected / good</dt><dd className="num">{qty(r.expected_output)} / {qty(r.actual_good_output)}</dd></div>
              <div className="flex justify-between"><dt className="text-navy-400">Damaged packets</dt><dd className="num">{qty(r.damaged_output)}</dd></div>
              <div className="flex justify-between"><dt className="text-navy-400">Process wastage</dt><dd className="num">{qty(r.wastage_qty)} {r.wastage_unit_code ?? ""}</dd></div>
              <div className="my-2 border-t border-navy-100" />
              <div className="flex justify-between"><dt className="text-navy-400">Raw material</dt><dd className="num">{inr(r.material_cost)}</dd></div>
              <div className="flex justify-between"><dt className="text-navy-400">Packaging (incl. damaged)</dt><dd className="num">{inr(r.packaging_cost)}</dd></div>
              <div className="flex justify-between"><dt className="text-navy-400">Labour</dt><dd className="num">{inr(r.labour_cost)}</dd></div>
              <div className="flex justify-between"><dt className="text-navy-400">Gas & power</dt><dd className="num">{inr(r.power_gas_cost)}</dd></div>
              <div className="flex justify-between border-t border-navy-100 pt-2 font-semibold"><dt>Total cost</dt><dd className="num">{inr(r.total_cost)}</dd></div>
              <div className="flex justify-between"><dt className="text-navy-400">Per good {r.output_unit_code.toLowerCase()}</dt><dd className="num">₹{r.cost_per_good_unit}</dd></div>
              <div className="flex justify-between"><dt className="text-navy-400">Margin / unit</dt><dd className="num">₹{r.gross_margin_per_unit} ({pct(r.gross_margin_pct)})</dd></div>
            </dl>
          ) : <EmptyState title={`Run ${r.status.toLowerCase()}`} />}
        </Card>
      </div>

      <Modal open={confirm} onClose={() => setConfirm(false)} title="Post production run"
        footer={<><Button variant="secondary" onClick={() => setConfirm(false)}>Back</Button>
          <Button variant="accent" icon={<CheckCircle2 className="h-4 w-4" />} loading={post.isPending} onClick={() => post.mutate()}>Post to stock</Button></>}>
        <ErrorBanner error={post.error} className="mb-3" />
        <p className="text-sm text-navy-600">In one transaction this will:</p>
        <ul className="mt-2 list-disc space-y-1 pl-5 text-sm text-navy-600">
          <li>issue the raw materials and packaging used (damaged packaging as DAMAGE),</li>
          <li>add <b>{out.good || 0}</b> good {r.output_unit_code} to finished goods at full run cost,</li>
          <li>calculate variance against a ±{pct(r.variance_tolerance_pct)} tolerance.</li>
        </ul>
        <p className="mt-3 text-sm text-navy-400">A posted run can't be edited. If any material is short, nothing is posted.</p>
      </Modal>
    </>
  );
}
