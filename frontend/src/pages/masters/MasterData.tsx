/**
 * Master data: customers, suppliers, products, raw materials, packaging, users, company and settings.
 *
 * One config-driven screen per record type. The server owns every rule (GSTIN check digit vs state,
 * unique codes, base unit locked once stock moves, owner-only owner accounts...): the form just
 * collects input, sends only the fields that changed, and shows the server's field errors.
 */
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import {
  Boxes, Building2, Package, Pencil, Plus, Search, Settings2, ShoppingBasket, Store, Truck, Users, type LucideIcon,
} from "lucide-react";
import { useEffect, useMemo, useState, type FormEvent, type ReactNode } from "react";
import { NavLink, Navigate, useParams } from "react-router-dom";
import {
  Badge, Button, Card, EmptyState, ErrorBanner, Field, Modal, PageHeader, Spinner, Table, Td, Th, cx, useToast,
} from "@/components/ui";
import { api } from "@/lib/api";
import { useAuth } from "@/lib/auth";
import { dateTime, inr, label, qty, roundStr } from "@/lib/format";
import type { Page, Role } from "@/lib/types";

// ---- reference data used by forms -------------------------------------------------------
interface State { code: string; name: string }
interface Unit { code: string; name: string; dimension: "MASS" | "VOLUME" | "COUNT" }
interface Salesman { id: number; full_name: string; username: string }
interface Lookups { states: State[]; units: Unit[]; salesmen: Salesman[]; role: Role }

type Row = Record<string, unknown> & { id: number; is_active: boolean };
type Option = { value: string; label: string };

interface FieldSpec {
  key: string;
  label: string;
  type?: "text" | "textarea" | "int" | "decimal" | "select" | "checkbox" | "password";
  required?: boolean;
  createOnly?: boolean; // e.g. codes and usernames never change
  editOnly?: boolean; // e.g. the Active switch
  options?: (l: Lookups) => Option[];
  hint?: string;
  placeholder?: string;
  initial?: string | boolean;
  wide?: boolean;
}
interface Column { label: string; right?: boolean; render: (r: Row, l: Lookups) => ReactNode }
interface MasterDef {
  key: string;
  title: string;
  singular: string;
  subtitle: string;
  endpoint: string;
  icon: LucideIcon;
  readers: Role[];
  writers: Role[];
  needsSalesmen?: boolean;
  /** Extra per-row rule mirrored from the server (UX only; the API enforces it). */
  canEditRow?: (r: Row, role: Role) => boolean;
  columns: Column[];
  fields: FieldSpec[];
}

const s = (v: unknown) => (v === null || v === undefined ? "" : String(v));
const stateName = (l: Lookups, code: unknown) => l.states.find((x) => x.code === code)?.name ?? s(code);
const stateOptions = (l: Lookups): Option[] => l.states.map((x) => ({ value: x.code, label: `${x.code} · ${x.name}` }));
const enumOptions = (...values: string[]): (() => Option[]) => () => values.map((v) => ({ value: v, label: label(v) }));
const unitOptions = (dims: Unit["dimension"][]) => (l: Lookups): Option[] =>
  l.units.filter((u) => dims.includes(u.dimension)).map((u) => ({ value: u.code, label: `${u.code} · ${u.name}` }));
const active = (r: Row) => (r.is_active ? null : <Badge>Inactive</Badge>);
const codeName = (r: Row) => (
  <div><div className="font-medium">{s(r.name)} {active(r)}</div><div className="text-xs text-navy-400">{s(r.code)}</div></div>
);

const ACTIVE_FIELD: FieldSpec = { key: "is_active", label: "Active", type: "checkbox", editOnly: true,
  hint: "Inactive records stay in history but can't be used on new documents." };
const GSTIN_HINT = "15 characters. The first two digits must match the state; the check digit is verified.";
const ITEM_COMMON: FieldSpec[] = [
  { key: "code", label: "Code", required: true, createOnly: true, placeholder: "RM-SUGAR" },
  { key: "name", label: "Name", required: true },
  { key: "standard_cost", label: "Standard cost (₹ per base unit)", type: "decimal", hint: "Used to value opening stock; actual cost is the weighted average." },
  { key: "reorder_level", label: "Reorder level", type: "decimal", initial: "0" },
];

