import React, { useEffect, useState } from "react";
import ReactDOM from "react-dom/client";
import { BrowserRouter, NavLink, Navigate, Route, Routes } from "react-router-dom";
import { api, auth, User } from "./api";
import { SessionCtx } from "./components/ui";
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

const RANK = { clerk: 1, manager: 2, admin: 3 } as const;

const NAV: [string, string, string][] = [
  ["/", "Dashboard", "◧"],
  ["/copilot", "Copilot", "✦"],
  ["/products", "Products", "▦"],
  ["/stock", "Stock", "▤"],
  ["/purchasing", "Purchasing", "↓"],
  ["/sales", "Sales", "↑"],
  ["/transfers", "Transfers", "⇄"],
  ["/counts", "Cycle counts", "✓"],
  ["/replenishment", "Replenishment", "↻"],
  ["/insights", "Insights", "∿"],
  ["/ledger", "Ledger", "≡"],
];

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
          <aside className="side">
            <div className="brand">
              <span className="logo">S</span> Stockpilot
            </div>
            <nav>
              {NAV.map(([to, label, icon]) => (
                <NavLink key={to} to={to} end={to === "/"}>
                  <span className="ico">{icon}</span>
                  {label}
                </NavLink>
              ))}
            </nav>
            <div className="me">
              <div>
                <b>{user.name}</b>
                <div className="muted small">{user.role}</div>
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
              <Route path="/transfers" element={<Transfers />} />
              <Route path="/counts" element={<Counts />} />
              <Route path="/replenishment" element={<Replenishment />} />
              <Route path="/insights" element={<Insights />} />
              <Route path="/ledger" element={<Ledger />} />
              <Route path="*" element={<Navigate to="/" />} />
            </Routes>
          </main>
        </div>
        <div className="toasts">
          {toasts.map((t) => <div key={t.id} className={`toast ${t.kind}`}>{t.msg}</div>)}
        </div>
      </BrowserRouter>
    </SessionCtx.Provider>
  );
}

ReactDOM.createRoot(document.getElementById("root")!).render(<React.StrictMode><App /></React.StrictMode>);
