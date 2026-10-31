import { FormEvent, useState } from "react";
import { api, User } from "../api";
import { Mark } from "../components/Mark";

const DEMO = [
  ["manager@stockpilot.dev", "manager123", "Manager"],
  ["clerk@stockpilot.dev", "clerk123", "Clerk"],
  ["admin@stockpilot.dev", "admin123", "Admin"],
] as const;

const WHAT: Record<string, string> = {
  Manager: "Managers sign off the planner's suggestions and place orders.",
  Clerk: "Clerks receive deliveries, sell at the till and count stock.",
  Admin: "Admins can do everything, including users and rules.",
};

export default function Login({ onLogin }: { onLogin: (token: string, user: User) => void }) {
  const [email, setEmail] = useState<string>(DEMO[0][0]);
  const [password, setPassword] = useState<string>(DEMO[0][1]);
  const [role, setRole] = useState<string>(DEMO[0][2]);
  const [error, setError] = useState<string | null>(null);
  const [busy, setBusy] = useState(false);
  const submit = async (e: FormEvent) => {
    e.preventDefault();
    setBusy(true);
    setError(null);
    try {
      const r = await api.post<{ token: string; user: User }>("/auth/login", { email, password });
      onLogin(r.token, r.user);
    } catch (err) {
      setError((err as Error).message);
      setBusy(false);
    }
  };
  return (
    <div className="sign">
      <div>
        <div className="brand"><Mark /> Stockpilot</div>
        <h1>Stock for a warehouse and the stores it feeds, <b>with a planner that asks first.</b></h1>
        <p className="lede">Claude reads your stock, rules and sales every morning and suggests what to order and what to move. Nothing happens until a manager approves it.</p>
        <ul className="points">
          <li>Receive a delivery by scanning the delivery note.</li>
          <li>Sell at the till and keep every store's shelf in step.</li>
          <li>See what is low, what is expiring and what to do about it.</li>
        </ul>
      </div>
      <form className="glass" onSubmit={submit} aria-labelledby="sign-in-title">
        <div>
          <h2 id="sign-in-title">Sign in</h2>
          <p className="muted small" style={{ marginTop: 4 }}>Demo data: three sites and ninety days of history.</p>
        </div>
        <div className="roles" role="radiogroup" aria-label="Demo role">
          {DEMO.map(([e, p, label]) => (
            <button type="button" role="radio" key={e} aria-checked={role === label} onClick={() => { setRole(label); setEmail(e); setPassword(p); }}>{label}</button>
          ))}
        </div>
        <p className="muted small" style={{ marginTop: -6 }}>{WHAT[role]}</p>
        <label>Email<input value={email} onChange={(e) => setEmail(e.target.value)} autoComplete="username" /></label>
        <label>Password<input type="password" value={password} onChange={(e) => setPassword(e.target.value)} autoComplete="current-password" /></label>
        {error && <p className="error" role="alert">{error}</p>}
        <button className="primary" type="submit" disabled={busy}>{busy ? "Signing in" : "Sign in"}</button>
      </form>
    </div>
  );
}
