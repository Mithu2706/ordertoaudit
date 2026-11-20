/** Small, consistent UI kit (Tailwind). Deliberately plain: usability over decoration. */
import { AnimatePresence, motion } from "framer-motion";
import { AlertTriangle, CheckCircle2, Inbox, Loader2, X } from "lucide-react";
import {
  createContext, useCallback, useContext, useState,
  type ButtonHTMLAttributes, type ReactNode,
} from "react";
import { ApiError } from "@/lib/api";
import { label as enumLabel } from "@/lib/format";

const cx = (...c: (string | false | null | undefined)[]) => c.filter(Boolean).join(" ");
export { cx };

// ---- Button ------------------------------------------------------------------------
type Variant = "primary" | "secondary" | "ghost" | "danger" | "accent";
const VARIANTS: Record<Variant, string> = {
  primary: "bg-navy-800 text-white hover:bg-navy-700 shadow-sm",
  accent: "bg-terracotta-600 text-white hover:bg-terracotta-700 shadow-sm",
  secondary: "bg-white text-navy-800 border border-navy-200 hover:bg-navy-50",
  ghost: "text-navy-600 hover:bg-navy-100",
  danger: "bg-white text-red-700 border border-red-200 hover:bg-red-50",
};

export function Button({
  variant = "primary", loading, icon, children, className, size = "md", ...rest
}: ButtonHTMLAttributes<HTMLButtonElement> & { variant?: Variant; loading?: boolean; icon?: ReactNode; size?: "sm" | "md" | "lg" }) {
  const sizes = { sm: "px-2.5 py-1.5 text-xs", md: "px-3.5 py-2 text-sm", lg: "px-4 py-3 text-base" };
  return (
    <button
      className={cx(
        "inline-flex items-center justify-center gap-2 rounded-lg font-medium transition-colors disabled:cursor-not-allowed disabled:opacity-50",
        VARIANTS[variant], sizes[size], className,
      )}
      {...rest}
      disabled={loading || rest.disabled} /* after the spread: a loading button can never be clicked twice */
    >
      {loading ? <Loader2 className="h-4 w-4 animate-spin" /> : icon}
      {children}
    </button>
  );
}

// ---- Layout pieces ---------------------------------------------------------------
export function Card({ children, className, title, actions }: { children: ReactNode; className?: string; title?: ReactNode; actions?: ReactNode }) {
  return (
    // min-w-0: as a grid/flex item, a wide table inside must scroll within the card, not stretch the page.
    <section className={cx("min-w-0 rounded-xl border border-navy-100 bg-white shadow-card", className)}>
      {(title || actions) && (
        <header className="flex items-center justify-between gap-3 border-b border-navy-100 px-4 py-3">
          <h2 className="text-sm font-semibold text-navy-800">{title}</h2>
          {actions}
        </header>
      )}
      {children}
    </section>
  );
}

export function PageHeader({ title, subtitle, actions, back }: { title: ReactNode; subtitle?: ReactNode; actions?: ReactNode; back?: ReactNode }) {
  return (
    <div className="mb-5 flex flex-wrap items-end justify-between gap-3">
      <div>
        {back}
        <h1 className="text-xl font-semibold tracking-tight text-navy-800 sm:text-2xl">{title}</h1>
        {subtitle && <p className="mt-1 text-sm text-navy-400">{subtitle}</p>}
      </div>
      {actions && <div className="flex flex-wrap gap-2">{actions}</div>}
    </div>
  );
}

export function Stat({ label, value, hint, tone = "default", icon }: { label: string; value: ReactNode; hint?: ReactNode; tone?: "default" | "warn" | "good" | "bad"; icon?: ReactNode }) {
  const tones = { default: "text-navy-800", warn: "text-amber-700", good: "text-emerald-700", bad: "text-red-700" };
  return (
    <div className="rounded-xl border border-navy-100 bg-white p-4 shadow-card">
      <div className="flex items-center justify-between text-xs font-medium uppercase tracking-wide text-navy-400">
        {label}
        {icon && <span className="text-navy-200">{icon}</span>}
      </div>
      <div className={cx("mt-2 text-2xl font-semibold tabular-nums", tones[tone])}>{value}</div>
      {hint && <div className="mt-1 text-xs text-navy-400">{hint}</div>}
    </div>
  );
}

