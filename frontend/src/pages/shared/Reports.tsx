/** Reports: catalogue for the caller's role, a typed table viewer, and CSV / Excel / PDF downloads. */
import { useQuery } from "@tanstack/react-query";
import { Download, FileSpreadsheet, FileText, Play } from "lucide-react";
import { useState } from "react";
import { useSearchParams } from "react-router-dom";
import { Badge, Button, Card, EmptyState, ErrorBanner, PageHeader, Spinner, Table, Td, Th, cx } from "@/components/ui";
import { api, download } from "@/lib/api";
import { date, inr, monthStart, pct, qty, roundStr, today } from "@/lib/format";
import type { ReportColumn, ReportData } from "@/lib/types";

interface Def { key: string; title: string; description: string; filters: string[] }

function cell(value: unknown, kind: ReportColumn["kind"]): string {
  if (value === null || value === undefined || value === "") return "";
  const v = String(value);
  switch (kind) {
    case "money": return inr(v, false);
    case "qty": return qty(v);
    case "rate": return roundStr(v, 4);
    case "pct": return pct(v);
    case "date": return date(v);
    case "bool": return value === true ? "Yes" : "No";
    default: return v;
  }
}
const NUMERIC = new Set(["money", "qty", "rate", "pct", "int"]);

export default function Reports() {
  const [params, setParams] = useSearchParams();
  const [from, setFrom] = useState(monthStart());
  const [to, setTo] = useState(today());
  const [run, setRun] = useState(0);
  const [dlError, setDlError] = useState<unknown>(null);
  const [busy, setBusy] = useState<string | null>(null);
  const key = params.get("key");

  const catalogue = useQuery({ queryKey: ["reports"], queryFn: () => api<Def[]>("/reports") });
  const report = useQuery({
    queryKey: ["report", key, from, to, run], enabled: !!key,
    queryFn: () => api<ReportData>(`/reports/${key}`, { params: { date_from: from, date_to: to } }),
  });
  const def = catalogue.data?.find((d) => d.key === key);

  async function exportAs(format: string) {
    setBusy(format);
    setDlError(null);
    try { await download(`/reports/${key}`, { date_from: from, date_to: to, format }); }
    catch (e) { setDlError(e); }
    finally { setBusy(null); }
  }

  return (
    <>
      <PageHeader title="Reports" subtitle="Monthly and audit reports from posted documents and the stock ledger" />
      <div className="grid gap-4 lg:grid-cols-4">
        <Card className="lg:col-span-1" title="Available to you">
          {catalogue.isLoading ? <Spinner /> : (
            <ul className="max-h-[70vh] overflow-y-auto p-2">
              {catalogue.data?.map((d) => (
                <li key={d.key}>
                  <button onClick={() => setParams({ key: d.key })}
                    className={cx("w-full rounded-lg px-3 py-2 text-left text-sm", key === d.key ? "bg-navy-800 text-white" : "hover:bg-navy-50")}>
                    <div className="font-medium">{d.title}</div>
                    <div className={cx("text-xs", key === d.key ? "text-navy-200" : "text-navy-400")}>{d.description}</div>
                  </button>
                </li>
              ))}
            </ul>
          )}
        </Card>

        <div className="min-w-0 space-y-4 lg:col-span-3">
          <Card className="p-4">
            <div className="flex flex-wrap items-end gap-3">
              <label><span className="label">From</span><input type="date" className="input" value={from} max={to} onChange={(e) => setFrom(e.target.value)} /></label>
              <label><span className="label">To</span><input type="date" className="input" value={to} min={from} max={today()} onChange={(e) => setTo(e.target.value)} /></label>
              <Button icon={<Play className="h-4 w-4" />} disabled={!key} onClick={() => setRun((n) => n + 1)}>Refresh</Button>
              <div className="ml-auto flex flex-wrap gap-2">
                <Button variant="secondary" disabled={!key} loading={busy === "csv"} icon={<Download className="h-4 w-4" />} onClick={() => exportAs("csv")}>CSV</Button>
                <Button variant="secondary" disabled={!key} loading={busy === "xlsx"} icon={<FileSpreadsheet className="h-4 w-4" />} onClick={() => exportAs("xlsx")}>Excel</Button>
                <Button variant="secondary" disabled={!key} loading={busy === "pdf"} icon={<FileText className="h-4 w-4" />} onClick={() => exportAs("pdf")}>PDF</Button>
              </div>
            </div>
            <ErrorBanner error={dlError} className="mt-3" />
          </Card>

          <Card title={def?.title ?? "Choose a report"} actions={report.data && <Badge>{report.data.row_count} rows</Badge>}>
            {!key ? <EmptyState title="Pick a report on the left" hint="All reports accept a date range and export to CSV, Excel and PDF." /> :
              report.isLoading ? <Spinner /> : report.error ? <ErrorBanner error={report.error} className="m-4" /> :
              !report.data?.rows.length ? <EmptyState title="No records in this period" /> : (
                <>
                  <Table>
                    <thead><tr>{report.data.columns.map((c) => <Th key={c.key} right={NUMERIC.has(c.kind)}>{c.label}</Th>)}</tr></thead>
                    <tbody className="divide-y divide-navy-100">
                      {report.data.rows.map((r, i) => (
                        <tr key={i} className="hover:bg-navy-50/40">
                          {report.data!.columns.map((c) => (
                            <Td key={c.key} right={NUMERIC.has(c.kind)} className={cx(c.kind === "bool" && r[c.key] === true && "font-medium text-terracotta-700")}>
                              {cell(r[c.key], c.kind)}
                            </Td>
                          ))}
                        </tr>
                      ))}
                      {report.data.totals && (
                        <tr className="bg-navy-50 font-semibold">
                          {report.data.columns.map((c, idx) => (
                            <Td key={c.key} right={NUMERIC.has(c.kind)}>{idx === 0 ? "Total" : report.data!.totals![c.key] !== undefined ? cell(report.data!.totals![c.key], c.kind) : ""}</Td>
                          ))}
                        </tr>
                      )}
                    </tbody>
                  </Table>
                  {report.data.notes.length > 0 && (
                    <ul className="space-y-1 border-t border-navy-100 px-4 py-3 text-xs text-navy-400">{report.data.notes.map((n) => <li key={n}>{n}</li>)}</ul>
                  )}
                </>
              )}
          </Card>
        </div>
      </div>
    </>
  );
}