const MASTERS: MasterDef[] = [
  {
    key: "customers", title: "Customers", singular: "customer", endpoint: "/customers", icon: Store,
    subtitle: "Retailers and distributors. The state decides CGST+SGST or IGST on invoices.",
    readers: ["ADMIN", "OWNER", "AUDITOR"], writers: ["ADMIN"], needsSalesmen: true,
    columns: [
      { label: "Customer", render: codeName },
      { label: "Type", render: (r) => label(s(r.customer_type)) },
      { label: "State", render: (r, l) => stateName(l, r.state_code) },
      { label: "GSTIN", render: (r) => s(r.gstin) || <span className="text-navy-400">Unregistered</span> },
      { label: "Salesman", render: (r, l) => l.salesmen.find((x) => x.id === r.assigned_salesman_id)?.full_name ?? "—" },
      { label: "Credit", right: true, render: (r) => `${inr(s(r.credit_limit))} · ${s(r.credit_days)} d` },
    ],
    fields: [
      { key: "code", label: "Code", required: true, createOnly: true, placeholder: "RET-C" },
      { key: "name", label: "Name", required: true },
      { key: "customer_type", label: "Type", type: "select", required: true, initial: "RETAILER", options: enumOptions("RETAILER", "DISTRIBUTOR", "OTHER") },
      { key: "state_code", label: "State", type: "select", required: true, initial: "33", options: stateOptions },
      { key: "gstin", label: "GSTIN", hint: GSTIN_HINT, placeholder: "Leave empty if unregistered" },
      { key: "assigned_salesman_id", label: "Salesman", type: "select", options: (l) => l.salesmen.map((x) => ({ value: String(x.id), label: x.full_name })), hint: "Only this salesman sees the customer and can take orders for it." },
      { key: "address", label: "Address", type: "textarea", required: true, wide: true },
      { key: "city", label: "City" },
      { key: "pincode", label: "PIN code", placeholder: "641001" },
      { key: "phone", label: "Phone" },
      { key: "email", label: "Email" },
      { key: "credit_limit", label: "Credit limit (₹)", type: "decimal", initial: "0" },
      { key: "credit_days", label: "Credit days", type: "int", initial: "30" },
      ACTIVE_FIELD,
    ],
  },
  {
    key: "suppliers", title: "Suppliers", singular: "supplier", endpoint: "/suppliers", icon: Truck,
    subtitle: "Vendors of raw materials and packaging.",
    readers: ["ADMIN", "PRODUCTION", "OWNER", "AUDITOR"], writers: ["ADMIN"],
    columns: [
      { label: "Supplier", render: codeName },
      { label: "State", render: (r, l) => stateName(l, r.state_code) },
      { label: "GSTIN", render: (r) => s(r.gstin) || "—" },
      { label: "Phone", render: (r) => s(r.phone) || "—" },
    ],
    fields: [
      { key: "code", label: "Code", required: true, createOnly: true, placeholder: "SUP-SPICE" },
      { key: "name", label: "Name", required: true },
      { key: "state_code", label: "State", type: "select", required: true, initial: "33", options: stateOptions },
      { key: "gstin", label: "GSTIN", hint: GSTIN_HINT },
      { key: "address", label: "Address", type: "textarea", wide: true },
      { key: "phone", label: "Phone" },
      { key: "email", label: "Email" },
      ACTIVE_FIELD,
    ],
  },
  {
    key: "products", title: "Products", singular: "product", endpoint: "/products", icon: ShoppingBasket,
    subtitle: "Finished goods and their price list. Prices are fixed on orders when they are created.",
    readers: ["ADMIN", "PRODUCTION", "OWNER", "AUDITOR"], writers: ["ADMIN"],
    columns: [
      { label: "Product", render: codeName },
      { label: "Unit", render: (r) => s(r.base_unit_code) },
      { label: "HSN", render: (r) => s(r.hsn_code) },
      { label: "GST", right: true, render: (r) => `${roundStr(s(r.gst_rate), 2)} %` },
      { label: "Price", right: true, render: (r) => inr(s(r.selling_price)) },
      { label: "Reorder at", right: true, render: (r) => qty(s(r.reorder_level)) },
    ],
    fields: [
      ...ITEM_COMMON.slice(0, 2),
      { key: "base_unit_code", label: "Base unit", type: "select", required: true, initial: "PKT", options: unitOptions(["COUNT"]), hint: "Locked once the product has stock movements." },
      { key: "hsn_code", label: "HSN code", required: true, placeholder: "21069099" },
      { key: "gst_rate", label: "GST rate (%)", type: "decimal", required: true, initial: "5" },
      { key: "selling_price", label: "Selling price (₹, before GST)", type: "decimal", required: true },
      { key: "net_weight_g", label: "Net weight (g)", type: "decimal" },
      ...ITEM_COMMON.slice(2),
      ACTIVE_FIELD,
    ],
  },
  {
    key: "raw-materials", title: "Raw materials", singular: "raw material", endpoint: "/raw-materials", icon: Boxes,
    subtitle: "Ingredients used by bills of materials.",
    readers: ["ADMIN", "PRODUCTION", "OWNER", "AUDITOR"], writers: ["ADMIN", "PRODUCTION"],
    columns: [
      { label: "Material", render: codeName },
      { label: "Category", render: (r) => s(r.category) || "—" },
      { label: "Unit", render: (r) => s(r.base_unit_code) },
      { label: "Std cost", right: true, render: (r) => (r.standard_cost ? `₹${roundStr(s(r.standard_cost), 2)}` : "—") },
      { label: "Reorder at", right: true, render: (r) => qty(s(r.reorder_level)) },
    ],
    fields: [
      ...ITEM_COMMON.slice(0, 2),
      { key: "base_unit_code", label: "Base unit", type: "select", required: true, initial: "KG", options: unitOptions(["MASS", "VOLUME", "COUNT"]), hint: "Locked once the material has stock movements." },
      { key: "category", label: "Category", placeholder: "Flour, Oil, Spices…" },
      { key: "shelf_life_days", label: "Shelf life (days)", type: "int" },
      ...ITEM_COMMON.slice(2),
      ACTIVE_FIELD,
    ],
  },
  {
    key: "packaging", title: "Packaging", singular: "packaging material", endpoint: "/packaging-materials", icon: Package,
    subtitle: "Pouches, cartons and labels. Count units only; cartons round down to whole units in production.",
    readers: ["ADMIN", "PRODUCTION", "OWNER", "AUDITOR"], writers: ["ADMIN", "PRODUCTION"],
    columns: [
      { label: "Material", render: codeName },
      { label: "Kind", render: (r) => label(s(r.packaging_kind)) },
      { label: "Unit", render: (r) => s(r.base_unit_code) },
      { label: "Std cost", right: true, render: (r) => (r.standard_cost ? `₹${roundStr(s(r.standard_cost), 2)}` : "—") },
      { label: "Reorder at", right: true, render: (r) => qty(s(r.reorder_level)) },
    ],
    fields: [
      ...ITEM_COMMON.slice(0, 2),
      { key: "packaging_kind", label: "Kind", type: "select", required: true, initial: "POUCH", options: enumOptions("POUCH", "CARTON", "LABEL", "OTHER") },
      { key: "base_unit_code", label: "Base unit", type: "select", required: true, initial: "PCS", options: unitOptions(["COUNT"]) },
      { key: "specification", label: "Specification", placeholder: "200 g, 3-layer laminate", wide: true },
      ...ITEM_COMMON.slice(2),
      ACTIVE_FIELD,
    ],
  },
  {
    key: "users", title: "Users", singular: "user", endpoint: "/users", icon: Users,
    subtitle: "Sign-in accounts and roles. Only an owner can create or change owner accounts.",
    readers: ["ADMIN", "OWNER"], writers: ["ADMIN", "OWNER"],
    canEditRow: (r, role) => r.role !== "OWNER" || role === "OWNER",
    columns: [
      { label: "User", render: (r) => <div><div className="font-medium">{s(r.full_name)} {active(r)}</div><div className="text-xs text-navy-400">{s(r.username)}</div></div> },
      { label: "Role", render: (r) => <Badge tone="blue">{label(s(r.role))}</Badge> },
      { label: "Email", render: (r) => s(r.email) || "—" },
      { label: "Last sign-in", render: (r) => (r.last_login_at ? dateTime(s(r.last_login_at)) : "Never") },
    ],
    fields: [
      { key: "username", label: "Username", required: true, createOnly: true, hint: "Lower-case letters, digits, dot and underscore." },
      { key: "full_name", label: "Full name", required: true },
      { key: "role", label: "Role", type: "select", required: true, initial: "SALESMAN",
        options: (l) => (["SALESMAN", "ADMIN", "PRODUCTION", "AUDITOR", ...(l.role === "OWNER" ? ["OWNER"] : [])] as string[])
          .map((v) => ({ value: v, label: v === "AUDITOR" ? "Accountant / Auditor" : label(v) })) },
      { key: "email", label: "Email" },
      { key: "phone", label: "Phone" },
      { key: "password", label: "Password", type: "password", required: true, createOnly: true, hint: "At least 8 characters." },
      { key: "password", label: "Reset password", type: "password", editOnly: true, hint: "Leave empty to keep the current password." },
      ACTIVE_FIELD,
    ],
  },
];