// ---- Feedback ------------------------------------------------------------------------
export function Spinner({ label = "Loading…" }: { label?: string }) {
  return (
    <div className="flex items-center justify-center gap-2 py-12 text-sm text-navy-400">
      <Loader2 className="h-4 w-4 animate-spin" /> {label}
    </div>
  );
}

export function EmptyState({ title, hint, icon }: { title: string; hint?: ReactNode; icon?: ReactNode }) {
  return (
    <div className="flex flex-col items-center justify-center px-6 py-12 text-center">
      <div className="mb-3 rounded-full bg-navy-50 p-3 text-navy-400">{icon ?? <Inbox className="h-5 w-5" />}</div>
      <p className="text-sm font-medium text-navy-700">{title}</p>
      {hint && <p className="mt-1 max-w-sm text-sm text-navy-400">{hint}</p>}
    </div>
  );
}

export function ErrorBanner({ error, className }: { error: unknown; className?: string }) {
  if (!error) return null;
  const message = error instanceof ApiError ? error.message : error instanceof Error ? error.message : String(error);
  const fields = error instanceof ApiError && Array.isArray(error.details?.errors)
    ? (error.details.errors as { field: string; message: string }[]) : [];
  return (
    <div role="alert" className={cx("flex gap-3 rounded-lg border border-red-200 bg-red-50 px-4 py-3 text-sm text-red-800", className)}>
      <AlertTriangle className="mt-0.5 h-4 w-4 flex-none" />
      <div>
        <p>{message}</p>
        {fields.length > 0 && (
          <ul className="mt-1 list-disc pl-4 text-xs">
            {fields.map((f) => <li key={f.field + f.message}><b>{f.field}</b>: {f.message}</li>)}
          </ul>
        )}
      </div>
    </div>
  );
}

// ---- Badges ----------------------------------------------------------------------------
const TONES = {
  gray: "bg-navy-50 text-navy-600 ring-navy-200",
  blue: "bg-sky-50 text-sky-800 ring-sky-200",
  amber: "bg-amber-50 text-amber-700 ring-amber-100",
  green: "bg-emerald-50 text-emerald-700 ring-emerald-200",
  red: "bg-red-50 text-red-700 ring-red-200",
  terracotta: "bg-terracotta-50 text-terracotta-700 ring-terracotta-100",
};
export type Tone = keyof typeof TONES;

export function Badge({ children, tone = "gray", className }: { children: ReactNode; tone?: Tone; className?: string }) {
  return (
    <span className={cx("inline-flex items-center gap-1 whitespace-nowrap rounded-full px-2 py-0.5 text-xs font-medium ring-1 ring-inset", TONES[tone], className)}>
      {children}
    </span>
  );
}

const STATUS_TONE: Record<string, Tone> = {
  DRAFT: "gray", SUBMITTED: "blue", APPROVED: "terracotta", REJECTED: "red", INVOICED: "amber",
  PARTIALLY_DISPATCHED: "amber", DISPATCHED: "green", CANCELLED: "gray", ISSUED: "blue",
  PARTIALLY_CREDITED: "amber", POSTED: "green",
};

export function StatusBadge({ status }: { status: string }) {
  return <Badge tone={STATUS_TONE[status] ?? "gray"}>{enumLabel(status)}</Badge>;
}

// ---- Form field -------------------------------------------------------------------------
export function Field({ label, children, hint, className }: { label: string; children: ReactNode; hint?: ReactNode; className?: string }) {
  return (
    <label className={cx("block", className)}>
      <span className="label">{label}</span>
      {children}
      {hint && <span className="mt-1 block text-xs text-navy-400">{hint}</span>}
    </label>
  );
}

