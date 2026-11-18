/** Audit trail: who changed what, with before/after values. Read-only. */
import { useQuery } from "@tanstack/react-query";
import { ChevronDown, ChevronRight, ScrollText } from "lucide-react";
import { Fragment, useState } from "react";
import { Badge, Card, EmptyState, ErrorBanner, PageHeader, Spinner, Table, Td, Th } from "@/components/ui";
import { api } from "@/lib/api";
import { dateTime } from "@/lib/format";
import type { Page } from "@/lib/types";

interface Log {
  id: number; occurred_at: string; user_id: number | null; action: string; entity_type: string; entity_id: string;
  summary: string | null; before_data: Record<string, unknown> | null; after_data: Record<string, unknown> | null;
  reason: string | null; ip_address: string | null;
}
const ENTITIES = ["", "sales_order", "invoice", "dispatch", "payment", "purchase", "production_run", "stock_movement", "bom",
  "customer", "product", "raw_material", "packaging_material", "supplier", "user", "app_setting"];
const ACTION_TONE: Record<string, "green" | "amber" | "red" | "blue" | "gray" | "terracotta"> = {
  CREATE: "blue", UPDATE: "amber", APPROVE: "green", REJECT: "red", CANCEL: "red", POST: "green", DISPATCH: "terracotta",
  CREDIT: "red", RECEIPT: "green", LOGIN: "gray", SUBMIT: "blue",
};

function Diff({ before, after }: { before: Log["before_data"]; after: Log["after_data"] }) {
  const keys = Array.from(new Set([...Object.keys(before ?? {}), ...Object.keys(after ?? {})]));
  if (!keys.length) return <p className="text-xs text-navy-400">No field data recorded.</p>;
  return (
    <table className="text-xs">
      <tbody>
        {keys.map((k) => (
          <tr key={k}>
            <td className="pr-3 font-medium text-navy-600">{k}</td>
            {before && <td className="pr-3 text-red-700 line-through">{JSON.stringify(before[k] ?? null)}</td>}
            <td className="text-emerald-700">{JSON.stringify(after?.[k] ?? null)}</td>
          </tr>
        ))}
      </tbody>
    </table>
  );
}

export default function AuditLog() {
  const [entity, setEntity] = useState("");
  const [open, setOpen] = useState<number | null>(null);
  const logs = useQuery({ queryKey: ["audit", entity], queryFn: () => api<Page<Log>>("/audit-logs", { params: { entity_type: entity, limit: 200 } }) });
  return (
    <>
      <PageHeader title="Audit trail" subtitle="Every create, approval, posting, cancellation and login, with before/after values" />
      <div className="mb-4 max-w-xs">
        <span className="label">Record type</span>
        <select className="input" value={entity} onChange={(e) => setEntity(e.target.value)}>
          {ENTITIES.map((e) => <option key={e} value={e}>{e ? e.replace(/_/g, " ") : "All"}</option>)}
        </select>
      </div>
      <ErrorBanner error={logs.error} />
      <Card>
        {logs.isLoading ? <Spinner /> : !logs.data?.items.length ? <EmptyState icon={<ScrollText className="h-5 w-5" />} title="No audit entries" /> : (
          <Table>
            <thead><tr><Th /><Th>When</Th><Th>Action</Th><Th>Record</Th><Th>Summary</Th><Th>User</Th></tr></thead>
            <tbody className="divide-y divide-navy-100">
              {logs.data.items.map((l) => (
                <Fragment key={l.id}>
                  <tr className="cursor-pointer hover:bg-navy-50/50" onClick={() => setOpen(open === l.id ? null : l.id)}>
                    <Td>{open === l.id ? <ChevronDown className="h-4 w-4" /> : <ChevronRight className="h-4 w-4 text-navy-400" />}</Td>
                    <Td className="text-navy-400">{dateTime(l.occurred_at)}</Td>
                    <Td><Badge tone={ACTION_TONE[l.action] ?? "gray"}>{l.action}</Badge></Td>
                    <Td>{l.entity_type.replace(/_/g, " ")} #{l.entity_id}</Td>
                    <Td wrap className="max-w-md">{l.summary}{l.reason && <div className="text-xs text-navy-400">Reason: {l.reason}</div>}</Td>
                    <Td className="text-navy-400">{l.user_id ?? "system"}</Td>
                  </tr>
                  {open === l.id && (
                    <tr className="bg-navy-50/50"><Td colSpan={6} wrap><Diff before={l.before_data} after={l.after_data} /></Td></tr>
                  )}
                </Fragment>
              ))}
            </tbody>
          </Table>
        )}
      </Card>
    </>
  );
}
