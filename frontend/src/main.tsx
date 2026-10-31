import React, { useEffect, useState } from "react";
import ReactDOM from "react-dom/client";
import { BrowserRouter, NavLink, Navigate, Route, Routes, useLocation } from "react-router-dom";
import { api, auth, User } from "./api";
import { SessionCtx } from "./components/ui";
import { Mark } from "./components/Mark";
import "@fontsource-variable/archivo/standard.css";
import "@fontsource/ibm-plex-mono/400.css";
import "@fontsource/ibm-plex-mono/500.css";
import "./styles.css";
import Dashboard from "./pages/Dashboard";
import Products from "./pages/Products";
import ProductDetail from "./pages/ProductDetail";
import Stock from "./pages/Stock";
import Purchasing from "./pages/Purchasing";
import Sales from "./pages/Sales";
import Transfers from "./pages/Transfers";
import Counts from "./pages/Counts";
import Replenishment from "./pages/Replenishment";
import Insights from "./pages/Insights";
import Ledger from "./pages/Ledger";
import Login from "./pages/Login";
import Copilot from "./pages/Copilot";
import POS from "./pages/POS";

const RANK = { clerk: 1, manager: 2, admin: 3 } as const;

const NAV: { group: string; items: [string, string][] }[] = [
  { group: "Today", items: [["/", "Today"], ["/copilot", "Planner"], ["/pos", "Point of sale"]] },
  { group: "Move stock", items: [["/purchasing", "Purchasing"], ["/sales", "Sales orders"], ["/transfers", "Transfers"], ["/counts", "Cycle counts"]] },
  { group: "Plan", items: [["/replenishment", "Replenishment"], ["/insights", "Demand"]] },
  { group: "Records", items: [["/products", "Products"], ["/stock", "Stock on hand"], ["/ledger", "Ledger"]] },
];

function Nav() {
  const loc = useLocation();
  const [pending, setPending] = useState(0);
  useEffect(() => {
    api.get<unknown[]>("/ai/proposals?status=pending").then((r) => setPending(r.length)).catch(() => setPending(0));
  }, [loc.pathname]);
  return (
    <nav>
      {NAV.map(({ group, items }) => (
        <div key={group} role="group" aria-label={group}>
          <div className="nav-group">{group}</div>
          {items.map(([to, label]) => (
            <NavLink key={to} to={to} end={to === "/"}>
              {label}
              {to === "/copilot" && pending > 0 && <span className="count" aria-label={`${pending} proposals waiting`}>{pending}</span>}
            </NavLink>
          ))}
        </div>
      ))}
    </nav>
  );
}

function App() {
  const [user, setUser] = useState<User | null>(null);
  const [ready, setReady] = useState(false);
  const [toasts, setToasts] = useState<{ id: number; msg: string; kind: string }[]>([]);

  useEffect(() => {
    if (!auth.token) return setReady(true);
    api.get<User>("/auth/me").then(setUser).catch(() => auth.set(null)).finally(() => setReady(true));
  }, []);

  if (!ready) return null;
  if (!user) return <Login onLogin={(t, u) => { auth.set(t); setUser(u); }} />;

  const toast = (msg: string, kind: "ok" | "err" = "ok") => {
    const id = Date.now() + Math.random();
    setToasts((t) => [...t, { id, msg, kind }]);
    setTimeout(() => setToasts((t) => t.filter((x) => x.id !== id)), kind === "err" ? 6000 : 3000);
  };
  const can = (r: User["role"]) => RANK[user.role] >= RANK[r];

  return (
    <SessionCtx.Provider value={{ user, can, toast }}>
      <BrowserRouter>
        <div className="shell">
          <aside className="side" aria-label="Main navigation">
            <div className="brand"><Mark /> Stockpilot</div>
            <Nav />
            <div className="me">
              <div>
                <b>{user.name}</b>
                <div className="faint small" style={{ textTransform: "capitalize" }}>{user.role}</div>
              </div>
              <button className="ghost small" onClick={() => { auth.set(null); setUser(null); }}>Sign out</button>
            </div>
          </aside>
          <main>
            <Routes>
              <Route path="/" element={<Dashboard />} />
              <Route path="/copilot" element={<Copilot />} />
              <Route path="/products" element={<Products />} />
              <Route path="/products/:id" element={<ProductDetail />} />
              <Route path="/stock" element={<Stock />} />
              <Route path="/purchasing" element={<Purchasing />} />
              <Route path="/sales" element={<Sales />} />
              <Route path="/pos" element={<POS />} />
              <Route path="/transfers" element={<Transfers />} />
              <Route path="/counts" element={<Counts />} />
              <Route path="/replenishment" element={<Replenishment />} />
              <Route path="/insights" element={<Insights />} />
              <Route path="/ledger" element={<Ledger />} />
              <Route path="*" element={<Navigate to="/" />} />
            </Routes>
          </main>
        </div>
        <div className="toasts" role="status" aria-live="polite">
          {toasts.map((t) => <div key={t.id} className={`toast ${t.kind}`}>{t.msg}</div>)}
        </div>
      </BrowserRouter>
    </SessionCtx.Provider>
  );
}

ReactDOM.createRoot(document.getElementById("root")!).render(<React.StrictMode><App /></React.StrictMode>);