// ---- Table ------------------------------------------------------------------------------
export function Table({ children, className }: { children: ReactNode; className?: string }) {
  return (
    <div className={cx("overflow-x-auto", className)}>
      <table className="min-w-full divide-y divide-navy-100 text-sm">{children}</table>
    </div>
  );
}
export const Th = ({ children, right, className }: { children?: ReactNode; right?: boolean; className?: string }) => (
  <th className={cx("whitespace-nowrap bg-navy-50/60 px-3 py-2 text-xs font-semibold uppercase tracking-wide text-navy-400", right ? "text-right" : "text-left", className)}>{children}</th>
);
/** Cells don't wrap by default (codes, dates, amounts stay on one line; the table scrolls instead). */
export const Td = ({ children, right, className, colSpan, wrap }: { children?: ReactNode; right?: boolean; className?: string; colSpan?: number; wrap?: boolean }) => (
  <td colSpan={colSpan} className={cx("px-3 py-2.5 align-middle", !wrap && "whitespace-nowrap", right && "num", className)}>{children}</td>
);

// ---- Modal ------------------------------------------------------------------------------
export function Modal({ open, onClose, title, children, footer, wide }: { open: boolean; onClose: () => void; title: string; children: ReactNode; footer?: ReactNode; wide?: boolean }) {
  return (
    <AnimatePresence>
      {open && (
        <motion.div className="fixed inset-0 z-50 flex items-end justify-center bg-navy-900/40 p-0 sm:items-center sm:p-4"
          initial={{ opacity: 0 }} animate={{ opacity: 1 }} exit={{ opacity: 0 }} onMouseDown={onClose}>
          <motion.div role="dialog" aria-modal="true" aria-label={title}
            className={cx("max-h-[92vh] w-full overflow-y-auto rounded-t-2xl bg-white shadow-xl sm:rounded-2xl", wide ? "sm:max-w-3xl" : "sm:max-w-lg")}
            initial={{ y: 24, opacity: 0 }} animate={{ y: 0, opacity: 1 }} exit={{ y: 24, opacity: 0 }}
            transition={{ duration: 0.16 }} onMouseDown={(e) => e.stopPropagation()}>
            <div className="flex items-center justify-between border-b border-navy-100 px-5 py-3">
              <h3 className="font-semibold">{title}</h3>
              <button onClick={onClose} className="rounded p-1 text-navy-400 hover:bg-navy-50" aria-label="Close"><X className="h-4 w-4" /></button>
            </div>
            <div className="px-5 py-4">{children}</div>
            {footer && <div className="flex justify-end gap-2 border-t border-navy-100 px-5 py-3">{footer}</div>}
          </motion.div>
        </motion.div>
      )}
    </AnimatePresence>
  );
}

// ---- Toasts -----------------------------------------------------------------------------
interface Toast { id: number; message: string; tone: "success" | "error" }
const ToastCtx = createContext<(message: string, tone?: Toast["tone"]) => void>(() => {});
export const useToast = () => useContext(ToastCtx);

export function ToastProvider({ children }: { children: ReactNode }) {
  const [toasts, setToasts] = useState<Toast[]>([]);
  const push = useCallback((message: string, tone: Toast["tone"] = "success") => {
    const id = Date.now() + Math.random();
    setToasts((t) => [...t, { id, message, tone }]);
    setTimeout(() => setToasts((t) => t.filter((x) => x.id !== id)), 4000);
  }, []);
  return (
    <ToastCtx.Provider value={push}>
      {children}
      <div className="pointer-events-none fixed inset-x-0 bottom-20 z-[60] flex flex-col items-center gap-2 px-4 sm:bottom-6 sm:items-end">
        <AnimatePresence>
          {toasts.map((t) => (
            <motion.div key={t.id} initial={{ opacity: 0, y: 8 }} animate={{ opacity: 1, y: 0 }} exit={{ opacity: 0 }}
              className={cx("pointer-events-auto flex max-w-sm items-center gap-2 rounded-lg px-4 py-2.5 text-sm text-white shadow-lg",
                t.tone === "success" ? "bg-navy-800" : "bg-red-700")}>
              {t.tone === "success" ? <CheckCircle2 className="h-4 w-4" /> : <AlertTriangle className="h-4 w-4" />}
              {t.message}
            </motion.div>
          ))}
        </AnimatePresence>
      </div>
    </ToastCtx.Provider>
  );
}