// ---- tabs ----------------------------------------------------------------------------------
const SETTINGS_TAB = { key: "company", title: "Company & settings", icon: Building2,
  readers: ["ADMIN", "PRODUCTION", "OWNER", "AUDITOR"] as Role[] };

export function visibleMasterTabs(role: Role) {
  return [...MASTERS, SETTINGS_TAB].filter((t) => t.readers.includes(role));
}

export default function MasterData() {
  const { user } = useAuth();
  const { tab } = useParams();
  const role = user!.role;
  const tabs = visibleMasterTabs(role);
  if (!tabs.length) return <Navigate to="/" replace />;
  if (!tab || !tabs.some((t) => t.key === tab)) return <Navigate to={`/masters/${tabs[0].key}`} replace />;
  const def = MASTERS.find((m) => m.key === tab);

  return (
    <>
      <PageHeader title="Master data" subtitle="Changes are validated by the server and recorded in the audit trail" />
      <nav className="-mx-1 mb-4 flex gap-1 overflow-x-auto pb-1" aria-label="Master data sections">
        {tabs.map((t) => (
          <NavLink key={t.key} to={`/masters/${t.key}`}
            className={({ isActive }) => cx("flex flex-none items-center gap-1.5 rounded-lg px-3 py-1.5 text-sm",
              isActive ? "bg-navy-800 text-white" : "text-navy-600 hover:bg-navy-50")}>
            <t.icon className="h-4 w-4" />{t.title}
          </NavLink>
        ))}
      </nav>
      {def ? <MasterList key={def.key} def={def} role={role} /> : <CompanyAndSettings role={role} />}
    </>
  );
}

