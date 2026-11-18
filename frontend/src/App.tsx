import type { ReactNode } from "react";
import { Navigate, Route, Routes, useLocation } from "react-router-dom";
import { AppShell } from "@/components/layout/AppShell";
import { Spinner } from "@/components/ui";
import { HOME, useAuth } from "@/lib/auth";
import type { Role } from "@/lib/types";
import LoginPage from "@/pages/LoginPage";
import MasterData from "@/pages/masters/MasterData";
import { InvoiceDetail, InvoiceList } from "@/pages/admin/Invoices";
import { ApprovalQueue, OrderReview } from "@/pages/admin/Orders";
import PaymentsPage from "@/pages/admin/Payments";
import Dashboard from "@/pages/owner/Dashboard";
import { RunDetail, RunList } from "@/pages/production/Production";
import { CustomerHistory, MyOrders, NewOrder, SalesOrderDetail } from "@/pages/sales/Sales";
import AuditLog from "@/pages/shared/AuditLog";
import { Boms, Purchases, Stock } from "@/pages/shared/Operations";
import Reports from "@/pages/shared/Reports";

/** Route guard: must be signed in, and (optionally) have one of `roles`. UX only — the API enforces too. */
function Guard({ roles, children }: { roles?: Role[]; children: ReactNode }) {
  const { user, loading } = useAuth();
  const location = useLocation();
  if (loading) return <Spinner />;
  if (!user) return <Navigate to="/login" replace state={{ from: location.pathname }} />;
  if (roles && !roles.includes(user.role)) return <Navigate to={HOME[user.role]} replace />;
  return <>{children}</>;
}

function Home() {
  const { user } = useAuth();
  return <Navigate to={user ? HOME[user.role] : "/login"} replace />;
}

export default function App() {
  return (
    <Routes>
      <Route path="/login" element={<LoginPage />} />
      <Route element={<Guard><AppShell /></Guard>}>
        <Route path="/sales" element={<Guard roles={["SALESMAN"]}><MyOrders /></Guard>} />
        <Route path="/sales/new" element={<Guard roles={["SALESMAN"]}><NewOrder /></Guard>} />
        <Route path="/sales/orders/:id" element={<Guard roles={["SALESMAN"]}><SalesOrderDetail /></Guard>} />
        <Route path="/sales/orders/:id/edit" element={<Guard roles={["SALESMAN"]}><NewOrder /></Guard>} />
        <Route path="/sales/history" element={<Guard roles={["SALESMAN"]}><CustomerHistory /></Guard>} />

        <Route path="/admin/orders" element={<Guard roles={["ADMIN", "OWNER", "AUDITOR"]}><ApprovalQueue /></Guard>} />
        <Route path="/admin/orders/:id" element={<Guard roles={["ADMIN", "OWNER", "AUDITOR"]}><OrderReview /></Guard>} />
        <Route path="/admin/invoices" element={<Guard roles={["ADMIN", "OWNER", "AUDITOR"]}><InvoiceList /></Guard>} />
        <Route path="/admin/invoices/:id" element={<Guard roles={["ADMIN", "OWNER", "AUDITOR"]}><InvoiceDetail /></Guard>} />
        <Route path="/admin/payments" element={<Guard roles={["ADMIN", "OWNER", "AUDITOR"]}><PaymentsPage /></Guard>} />

        <Route path="/production" element={<Guard roles={["PRODUCTION", "ADMIN", "OWNER", "AUDITOR"]}><RunList /></Guard>} />
        <Route path="/production/:id" element={<Guard roles={["PRODUCTION", "ADMIN", "OWNER", "AUDITOR"]}><RunDetail /></Guard>} />
        <Route path="/boms" element={<Guard roles={["PRODUCTION", "ADMIN", "OWNER", "AUDITOR"]}><Boms /></Guard>} />
        <Route path="/purchases" element={<Guard roles={["PRODUCTION", "ADMIN", "OWNER", "AUDITOR"]}><Purchases /></Guard>} />
        <Route path="/stock" element={<Guard roles={["PRODUCTION", "ADMIN", "OWNER", "AUDITOR"]}><Stock /></Guard>} />

        <Route path="/dashboard" element={<Guard roles={["OWNER", "ADMIN", "AUDITOR"]}><Dashboard /></Guard>} />
        <Route path="/reports" element={<Guard roles={["ADMIN", "PRODUCTION", "OWNER", "AUDITOR"]}><Reports /></Guard>} />
        <Route path="/masters" element={<Guard roles={["ADMIN", "PRODUCTION", "OWNER", "AUDITOR"]}><MasterData /></Guard>} />
        <Route path="/masters/:tab" element={<Guard roles={["ADMIN", "PRODUCTION", "OWNER", "AUDITOR"]}><MasterData /></Guard>} />
        <Route path="/audit" element={<Guard roles={["ADMIN", "OWNER", "AUDITOR"]}><AuditLog /></Guard>} />
      </Route>
      <Route path="*" element={<Home />} />
    </Routes>
  );
}
