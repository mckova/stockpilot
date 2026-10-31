import { FormEvent, useState } from "react";
import { api, User } from "../api";

const DEMO = [
  ["manager@stockpilot.dev", "manager123", "Manager"],
  ["clerk@stockpilot.dev", "clerk123", "Clerk"],
  ["admin@stockpilot.dev", "admin123", "Admin"],
];

export default function Login({ onLogin }: { onLogin: (token: string, user: User) => void }) {
  const [email, setEmail] = useState(DEMO[0][0]);
  const [password, setPassword] = useState(DEMO[0][1]);
  const [error, setError] = useState<string | null>(null);

  const submit = async (e: FormEvent) => {
    e.preventDefault();
    try {
      const r = await api.post<{ token: string; user: User }>("/auth/login", { email, password });
      onLogin(r.token, r.user);
    } catch (err) {
      setError((err as Error).message);
    }
  };

  return (
    <div className="login">
      <form className="card login-card" onSubmit={submit}>
        <div className="brand big"><span className="logo">S</span> Stockpilot</div>
        <p className="muted">Multi-site warehouse &amp; inventory management</p>
        <label>Email<input value={email} onChange={(e) => setEmail(e.target.value)} autoFocus /></label>
        <label>Password<input type="password" value={password} onChange={(e) => setPassword(e.target.value)} /></label>
        {error && <div className="error">{error}</div>}
        <button className="primary" type="submit">Sign in</button>
        <div className="demo">
          <span className="muted small">Demo accounts:</span>
          {DEMO.map(([e, p, label]) => (
            <button type="button" key={e} className="chip" onClick={() => { setEmail(e); setPassword(p); }}>{label}</button>
          ))}
        </div>
      </form>
    </div>
  );
}