// ---- list + form for one record type -----------------------------------------------------
function useLookups(role: Role, needsSalesmen: boolean): Lookups {
  const states = useQuery({ queryKey: ["states"], queryFn: () => api<State[]>("/states"), staleTime: Infinity });
  const units = useQuery({ queryKey: ["units"], queryFn: () => api<Unit[]>("/units"), staleTime: Infinity });
  const salesmen = useQuery({ queryKey: ["salesmen"], queryFn: () => api<Salesman[]>("/users/salesmen"), enabled: needsSalesmen });
  return { states: states.data ?? [], units: units.data ?? [], salesmen: salesmen.data ?? [], role };
}

function MasterList({ def, role }: { def: MasterDef; role: Role }) {
  const [q, setQ] = useState("");
  const [search, setSearch] = useState("");
  const [showInactive, setShowInactive] = useState(false);
  const [editing, setEditing] = useState<Row | "new" | null>(null);
  const lookups = useLookups(role, !!def.needsSalesmen);
  const canWrite = def.writers.includes(role);

  useEffect(() => {
    const t = setTimeout(() => setSearch(q.trim()), 250);
    return () => clearTimeout(t);
  }, [q]);

  const list = useQuery({
    queryKey: ["masters", def.key, search, showInactive],
    queryFn: () => api<Page<Row>>(def.endpoint, { params: { q: search, active: showInactive ? undefined : true, limit: 200 } }),
  });
  const Icon = def.icon;

  return (
    <Card
      title={<span className="flex items-center gap-2"><Icon className="h-4 w-4 text-navy-400" />{def.title}</span>}
      actions={canWrite && <Button icon={<Plus className="h-4 w-4" />} onClick={() => setEditing("new")}>New {def.singular}</Button>}>
      <div className="flex flex-wrap items-center gap-3 border-b border-navy-100 px-4 py-3">
        <p className="w-full text-xs text-navy-400 sm:w-auto sm:flex-1">{def.subtitle}</p>
        <label className="relative">
          <Search className="pointer-events-none absolute left-2.5 top-2.5 h-4 w-4 text-navy-400" />
          <input className="input w-56 pl-8" placeholder="Search code or name" value={q} onChange={(e) => setQ(e.target.value)} aria-label={`Search ${def.title}`} />
        </label>
        <label className="flex items-center gap-2 text-sm text-navy-600">
          <input type="checkbox" checked={showInactive} onChange={(e) => setShowInactive(e.target.checked)} />Show inactive
        </label>
      </div>
      <ErrorBanner error={list.error} className="m-4" />
      {list.isLoading ? <Spinner /> : !list.data?.items.length ? (
        <EmptyState title={search ? "Nothing matches your search" : `No ${def.title.toLowerCase()} yet`} />
      ) : (
        <>
          <Table>
            <thead><tr>{def.columns.map((c) => <Th key={c.label} right={c.right}>{c.label}</Th>)}{canWrite && <Th />}</tr></thead>
            <tbody className="divide-y divide-navy-100">
              {list.data.items.map((r) => (
                <tr key={r.id} className={cx("hover:bg-navy-50/40", !r.is_active && "opacity-60")}>
                  {def.columns.map((c) => <Td key={c.label} right={c.right}>{c.render(r, lookups)}</Td>)}
                  {canWrite && (
                    <Td right>
                      {(def.canEditRow?.(r, role) ?? true) && <Button variant="ghost" icon={<Pencil className="h-4 w-4" />} onClick={() => setEditing(r)}
                        aria-label={`Edit ${s(r.name ?? r.full_name)}`}>Edit</Button>}
                    </Td>
                  )}
                </tr>
              ))}
            </tbody>
          </Table>
          {list.data.total > list.data.items.length && (
            <p className="px-4 py-2 text-xs text-navy-400">Showing {list.data.items.length} of {list.data.total}. Search to narrow down.</p>
          )}
        </>
      )}
      {editing && <RecordForm def={def} row={editing === "new" ? null : editing} lookups={lookups} onClose={() => setEditing(null)} />}
    </Card>
  );
}

