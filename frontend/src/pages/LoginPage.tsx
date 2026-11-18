import { motion } from "framer-motion";
import { Lock, User as UserIcon } from "lucide-react";
import { useState, type FormEvent } from "react";
import { Navigate, useLocation, useNavigate } from "react-router-dom";
import { Button, ErrorBanner } from "@/components/ui";
import { HOME, useAuth } from "@/lib/auth";

const DEMO = [
  ["salesman_a", "Salesman"], ["admin", "Admin"], ["production", "Production"], ["owner", "Owner"], ["auditor", "Auditor"],
];

export default function LoginPage() {
  const { user, login } = useAuth();
  const navigate = useNavigate();
  const location = useLocation();
  const [username, setUsername] = useState("");
  const [password, setPassword] = useState("");
  const [error, setError] = useState<unknown>(null);
  const [busy, setBusy] = useState(false);

  if (user) return <Navigate to={HOME[user.role]} replace />;

  async function submit(e: FormEvent) {
    e.preventDefault();
    setBusy(true);
    setError(null);
    try {
      const u = await login(username.trim().toLowerCase(), password);
      const from = (location.state as { from?: string } | null)?.from;
      navigate(from && from !== "/login" ? from : HOME[u.role], { replace: true });
    } catch (err) {
      setError(err);
    } finally {
      setBusy(false);
    }
  }

  return (
    <div className="grid min-h-screen lg:grid-cols-2">
      <div className="relative hidden overflow-hidden bg-navy-800 p-12 text-white lg:flex lg:flex-col lg:justify-between">
        <div className="flex items-center gap-3">
          <svg viewBox="0 0 32 32" className="h-10 w-10" aria-hidden>
            <rect width="32" height="32" rx="7" fill="#C2643A" />
            <circle cx="16" cy="16" r="8" fill="none" stroke="#fff" strokeWidth="3" strokeDasharray="4 2.3" />
          </svg>
          <div>
            <div className="font-semibold">Sri Annapoorna Snacks</div>
            <div className="text-sm text-navy-200">Coimbatore, Tamil Nadu</div>
          </div>
        </div>
        <div>
          <h1 className="max-w-md text-3xl font-semibold leading-tight">From the salesman's order to the auditor's report, on one ledger.</h1>
          <ul className="mt-6 space-y-2 text-sm text-navy-200">
            <li>Orders verified against live, reserved stock</li>
            <li>GST invoices with CGST/SGST or IGST by place of supply</li>
            <li>BOM-driven production with variance alerts and costing</li>
            <li>Every stock change traceable to a document</li>
          </ul>
        </div>
        <p className="text-xs text-navy-400">Internship prototype · all data is fictional</p>
      </div>

      <div className="flex items-center justify-center px-5 py-10">
        <motion.form onSubmit={submit} initial={{ opacity: 0, y: 8 }} animate={{ opacity: 1, y: 0 }}
          className="w-full max-w-sm space-y-5">
          <div>
            <h2 className="text-2xl font-semibold">Sign in</h2>
            <p className="mt-1 text-sm text-navy-400">Use your Annapoorna account.</p>
          </div>
          <ErrorBanner error={error} />
          <label className="block">
            <span className="label">Username</span>
            <div className="relative">
              <UserIcon className="absolute left-3 top-2.5 h-4 w-4 text-navy-400" />
              <input className="input pl-9" autoComplete="username" autoCapitalize="none" required
                value={username} onChange={(e) => setUsername(e.target.value)} />
            </div>
          </label>
          <label className="block">
            <span className="label">Password</span>
            <div className="relative">
              <Lock className="absolute left-3 top-2.5 h-4 w-4 text-navy-400" />
              <input className="input pl-9" type="password" autoComplete="current-password" required
                value={password} onChange={(e) => setPassword(e.target.value)} />
            </div>
          </label>
          <Button type="submit" variant="accent" size="lg" className="w-full" loading={busy}>Sign in</Button>
          <div className="rounded-lg border border-dashed border-navy-200 p-3">
            <p className="text-xs text-navy-400">Demo accounts (password in the README):</p>
            <div className="mt-2 flex flex-wrap gap-1.5">
              {DEMO.map(([u, role]) => (
                <button type="button" key={u} onClick={() => setUsername(u)}
                  className="rounded-full bg-navy-50 px-2.5 py-1 text-xs text-navy-600 hover:bg-navy-100">
                  {role}
                </button>
              ))}
            </div>
          </div>
        </motion.form>
      </div>
    </div>
  );
}
