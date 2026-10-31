import { X } from "lucide-react";
import { ReactNode, useCallback, useEffect, useId, useRef, useState } from "react";
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

export const money = (n: number) => (n < 0 ? "−₪" : "₪") + Math.abs(n).toLocaleString("en-US", { maximumFractionDigits: 0 });
export const money2 = (n: number) => (n < 0 ? "−₪" : "₪") + Math.abs(n).toLocaleString("en-US", { minimumFractionDigits: 2, maximumFractionDigits: 2 });
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
  const box = useRef<HTMLDivElement>(null);
  const id = useId();
  const close = useRef(onClose);
  close.current = onClose;
  useEffect(() => {
    const opener = document.activeElement as HTMLElement | null;
    const focusables = () => Array.from(box.current?.querySelectorAll<HTMLElement>(
      'a[href], button:not([disabled]), input:not([disabled]):not([type="hidden"]), select:not([disabled]), textarea:not([disabled]), [tabindex]:not([tabindex="-1"])',
    ) ?? []).filter((el) => el.offsetParent !== null || el === document.activeElement);
    // first field, else the dialog itself
    (focusables().find((el) => el.matches("input, select, textarea")) ?? box.current)?.focus({ preventScroll: true });
    const onKey = (e: KeyboardEvent) => {
      if (e.key === "Escape") { e.stopPropagation(); close.current(); return; }
      if (e.key !== "Tab") return;
      const els = focusables();
      if (!els.length) return;
      const [first, last] = [els[0], els[els.length - 1]];
      if (e.shiftKey && document.activeElement === first) { e.preventDefault(); last.focus(); }
      else if (!e.shiftKey && document.activeElement === last) { e.preventDefault(); first.focus(); }
    };
    window.addEventListener("keydown", onKey);
    return () => { window.removeEventListener("keydown", onKey); opener?.focus?.({ preventScroll: true }); };
  }, []);
  return (
    <div className="modal-bg" onMouseDown={onClose}>
      <div className="modal" ref={box} role="dialog" aria-modal="true" aria-labelledby={id} tabIndex={-1} onMouseDown={(e) => e.stopPropagation()}>
        <div className="card-head">
          <h3 id={id}>{title}</h3>
          <button className="ghost" onClick={onClose} aria-label="Close dialog"><X size={16} strokeWidth={1.75} /></button>
        </div>
        {children}
      </div>
    </div>
  );
}

/** Structural skeleton while data loads; the error, if any, is shown in place. */
export function Loading({ error }: { error?: string | null }) {
  if (error) return <div className="error" role="alert">{error}</div>;
  return <div className="skeleton" aria-busy="true" aria-label="Loading"><i /><i /><i /><i /></div>;
}

/** Empty state: one sentence and, when there is one, the single next action. */
export function Empty({ children, action }: { children: ReactNode; action?: ReactNode }) {
  return <div className="empty"><span>{children}</span>{action}</div>;
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