function initialValues(def: MasterDef, row: Row | null): Record<string, string | boolean> {
  const v: Record<string, string | boolean> = {};
  for (const f of def.fields) {
    if (row ? f.createOnly : f.editOnly) continue;
    if (f.type === "password") v[f.key] = "";
    else if (f.type === "checkbox") v[f.key] = row ? Boolean(row[f.key]) : (f.initial as boolean) ?? true;
    else v[f.key] = row ? s(row[f.key]) : s(f.initial);
  }
  return v;
}

/** Build the request body. Create: every filled field. Edit: only fields that changed;
 *  an emptied optional field is sent as null (cleared). The server validates everything. */
function payload(def: MasterDef, values: Record<string, string | boolean>, initial: Record<string, string | boolean>, isEdit: boolean) {
  const body: Record<string, unknown> = {};
  for (const f of def.fields) {
    if (!(f.key in values) || (isEdit ? f.createOnly : f.editOnly)) continue;
    const v = values[f.key];
    if (f.type === "password") {
      if (v) body[f.key] = v;
      continue;
    }
    if (isEdit && v === initial[f.key]) continue;
    if (typeof v === "boolean") body[f.key] = v;
    else if (v.trim() === "") { if (isEdit) body[f.key] = null; }
    else if (f.type === "int" || (f.type === "select" && f.key.endsWith("_id"))) body[f.key] = Number(v);
    else body[f.key] = v.trim();
  }
  return body;
}

