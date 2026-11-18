/**
 * Display formatting for the exact decimal strings the API returns.
 * Pure string manipulation: no parseFloat, so "7875.00" can never become 7874.999.
 */

/** Indian digit grouping of an integer string: 1234567 -> 12,34,567 */
function groupIndian(int: string): string {
  if (int.length <= 3) return int;
  const last3 = int.slice(-3);
  let rest = int.slice(0, -3);
  const parts: string[] = [];
  while (rest.length > 2) {
    parts.unshift(rest.slice(-2));
    rest = rest.slice(0, -2);
  }
  if (rest) parts.unshift(rest);
  return `${parts.join(",")},${last3}`;
}

function split(value: string): { neg: boolean; int: string; frac: string } {
  const neg = value.startsWith("-");
  const [int, frac = ""] = value.replace("-", "").split(".");
  return { neg, int: int.replace(/^0+(?=\d)/, ""), frac };
}

/** Round a decimal string half-up to `dp` places using BigInt (no floats): ("31.146", 2) -> "31.15" */
export function roundStr(value: string, dp: number): string {
  const neg = value.startsWith("-");
  const [int, frac = ""] = value.replace("-", "").split(".");
  const padded = (frac + "0".repeat(dp + 1)).slice(0, dp + 1);
  let n = BigInt(int + padded);
  n = n / 10n + (n % 10n >= 5n ? 1n : 0n); // drop the guard digit, rounding half up
  const s = n.toString().padStart(dp + 1, "0");
  const out = dp ? `${s.slice(0, -dp)}.${s.slice(-dp)}` : s;
  return neg && !/^[0.]+$/.test(out) ? `-${out}` : out;
}

/** "7875.00" -> "₹7,875.00" (always 2 decimals; input is already rounded by the server) */
export function inr(value: string | null | undefined, symbol = true): string {
  if (value === null || value === undefined || value === "") return "—";
  const { neg, int, frac } = split(value);
  const paise = (frac + "00").slice(0, 2);
  return `${neg ? "−" : ""}${symbol ? "₹" : ""}${groupIndian(int)}.${paise}`;
}

/** "10.5000" -> "10.5", "238.0000" -> "238" */
export function qty(value: string | null | undefined): string {
  if (value === null || value === undefined || value === "") return "—";
  const { neg, int, frac } = split(value);
  const trimmed = frac.replace(/0+$/, "");
  return `${neg ? "−" : ""}${groupIndian(int)}${trimmed ? "." + trimmed : ""}`;
}

/** "-6.0000" -> "−6.00%", with explicit + for positive variances */
export function pct(value: string | null | undefined, signed = false): string {
  if (value === null || value === undefined || value === "") return "—";
  const { neg, int, frac } = split(value);
  const two = (frac + "00").slice(0, 2);
  const isZero = /^0*$/.test(int + two);
  const sign = neg && !isZero ? "−" : signed && !isZero ? "+" : "";
  return `${sign}${int}.${two}%`;
}

export function isNegative(value: string | null | undefined): boolean {
  return !!value && value.startsWith("-") && !/^-0*\.?0*$/.test(value);
}

export function isZero(value: string | null | undefined): boolean {
  return !value || /^-?0*\.?0*$/.test(value);
}

export function date(iso: string | null | undefined): string {
  if (!iso) return "—";
  const [y, m, d] = iso.slice(0, 10).split("-");
  return `${d}-${m}-${y}`;
}

export function dateTime(iso: string | null | undefined): string {
  if (!iso) return "—";
  const dt = new Date(iso);
  return dt.toLocaleString("en-IN", { day: "2-digit", month: "short", hour: "2-digit", minute: "2-digit" });
}

/** Local calendar date (not UTC: in IST, toISOString() is still "yesterday" until 05:30). */
export const today = () => {
  const d = new Date();
  return `${d.getFullYear()}-${String(d.getMonth() + 1).padStart(2, "0")}-${String(d.getDate()).padStart(2, "0")}`;
};
export const monthStart = () => today().slice(0, 8) + "01";

const ACRONYMS = new Set(["UPI", "GST", "IGST", "CGST", "SGST", "BOM", "FG"]);

/** "PARTIALLY_DISPATCHED" -> "Partially Dispatched"; acronyms like UPI stay upper-case. */
export function label(enumValue: string): string {
  return enumValue
    .split("_")
    .map((w) => (ACRONYMS.has(w) ? w : w[0] + w.slice(1).toLowerCase()))
    .join(" ");
}
