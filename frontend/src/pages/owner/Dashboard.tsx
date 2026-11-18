/** Owner dashboard: every figure comes from /api/dashboard, computed live on the server. */
import { useQuery } from "@tanstack/react-query";
import { AlertTriangle, Boxes, ClipboardCheck, Factory, IndianRupee, TrendingUp, Wallet } from "lucide-react";
import { Link } from "react-router-dom";
import { Area, AreaChart, CartesianGrid, ResponsiveContainer, Tooltip, XAxis, YAxis } from "recharts";
import { Badge, Card, EmptyState, ErrorBanner, PageHeader, Spinner, Stat, Table, Td, Th } from "@/components/ui";
import { api } from "@/lib/api";
import { date, inr, pct, qty, roundStr } from "@/lib/format";

interface Dash {
  as_of: string;
  month: { from: string; to: string };
  sales: { invoices: number; gross_taxable: string; gross_total: string; credited_taxable: string; net_taxable: string };
  collections: { month: string };
  receivables: { outstanding: string; overdue: string; customers: { customer_id: number; name: string; outstanding: string }[] };
  orders: { pending_approval: number; pending_with_shortage: number; awaiting_invoice: number; awaiting_dispatch: number };
  stock: { value_by_type: Record<string, string>; total_value: string; low_stock: { item_id: number; code: string; name: string; unit: string; quantity: string; reorder_level: string }[] };
  production: { runs: number; expected: string; good: string; yield_pct: string | null; alerts: number;
    latest: null | { run_id: number; run_no: string; product: string; cost_per_unit: string; margin_pct: string; yield_variance_pct: string } };
  sales_trend: { date: string; taxable: string }[];
  top_customers: { customer_id: number; name: string; total: string }[];
}

const TYPE_LABEL: Record<string, string> = { RAW_MATERIAL: "Raw materials", PACKAGING: "Packaging", FINISHED_GOOD: "Finished goods" };