function RecordForm({ def, row, lookups, onClose }: { def: MasterDef; row: Row | null; lookups: Lookups; onClose: () => void }) {
  const isEdit = row !== null;
  const initial = useMemo(() => initialValues(def, row), [def, row]);
  const [values, setValues] = useState(initial);
  const toast = useToast();
  const qc = useQueryClient();
  const fields = def.fields.filter((f) => !(isEdit ? f.createOnly : f.editOnly));
  const body = payload(def, values, initial, isEdit);
  const unchanged = isEdit && Object.keys(body).length === 0;

  const save = useMutation({
    mutationFn: () => api<Row>(isEdit ? `${def.endpoint}/${row!.id}` : def.endpoint, { method: isEdit ? "PATCH" : "POST", body }),
    onSuccess: (saved) => {
      qc.invalidateQueries({ queryKey: ["masters", def.key] });
      qc.invalidateQueries({ queryKey: ["catalog"] });
      qc.invalidateQueries({ queryKey: ["balances"] });
      qc.invalidateQueries({ queryKey: ["salesmen"] });
      toast(`${def.singular[0].toUpperCase()}${def.singular.slice(1)} ${s(saved.code ?? saved.username)} ${isEdit ? "updated" : "created"}`);
      onClose();
    },
  });

  function submit(e: FormEvent) {
    e.preventDefault();
    if (!unchanged) save.mutate();
  }
  const set = (k: string, v: string | boolean) => setValues((old) => ({ ...old, [k]: v }));
  const title = isEdit ? `Edit ${def.singular} ${s(row!.code ?? row!.username)}` : `New ${def.singular}`;

  return (
    <Modal open onClose={onClose} title={title} wide
      footer={<>
        <Button variant="secondary" onClick={onClose}>Cancel</Button>
        <Button type="submit" form="master-form" loading={save.isPending} disabled={unchanged}>{isEdit ? "Save changes" : "Create"}</Button>
      </>}>
      <form id="master-form" onSubmit={submit} className="grid gap-3 sm:grid-cols-2">
        <ErrorBanner error={save.error} className="sm:col-span-2" />
        {fields.map((f) => (
          f.type === "checkbox" ? (
            <label key={f.key + "cb"} className="flex items-start gap-2 text-sm sm:col-span-2">
              <input type="checkbox" className="mt-1" checked={values[f.key] as boolean} onChange={(e) => set(f.key, e.target.checked)} />
              <span><span className="font-medium">{f.label}</span>{f.hint && <span className="block text-xs text-navy-400">{f.hint}</span>}</span>
            </label>
          ) : (
            <Field key={f.key + (f.editOnly ? "e" : "")} label={f.label + (f.required && !isEdit ? " *" : "")} hint={f.hint} className={cx(f.wide && "sm:col-span-2")}>
              <Input f={f} value={values[f.key] as string} lookups={lookups} isEdit={isEdit} onChange={(v) => set(f.key, v)} />
            </Field>
          )
        ))}
      </form>
    </Modal>
  );
}

