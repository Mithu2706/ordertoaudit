import { Badge } from "@/components/ui";
import { inr } from "@/lib/format";
import type { Dec } from "@/lib/types";

/** GST breakdown exactly as computed by the server (no client-side tax maths). */
export function OrderTotals({ supply, taxable, cgst, sgst, igst, total, totalLabel = "Total" }: {
  supply: "INTRA_STATE" | "INTER_STATE"; taxable: Dec; cgst: Dec; sgst: Dec; igst: Dec; total: Dec; totalLabel?: string;
}) {
  const intra = supply === "INTRA_STATE";
  return (
    <dl className="space-y-1.5 text-sm">
      <div className="flex justify-between"><dt className="text-navy-400">Taxable value</dt><dd className="num">{inr(taxable)}</dd></div>
      {intra ? (
        <>
          <div className="flex justify-between"><dt className="text-navy-400">CGST</dt><dd className="num">{inr(cgst)}</dd></div>
          <div className="flex justify-between"><dt className="text-navy-400">SGST</dt><dd className="num">{inr(sgst)}</dd></div>
        </>
      ) : (
        <div className="flex justify-between"><dt className="text-navy-400">IGST</dt><dd className="num">{inr(igst)}</dd></div>
      )}
      <div className="flex items-center justify-between border-t border-navy-100 pt-2 text-base font-semibold">
        <dt className="flex items-center gap-2">{totalLabel}<Badge tone={intra ? "blue" : "terracotta"}>{intra ? "Intra-state" : "Inter-state"}</Badge></dt>
        <dd className="num">{inr(total)}</dd>
      </div>
    </dl>
  );
}
