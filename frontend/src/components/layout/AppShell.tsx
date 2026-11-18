import {
  BarChart3, ClipboardCheck, ClipboardList, Factory, FileText, Gauge, IndianRupee, LogOut, Menu, Package,
  PlusCircle, ScrollText, ShoppingCart, Truck, Warehouse, X, type LucideIcon,
} from "lucide-react";
import { useState, type ReactNode } from "react";
import { NavLink, Outlet } from "react-router-dom";
import { cx } from "@/components/ui";
import { useAuth } from "@/lib/auth";
import type { Role } from "@/lib/types";

interface NavItem { to: string; label: string; icon: LucideIcon; end?: boolean }

/** What each role sees. The server still checks every request; this is navigation only. */
export const NAV: Record<Role, NavItem[]> = {
  SALESMAN: [
    { to: "/sales", label: "My orders", icon: ClipboardList, end: true },
    { to: "/sales/new", label: "New order", icon: PlusCircle },
    { to: "/sales/history", label: "Customer sales", icon: BarChart3 },
  ],
  ADMIN: [
    { to: "/admin/orders", label: "Approvals", icon: ClipboardCheck },
    { to: "/admin/invoices", label: "Invoices & dispatch", icon: FileText },
    { to: "/admin/payments", label: "Payments", icon: IndianRupee },
    { to: "/purchases", label: "Purchases", icon: ShoppingCart },
    { to: "/stock", label: "Stock", icon: Warehouse },
    { to: "/dashboard", label: "Dashboard", icon: Gauge },
    { to: "/reports", label: "Reports", icon: BarChart3 },
    { to: "/audit", label: "Audit trail", icon: ScrollText },
  ],
  PRODUCTION: [
    { to: "/production", label: "Production runs", icon: Factory },
    { to: "/purchases", label: "Material receipts", icon: Truck },
    { to: "/stock", label: "Stock", icon: Warehouse },
    { to: "/boms", label: "Bills of materials", icon: Package },
    { to: "/reports", label: "Reports", icon: BarChart3 },
  ],
  OWNER: [
    { to: "/dashboard", label: "Dashboard", icon: Gauge },
    { to: "/reports", label: "Reports", icon: BarChart3 },
    { to: "/stock", label: "Stock", icon: Warehouse },
    { to: "/production", label: "Production", icon: Factory },
    { to: "/audit", label: "Audit trail", icon: ScrollText },
  ],
  AUDITOR: [
    { to: "/reports", label: "Reports", icon: BarChart3 },
    { to: "/dashboard", label: "Dashboard", icon: Gauge },
    { to: "/stock", label: "Stock", icon: Warehouse },
    { to: "/audit", label: "Audit trail", icon: ScrollText },
  ],
};

const ROLE_LABEL: Record<Role, string> = {
  SALESMAN: "Salesman", ADMIN: "Admin", PRODUCTION: "Production", OWNER: "Owner", AUDITOR: "Accountant / Auditor",
};

function Brand() {
  return (
    <div className="flex items-center gap-2.5">
      <svg viewBox="0 0 32 32" className="h-8 w-8" aria-hidden>
        <rect width="32" height="32" rx="7" fill="#C2643A" />
        <circle cx="16" cy="16" r="8" fill="none" stroke="#fff" strokeWidth="3" strokeDasharray="4 2.3" />
      </svg>
      <div className="leading-tight">
        <div className="text-sm font-semibold text-white">Annapoorna Snacks</div>
        <div className="text-[11px] text-navy-200">Order-to-Audit</div>
      </div>
    </div>
  );
}

function NavLinks({ items, onNavigate }: { items: NavItem[]; onNavigate?: () => void }) {
  return (
    <nav className="space-y-0.5">
      {items.map(({ to, label, icon: Icon, end }) => (
        <NavLink key={to} to={to} end={end} onClick={onNavigate}
          className={({ isActive }) => cx(
            "flex items-center gap-3 rounded-lg px-3 py-2 text-sm font-medium transition-colors",
            isActive ? "bg-white/10 text-white" : "text-navy-200 hover:bg-white/5 hover:text-white",
          )}>
          {({ isActive }) => (<>
            <Icon className={cx("h-4 w-4", isActive && "text-terracotta-500")} />{label}
          </>)}
        </NavLink>
      ))}
    </nav>
  );
}

export function AppShell({ children }: { children?: ReactNode }) {
  const { user, logout } = useAuth();
  const [open, setOpen] = useState(false);
  if (!user) return null;
  const items = NAV[user.role];
  const isSalesman = user.role === "SALESMAN";

  const sidebar = (
    <div className="flex h-full flex-col bg-navy-800 px-3 py-4">
      <div className="mb-6 px-2"><Brand /></div>
      <NavLinks items={items} onNavigate={() => setOpen(false)} />
      <div className="mt-auto rounded-lg bg-white/5 p-3">
        <div className="truncate text-sm font-medium text-white">{user.full_name}</div>
        <div className="text-xs text-navy-200">{ROLE_LABEL[user.role]}</div>
        <button onClick={logout} className="mt-2 flex items-center gap-1.5 text-xs text-navy-200 hover:text-white">
          <LogOut className="h-3.5 w-3.5" /> Sign out
        </button>
      </div>
    </div>
  );

  return (
    <div className="min-h-screen lg:pl-60">
      <aside className="fixed inset-y-0 left-0 hidden w-60 lg:block">{sidebar}</aside>

      {/* Mobile top bar */}
      <header className="sticky top-0 z-30 flex items-center justify-between bg-navy-800 px-4 py-3 lg:hidden">
        <Brand />
        {!isSalesman && (
          <button onClick={() => setOpen(true)} className="rounded p-1.5 text-white" aria-label="Open menu"><Menu className="h-5 w-5" /></button>
        )}
        {isSalesman && (
          <button onClick={logout} className="flex items-center gap-1 text-xs text-navy-200" aria-label="Sign out"><LogOut className="h-4 w-4" /></button>
        )}
      </header>

      {open && (
        <div className="fixed inset-0 z-40 lg:hidden">
          <div className="absolute inset-0 bg-navy-900/50" onClick={() => setOpen(false)} />
          <div className="absolute inset-y-0 left-0 w-64">
            <button onClick={() => setOpen(false)} className="absolute right-2 top-3 z-10 p-1 text-white" aria-label="Close menu"><X className="h-5 w-5" /></button>
            {sidebar}
          </div>
        </div>
      )}

      <main className={cx("mx-auto max-w-7xl px-4 py-5 sm:px-6 lg:py-8", isSalesman && "pb-24 lg:pb-8")}>
        {children ?? <Outlet />}
      </main>

      {/* Salesman: thumb-friendly bottom navigation on phones */}
      {isSalesman && (
        <nav className="fixed inset-x-0 bottom-0 z-30 grid grid-cols-3 border-t border-navy-100 bg-white pb-[env(safe-area-inset-bottom)] lg:hidden">
          {items.map(({ to, label, icon: Icon, end }) => (
            <NavLink key={to} to={to} end={end}
              className={({ isActive }) => cx("flex flex-col items-center gap-0.5 py-2 text-[11px] font-medium",
                isActive ? "text-terracotta-600" : "text-navy-400")}>
              <Icon className="h-5 w-5" />{label}
            </NavLink>
          ))}
        </nav>
      )}
    </div>
  );
}