function Input({ f, value, lookups, isEdit, onChange }: { f: FieldSpec; value: string; lookups: Lookups; isEdit: boolean; onChange: (v: string) => void }) {
  const required = f.required && !(isEdit && f.type === "password");
  if (f.type === "select") {
    const opts = f.options?.(lookups) ?? [];
    return (
      <select className="input" value={value} required={required} onChange={(e) => onChange(e.target.value)}>
        {!f.required && <option value="">—</option>}
        {f.required && !value && <option value="" disabled>Choose…</option>}
        {opts.map((o) => <option key={o.value} value={o.value}>{o.label}</option>)}
      </select>
    );
  }
  if (f.type === "textarea") {
    return <textarea className="input min-h-[4.5rem]" value={value} required={required} onChange={(e) => onChange(e.target.value)} />;
  }
  const numeric = f.type === "int" || f.type === "decimal";
  return (
    <input className={cx("input", numeric && "num")} value={value} required={required} placeholder={f.placeholder}
      type={f.type === "password" ? "password" : "text"} autoComplete={f.type === "password" ? "new-password" : "off"}
      inputMode={f.type === "int" ? "numeric" : f.type === "decimal" ? "decimal" : undefined}
      pattern={f.type === "int" ? "[0-9]*" : f.type === "decimal" ? "[0-9]*\\.?[0-9]*" : undefined}
      onChange={(e) => onChange(e.target.value)} />
  );
}

// ---- company profile + settings --------------------------------------------------------------
interface Company { legal_name: string; trade_name: string | null; gstin: string; state_code: string; address: string; phone: string | null; email: string | null; fy_start_month: number }
interface Setting { key: string; value: string; description: string | null; updated_at: string }

function CompanyAndSettings({ role }: { role: Role }) {
  const canWrite = role === "ADMIN" || role === "OWNER";
  const company = useQuery({ queryKey: ["company"], queryFn: () => api<Company>("/company") });
  const settings = useQuery({ queryKey: ["settings"], queryFn: () => api<Setting[]>("/settings") });
  const lookups = useLookups(role, false);
  const [editCompany, setEditCompany] = useState(false);

  return (
    <div className="grid gap-4 xl:grid-cols-2">
      <Card title={<span className="flex items-center gap-2"><Building2 className="h-4 w-4 text-navy-400" />Company profile</span>}
        actions={canWrite && company.data && <Button variant="secondary" icon={<Pencil className="h-4 w-4" />} onClick={() => setEditCompany(true)}>Edit</Button>}>
        <ErrorBanner error={company.error} className="m-4" />
        {company.isLoading ? <Spinner /> : company.data && (
          <dl className="grid grid-cols-3 gap-x-3 gap-y-2 p-4 text-sm">
            {([
              ["Legal name", company.data.legal_name], ["Trade name", company.data.trade_name ?? "—"],
              ["GSTIN", company.data.gstin], ["State", stateName(lookups, company.data.state_code)],
              ["Address", company.data.address], ["Phone", company.data.phone ?? "—"], ["Email", company.data.email ?? "—"],
              ["Financial year", `Starts in month ${company.data.fy_start_month}`],
            ] as [string, string][]).map(([k, v]) => (
              <div key={k} className="contents"><dt className="text-navy-400">{k}</dt><dd className="col-span-2 whitespace-pre-line">{v}</dd></div>
            ))}
          </dl>
        )}
        <p className="border-t border-navy-100 px-4 py-2 text-xs text-navy-400">
          The company's state decides intra-state (CGST+SGST) vs inter-state (IGST) on every new invoice.
        </p>
        {editCompany && company.data && <CompanyForm company={company.data} lookups={lookups} onClose={() => setEditCompany(false)} />}
      </Card>

      <Card title={<span className="flex items-center gap-2"><Settings2 className="h-4 w-4 text-navy-400" />Settings</span>}>
        <ErrorBanner error={settings.error} className="m-4" />
        {settings.isLoading ? <Spinner /> : (
          <ul className="divide-y divide-navy-100">
            {settings.data?.map((st) => <SettingRow key={st.key} setting={st} canWrite={canWrite} />)}
          </ul>
        )}
      </Card>
    </div>
  );
}

