import { Suspense, lazy, type ComponentType, type ReactNode } from "react";
import { Navigate, Route, Routes, useLocation } from "react-router-dom";
import { AppShell } from "@/components/layout/AppShell";
import { Spinner } from "@/components/ui";
import { HOME, useAuth } from "@/lib/auth";
import type { Role } from "@/lib/types";
import LoginPage from "@/pages/LoginPage";

// Each page group is its own chunk, so a role downloads only the screens it uses
// (e.g. salesmen never load the charts library used by the dashboard and production).
const page = <M extends Record<string, unknown>>(load: () => Promise<M>, name: keyof M) =>
  lazy(() => load().then((m) => ({ default: m[name] as ComponentType })));
const MasterData = page(() => import("@/pages/masters/MasterData"), "default");
const InvoiceList = page(() => import("@/pages/admin/Invoices"), "InvoiceList");
const InvoiceDetail = page(() => import("@/pages/admin/Invoices"), "InvoiceDetail");
const ApprovalQueue = page(() => import("@/pages/admin/Orders"), "ApprovalQueue");
const OrderReview = page(() => import("@/pages/admin/Orders"), "OrderReview");
const PaymentsPage = page(() => import("@/pages/admin/Payments"), "default");
const Dashboard = page(() => import("@/pages/owner/Dashboard"), "default");
const RunList = page(() => import("@/pages/production/Production"), "RunList");
const RunDetail = page(() => import("@/pages/production/Production"), "RunDetail");
const MyOrders = page(() => import("@/pages/sales/Sales"), "MyOrders");
const NewOrder = page(() => import("@/pages/sales/Sales"), "NewOrder");
const SalesOrderDetail = page(() => import("@/pages/sales/Sales"), "SalesOrderDetail");
const CustomerHistory = page(() => import("@/pages/sales/Sales"), "CustomerHistory");
const AuditLog = page(() => import("@/pages/shared/AuditLog"), "default");
const Purchases = page(() => import("@/pages/shared/Operations"), "Purchases");
const Stock = page(() => import("@/pages/shared/Operations"), "Stock");
const Boms = page(() => import("@/pages/shared/Operations"), "Boms");
const Reports = page(() => import("@/pages/shared/Reports"), "default");

/** Route guard: must be signed in, and (optionally) have one of `roles`. UX only — the API enforces too. */
function Guard({ roles, children }: { roles?: Role[]; children: ReactNode }) {
  const { user, loading } = useAuth();
  const location = useLocation();
  if (loading) return <Spinner />;
  if (!user) return <Navigate to="/login" replace state={{ from: location.pathname }} />;
  if (roles && !roles.includes(user.role)) return <Navigate to={HOME[user.role]} replace />;
  return <Suspense fallback={<Spinner />}>{children}</Suspense>;
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
