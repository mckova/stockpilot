import { ReactNode, useCallback, useEffect, useState } from "react";
import { createContext, useContext } from "react";
import { User } from "../api";

// ----------------------------------------------------------------- data hook

export function useLoad<T>(fn: () => Promise<T>, deps: unknown[] = []) {
  const [data, setData] = useState<T | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [loading, setLoading] = useState(true);
  const reload = useCallback(() => {
    setLoading(true);
    fn()
      .then((d) => { setData(d); setError(null); })
      .catch((e: Error) => setError(e.message))
      .finally(() => setLoading(false));
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, deps);
  useEffect(reload, [reload]);
  return { data, error, loading, reload };
}

// ----------------------------------------------------------------- session + toasts

export const SessionCtx = createContext<{ user: User; can: (r: User["role"]) => boolean; toast: (m: string, kind?: "ok" | "err") => void }>(null!);
export const useSession = () => useContext(SessionCtx);

/** Wraps an async action with a toast on success/failure. */
export function useAction() {
  const { toast } = useSession();
  const [busy, setBusy] = useState(false);
  const run = async (fn: () => Promise<unknown>, ok?: string) => {
    setBusy(true);
    try {
      await fn();
      if (ok) toast(ok, "ok");
      return true;
    } catch (e) {
      toast((e as Error).message, "err");
      return false;
    } finally {
      setBusy(false);
    }
  };
  return { run, busy };
}

// ----------------------------------------------------------------- formatting

export const money = (n: number) => "₪" + n.toLocaleString("en-US", { maximumFractionDigits: 0 });
export const money2 = (n: number) => "₪" + n.toLocaleString("en-US", { minimumFractionDigits: 2, maximumFractionDigits: 2 });
export const num = (n: number) => n.toLocaleString("en-US", { maximumFractionDigits: 2 });
export const dt = (s: string) => new Date(s).toLocaleString("en-GB", { day: "2-digit", month: "short", hour: "2-digit", minute: "2-digit" });
export const day = (s: string) => new Date(s).toLocaleDateString("en-GB", { day: "2-digit", month: "short" });

// ----------------------------------------------------------------- components

export function Page({ title, subtitle, actions, children }: { title: string; subtitle?: string; actions?: ReactNode; children: ReactNode }) {
  return (
    <div className="page">
      <header className="page-head">
        <div>
          <h1>{title}</h1>
          {subtitle && <p className="muted">{subtitle}</p>}
        </div>
        <div className="row">{actions}</div>
      </header>
      {children}
    </div>
  );
}

export function Status({ value }: { value: string }) {
  return <span className={`badge s-${value}`}>{value.replace("_", " ")}</span>;
}

export function Card({ title, children, extra }: { title?: string; children: ReactNode; extra?: ReactNode }) {
  return (
    <section className="card">
      {title && (
        <div className="card-head">
          <h3>{title}</h3>
          {extra}
        </div>
      )}
      {children}
    </section>
  );
}

export function Modal({ title, onClose, children }: { title: string; onClose: () => void; children: ReactNode }) {
  useEffect(() => {
    const esc = (e: KeyboardEvent) => e.key === "Escape" && onClose();
    window.addEventListener("keydown", esc);
    return () => window.removeEventListener("keydown", esc);
  }, [onClose]);
  return (
    <div className="modal-bg" onMouseDown={onClose}>
      <div className="modal" onMouseDown={(e) => e.stopPropagation()}>
        <div className="card-head">
          <h3>{title}</h3>
          <button className="ghost" onClick={onClose} aria-label="close">✕</button>
        </div>
        {children}
      </div>
    </div>
  );
}

export function Loading({ error }: { error?: string | null }) {
  return error ? <div className="error">{error}</div> : <div className="muted pad">Loading…</div>;
}

export function Empty({ children }: { children: ReactNode }) {
  return <div className="empty">{children}</div>;
}

export function Spark({ values, w = 120, h = 28 }: { values: number[]; w?: number; h?: number }) {
  const max = Math.max(...values, 1);
  const pts = values.map((v, i) => `${(i / Math.max(values.length - 1, 1)) * w},${h - (v / max) * (h - 2) - 1}`).join(" ");
  return (
    <svg width={w} height={h} className="spark" aria-hidden>
      <polyline points={pts} fill="none" stroke="currentColor" strokeWidth="1.5" />
    </svg>
  );
}