export default function Dashboard() {
  const q = useQuery({ queryKey: ["dashboard"], queryFn: () => api<Dash>("/dashboard"), refetchInterval: 60_000 });
  if (q.isLoading) return <Spinner />;
  if (!q.data) return <ErrorBanner error={q.error} />;
  const d = q.data;
  const trend = d.sales_trend.map((p) => ({ day: p.date.slice(8, 10) + "/" + p.date.slice(5, 7), v: Number(p.taxable) })); // chart only
  const p = d.production;

  return (
    <>
      <PageHeader title="Business overview" subtitle={`Month to date ${date(d.month.from)} – ${date(d.month.to)} · live from the books`} />

      <div className="grid gap-3 sm:grid-cols-2 xl:grid-cols-4">
        <Stat label="Net sales (taxable)" icon={<TrendingUp className="h-4 w-4" />} value={inr(d.sales.net_taxable)}
          hint={`${d.sales.invoices} invoice(s) · ${inr(d.sales.gross_total)} incl. GST`} />
        <Stat label="Collected this month" icon={<IndianRupee className="h-4 w-4" />} value={inr(d.collections.month)} />
        <Stat label="Receivables" icon={<Wallet className="h-4 w-4" />} value={inr(d.receivables.outstanding)}
          tone={d.receivables.overdue !== "0.00" ? "warn" : "default"} hint={`Overdue (> first bucket): ${inr(d.receivables.overdue)}`} />
        <Stat label="Stock value" icon={<Boxes className="h-4 w-4" />} value={inr(d.stock.total_value)}
          hint={`${d.stock.low_stock.length} item(s) at or below reorder level`} tone={d.stock.low_stock.length ? "warn" : "default"} />
      </div>

      <div className="mt-4 grid gap-4 xl:grid-cols-3">
        <Card className="xl:col-span-2" title="Sales: last 30 days (taxable value)">
          <div className="h-64 p-3">
            <ResponsiveContainer>
              <AreaChart data={trend} margin={{ left: 8, right: 8, top: 8 }}>
                <defs><linearGradient id="g" x1="0" y1="0" x2="0" y2="1"><stop offset="0%" stopColor="#C2643A" stopOpacity={0.35} /><stop offset="100%" stopColor="#C2643A" stopOpacity={0} /></linearGradient></defs>
                <CartesianGrid strokeDasharray="3 3" stroke="#E3E7ED" vertical={false} />
                <XAxis dataKey="day" tick={{ fontSize: 11, fill: "#5B6B82" }} interval={4} />
                <YAxis tick={{ fontSize: 11, fill: "#5B6B82" }} width={56} tickFormatter={(v: number) => `₹${v >= 1000 ? `${v / 1000}k` : v}`} />
                <Tooltip formatter={(v: number) => [inr(v.toFixed(2)), "Taxable"]} />
                <Area type="monotone" dataKey="v" stroke="#B4532A" strokeWidth={2} fill="url(#g)" />
              </AreaChart>
            </ResponsiveContainer>
          </div>
        </Card>

        <Card title="Order pipeline">
          <ul className="divide-y divide-navy-100 text-sm">
            <li className="flex items-center justify-between px-4 py-3">
              <Link to="/admin/orders" className="flex items-center gap-2 hover:underline"><ClipboardCheck className="h-4 w-4 text-navy-400" />Awaiting approval</Link>
              <span className="flex items-center gap-2 font-semibold">{d.orders.pending_approval}
                {d.orders.pending_with_shortage > 0 && <Badge tone="amber"><AlertTriangle className="h-3 w-3" />{d.orders.pending_with_shortage} short</Badge>}</span>
            </li>
            <li className="flex justify-between px-4 py-3"><span>Approved, to invoice</span><b>{d.orders.awaiting_invoice}</b></li>
            <li className="flex justify-between px-4 py-3"><span>Invoiced, to dispatch</span><b>{d.orders.awaiting_dispatch}</b></li>
          </ul>
        </Card>
      </div>

      <div className="mt-4 grid gap-4 xl:grid-cols-3">
        <Card title={<span className="flex items-center gap-2"><Factory className="h-4 w-4 text-navy-400" />Production efficiency (30 days)</span>}>
          {!p.runs ? <EmptyState title="No posted runs in the last 30 days" /> : (
            <div className="space-y-3 p-4 text-sm">
              <div className="flex justify-between"><span className="text-navy-400">Runs posted</span><b>{p.runs}</b></div>
              <div className="flex justify-between"><span className="text-navy-400">Good / expected</span><b>{qty(p.good)} / {qty(p.expected)}</b></div>
              <div className="flex justify-between"><span className="text-navy-400">Yield</span><b>{pct(p.yield_pct)}</b></div>
              <div className="flex justify-between"><span className="text-navy-400">Runs with variance alerts</span>
                {p.alerts ? <Badge tone="amber">{p.alerts}</Badge> : <Badge tone="green">0</Badge>}</div>
              {p.latest && (
                <Link to={`/production/${p.latest.run_id}`} className="block rounded-lg bg-navy-50 p-3 hover:bg-navy-100">
                  <div className="text-xs text-navy-400">Latest: {p.latest.run_no} · {p.latest.product}</div>
                  <div className="mt-1 flex justify-between"><span>Cost / packet</span><b>₹{roundStr(p.latest.cost_per_unit, 2)}</b></div>
                  <div className="flex justify-between"><span>Gross margin</span><b>{pct(p.latest.margin_pct)}</b></div>
                  <div className="flex justify-between"><span>Yield variance</span><b>{pct(p.latest.yield_variance_pct, true)}</b></div>
                </Link>
              )}
            </div>
          )}
        </Card>

        <Card title="Inventory">
          <ul className="divide-y divide-navy-100 text-sm">
            {Object.entries(d.stock.value_by_type).map(([t, v]) => (
              <li key={t} className="flex justify-between px-4 py-2.5"><span>{TYPE_LABEL[t] ?? t}</span><span className="num">{inr(v)}</span></li>
            ))}
          </ul>
          {d.stock.low_stock.length > 0 && (
            <div className="border-t border-navy-100 p-4">
              <div className="label">Low stock</div>
              {d.stock.low_stock.map((l) => (
                <div key={l.item_id} className="flex justify-between text-sm"><span>{l.name}</span>
                  <span className="text-amber-700">{qty(l.quantity)} / {qty(l.reorder_level)} {l.unit}</span></div>
              ))}
            </div>
          )}
        </Card>

        <Card title="Outstanding dues">
          {!d.receivables.customers.length ? <EmptyState title="Nothing outstanding" /> : (
            <Table>
              <thead><tr><Th>Customer</Th><Th right>Due</Th></tr></thead>
              <tbody className="divide-y divide-navy-100">
                {d.receivables.customers.map((c) => <tr key={c.customer_id}><Td>{c.name}</Td><Td right className="font-medium">{inr(c.outstanding)}</Td></tr>)}
              </tbody>
            </Table>
          )}
          {d.top_customers.length > 0 && (
            <div className="border-t border-navy-100 p-4">
              <div className="label">Top customers this month</div>
              {d.top_customers.map((c) => <div key={c.customer_id} className="flex justify-between text-sm"><span>{c.name}</span><span className="num">{inr(c.total)}</span></div>)}
            </div>
          )}
        </Card>
      </div>
    </>
  );
}