const SETTING_LABEL: Record<string, string> = {
  variance_tolerance_pct: "Production variance tolerance (%)",
  default_gst_rate: "Default GST rate (%)",
  receivable_ageing_buckets: "Receivable ageing buckets (days)",
};
const settingLabel = (key: string) => SETTING_LABEL[key] ?? label(key.toUpperCase());

function SettingRow({ setting, canWrite }: { setting: Setting; canWrite: boolean }) {
  const [value, setValue] = useState(setting.value);
  const toast = useToast();
  const qc = useQueryClient();
  useEffect(() => setValue(setting.value), [setting.value]);
  const save = useMutation({
    mutationFn: () => api<Setting>(`/settings/${setting.key}`, { method: "PUT", body: { value: value.trim() } }),
    onSuccess: () => { qc.invalidateQueries({ queryKey: ["settings"] }); toast(`${settingLabel(setting.key)} saved`); },
  });
  const dirty = value.trim() !== setting.value;
  return (
    <li className="space-y-2 px-4 py-3">
      <div className="flex items-baseline justify-between gap-3">
        <span className="font-medium">{settingLabel(setting.key)}</span>
        <span className="text-xs text-navy-400">updated {dateTime(setting.updated_at)}</span>
      </div>
      {setting.description && <p className="text-xs text-navy-400">{setting.description}</p>}
      <form className="flex gap-2" onSubmit={(e) => { e.preventDefault(); if (dirty) save.mutate(); }}>
        <input className="input num max-w-[12rem]" value={value} disabled={!canWrite} onChange={(e) => setValue(e.target.value)} aria-label={settingLabel(setting.key)} />
        {canWrite && <Button type="submit" variant="secondary" disabled={!dirty} loading={save.isPending}>Save</Button>}
      </form>
      <ErrorBanner error={save.error} />
    </li>
  );
}

const COMPANY_DEF: MasterDef = {
  key: "company", title: "Company", singular: "company profile", endpoint: "/company", icon: Building2,
  subtitle: "", readers: [], writers: [], columns: [],
  fields: [
    { key: "legal_name", label: "Legal name", required: true },
    { key: "trade_name", label: "Trade name" },
    { key: "gstin", label: "GSTIN", required: true, hint: GSTIN_HINT },
    { key: "state_code", label: "State", type: "select", required: true, options: stateOptions },
    { key: "address", label: "Address", type: "textarea", required: true, wide: true },
    { key: "phone", label: "Phone" },
    { key: "email", label: "Email" },
  ],
};

function CompanyForm({ company, lookups, onClose }: { company: Company; lookups: Lookups; onClose: () => void }) {
  const row = { ...company, id: 1, is_active: true } as unknown as Row;
  const initial = useMemo(() => initialValues(COMPANY_DEF, row), []); // eslint-disable-line react-hooks/exhaustive-deps
  const [values, setValues] = useState(initial);
  const toast = useToast();
  const qc = useQueryClient();
  const body = payload(COMPANY_DEF, values, initial, true);
  const save = useMutation({
    mutationFn: () => api<Company>("/company", { method: "PATCH", body }),
    onSuccess: () => { qc.invalidateQueries({ queryKey: ["company"] }); toast("Company profile updated"); onClose(); },
  });
  return (
    <Modal open onClose={onClose} title="Edit company profile" wide
      footer={<>
        <Button variant="secondary" onClick={onClose}>Cancel</Button>
        <Button type="submit" form="company-form" loading={save.isPending} disabled={!Object.keys(body).length}>Save changes</Button>
      </>}>
      <form id="company-form" className="grid gap-3 sm:grid-cols-2" onSubmit={(e) => { e.preventDefault(); save.mutate(); }}>
        <ErrorBanner error={save.error} className="sm:col-span-2" />
        {COMPANY_DEF.fields.map((f) => (
          <Field key={f.key} label={f.label} hint={f.hint} className={cx(f.wide && "sm:col-span-2")}>
            <Input f={f} value={values[f.key] as string} lookups={lookups} isEdit onChange={(v) => setValues((o) => ({ ...o, [f.key]: v }))} />
          </Field>
        ))}
      </form>
    </Modal>
  );
}
