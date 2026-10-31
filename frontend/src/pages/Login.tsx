import { FormEvent, useEffect, useMemo, useRef, useState } from "react";
import { api, User } from "../api";
import { Mark } from "../components/Mark";
import { Gauge } from "../components/Gauge";
import "./login.css";

/*
  The front page is a live surface: a sample morning at a distributor, computed
  in the browser from the arrays below. Scrolling advances the clock; every
  figure is derived from the step, so scrolling back rewinds it exactly.
*/

const DEMO = [
  ["manager@stockpilot.dev", "manager123", "Manager", "signs off the planner"],
  ["clerk@stockpilot.dev", "clerk123", "Clerk", "receives and sells"],
  ["admin@stockpilot.dev", "admin123", "Admin", "everything"],
] as const;

type Sku = "COF-ESP-1K" | "DRY-MLK-1L" | "DRY-OAT-1L" | "DRY-LAB-250" | "PAN-TAH-500";
type Site = "WH1" | "TLV" | "HFA";
const ITEMS: { sku: Sku; name: string; cost: number }[] = [
  { sku: "COF-ESP-1K", name: "Espresso beans 1kg", cost: 62 },
  { sku: "DRY-MLK-1L", name: "Barista milk 1L", cost: 6.2 },
  { sku: "DRY-OAT-1L", name: "Oat drink 1L", cost: 7.8 },
  { sku: "DRY-LAB-250", name: "Labneh 250g", cost: 7.1 },
  { sku: "PAN-TAH-500", name: "Raw tahini 500g", cost: 12.5 },
];
const SITES: { code: Site; name: string }[] = [
  { code: "WH1", name: "Central warehouse" },
  { code: "TLV", name: "Tel Aviv store" },
  { code: "HFA", name: "Haifa store" },
];
const OPENING: Record<Site, Record<Sku, number>> = {
  WH1: { "COF-ESP-1K": 140, "DRY-MLK-1L": 260, "DRY-OAT-1L": 180, "DRY-LAB-250": 70, "PAN-TAH-500": 210 },
  TLV: { "COF-ESP-1K": 22, "DRY-MLK-1L": 18, "DRY-OAT-1L": 31, "DRY-LAB-250": 6, "PAN-TAH-500": 40 },
  HFA: { "COF-ESP-1K": 35, "DRY-MLK-1L": 52, "DRY-OAT-1L": 40, "DRY-LAB-250": 21, "PAN-TAH-500": 33 },
};
// reorder rules [min, max]; the warehouse buys from Emek Dairy in cases of 12
const RULES: Record<Site, Partial<Record<Sku, [number, number]>>> = {
  TLV: { "COF-ESP-1K": [30, 70], "DRY-MLK-1L": [40, 110], "DRY-OAT-1L": [25, 60], "DRY-LAB-250": [15, 40], "PAN-TAH-500": [20, 50] },
  HFA: { "COF-ESP-1K": [25, 60], "DRY-MLK-1L": [40, 100], "DRY-OAT-1L": [25, 60], "DRY-LAB-250": [15, 40], "PAN-TAH-500": [20, 50] },
  WH1: { "DRY-MLK-1L": [200, 480], "DRY-LAB-250": [60, 160] },
};
const CASE = 12;
// what the driver's paper note says (in the real system the model reads it from a photo)
const NOTE = [
  { sku: "DRY-MLK-1L" as Sku, printed: "Barista milk 1L", qty: 324, cost: 6.4, lot: "B7", expiry: "2026-11-20" },
  { sku: "DRY-LAB-250" as Sku, printed: "Labneh 250g", qty: 132, cost: 7.1, lot: "L9", expiry: "2026-11-16" },
];

const STEPS = [
  { time: "07:40", title: "Opening", body: "A sample morning at a coffee and pantry distributor. Scroll to run it. Every figure on this screen is computed from data in the page." },
  { time: "07:41", title: "Morning review", body: "The planner, Claude, reads what a buyer reads first: stock by site, the reorder rules, open orders and the demand forecast." },
  { time: "07:42", title: "Two proposals", body: "Tel Aviv is short on three lines. Covering it from the warehouse would push milk and labneh under the warehouse's own minimum, so the planner also drafts an order to Emek Dairy." },
  { time: "07:43", title: "Your signature", body: "Nothing moves until a manager approves. Sign the transfer yourself, or keep scrolling and the shift manager will." },
  { time: "10:05", title: "Tel Aviv receives", body: "The van arrives. Lots and expiry dates travel with the goods, so the store sells the oldest stock first." },
  { time: "11:20", title: "Delivery note", body: "Emek's driver hands over a paper note. A photo is enough: Claude reads it and matches it to the order. Two lines don't add up, and it says so." },
  { time: "11:22", title: "Posted", body: "The clerk posts the receipt. The ledger now holds every unit's path from the supplier to the shelf." },
];

type Move = { time: string; ref: string; sku: Sku; qty: number; from: string; to: string; lot?: string };

function simulate(step: number, signedEarly: boolean) {
  const stock = structuredClone(OPENING);
  const transit: Partial<Record<Sku, number>> = {};
  const moves: Move[] = [];
  const short = (Object.entries(RULES.TLV) as [Sku, [number, number]][]).filter(([sku, [min]]) => stock.TLV[sku] < min);
  const transfer = short.map(([sku, [, max]]) => ({ sku, qty: max - stock.TLV[sku] }));
  const order = (Object.entries(RULES.WH1) as [Sku, [number, number]][]).flatMap(([sku, [min, max]]) => {
    const after = stock.WH1[sku] - (transfer.find((t) => t.sku === sku)?.qty ?? 0);
    return after < min ? [{ sku, qty: Math.ceil((max - after) / CASE) * CASE, cost: ITEMS.find((i) => i.sku === sku)!.cost }] : [];
  });
  const signed = step >= 4 || (step === 3 && signedEarly);
  if (signed) {
    for (const t of transfer) { stock.WH1[t.sku] -= t.qty; transit[t.sku] = t.qty; moves.push({ time: "07:43", ref: "TR-0108", sku: t.sku, qty: t.qty, from: "WH1", to: "transit" }); }
  }
  if (step >= 4) {
    for (const t of transfer) { stock.TLV[t.sku] += t.qty; delete transit[t.sku]; moves.push({ time: "10:05", ref: "TR-0108", sku: t.sku, qty: t.qty, from: "transit", to: "TLV" }); }
  }
  const intake = NOTE.map((n) => {
    const line = order.find((o) => o.sku === n.sku);
    const open = line?.qty ?? 0;
    const warnings = [
      ...(n.qty > open ? [`delivered ${n.qty}, ${open} open on PO-0040`] : []),
      ...(line && Math.abs(n.cost - line.cost) > 0.01 ? [`invoiced at ₪${n.cost.toFixed(2)}, ordered at ₪${line.cost.toFixed(2)}`] : []),
    ];
    return { ...n, receive: Math.min(n.qty, open), warnings };
  });
  if (step >= 6) {
    for (const r of intake) { stock.WH1[r.sku] += r.receive; moves.push({ time: "11:22", ref: "PO-0040", sku: r.sku, qty: r.receive, from: "Emek Dairy", to: "WH1", lot: r.lot }); }
  }
  const below = (site: Site, sku: Sku) => { const r = RULES[site][sku]; return r ? stock[site][sku] < r[0] : false; };
  return { stock, transit, moves, short, transfer, order, intake, signed, below };
}

export default function Login({ onLogin }: { onLogin: (token: string, user: User) => void }) {
  const [step, setStep] = useState(0);
  const [signedEarly, setSignedEarly] = useState(false);
  const sim = useMemo(() => simulate(step, signedEarly), [step, signedEarly]);
  const rail = useRef<HTMLDivElement>(null);

  // the clock advances as each stop crosses the middle of the viewport
  useEffect(() => {
    const els = Array.from(rail.current?.querySelectorAll<HTMLElement>("[data-step]") ?? []);
    const io = new IntersectionObserver((entries) => {
      for (const e of entries) if (e.isIntersecting) setStep(Number((e.target as HTMLElement).dataset.step));
    }, { rootMargin: "-50% 0px -50% 0px" });
    els.forEach((el) => io.observe(el));
    return () => io.disconnect();
  }, []);

  const s = STEPS[step];
  return (
    <div className="lp" data-step={step}>
      <header className="lp-bar">
        <span className="lp-word"><Mark /> Stockpilot</span>
        <span className="lp-status faint">Sample data, computed in your browser</span>
        <span className="lp-clock mono">Thu {s.time}</span>
        <a href="#sign-in" className="lp-skip">Sign in</a>
      </header>

      <div className="lp-track">
        <div className="lp-surface">
          <aside className="lp-help">
            <h1>Stock for one warehouse and the stores it feeds, with an AI planner that asks before it acts.</h1>
            <div className="lp-now" aria-live="polite">
              <h2><span className="mono">{s.time}</span> {s.title}</h2>
              <p>{s.body}</p>
            </div>
            <ol className="lp-steps" aria-label="Morning timeline">
              {STEPS.map((x, i) => <li key={x.time} className={i === step ? "on" : i < step ? "done" : ""}><span className="mono">{x.time}</span>{x.title}</li>)}
            </ol>
          </aside>

          <section className="lp-board" aria-label="Stock by site">
            <div className="lp-pane-head"><span className="label">Stock on hand</span><span className="faint small">bar: stock against its reorder rule</span></div>
            <table>
              <thead><tr><th>Item</th>{SITES.map((x) => <th key={x.code} className="r" title={x.name}>{x.code}</th>)}</tr></thead>
              <tbody>
                {ITEMS.map((it) => (
                  <tr key={it.sku}>
                    <td><span className="mono lp-sku">{it.sku}</span><span className="lp-name">{it.name}</span></td>
                    {SITES.map((x) => (
                      <td key={x.code} className={`r ${sim.below(x.code, it.sku) ? "low" : ""}`}>
                        <Num v={sim.stock[x.code][it.sku]} />
                        {RULES[x.code][it.sku] && <Gauge qty={sim.stock[x.code][it.sku]} min={RULES[x.code][it.sku]![0]} max={RULES[x.code][it.sku]![1]} />}
                        {x.code === "TLV" && sim.transit[it.sku] ? <span className="lp-transit">+{sim.transit[it.sku]} on the van</span> : null}
                      </td>
                    ))}
                  </tr>
                ))}
              </tbody>
            </table>
          </section>

          <section className="lp-side" aria-label="Planner">
            <div className="lp-pane-head"><span className="label">{step >= 5 ? "Goods in" : "Planner"}</span><span className="faint small">{step >= 5 ? "WH1 dock 2" : step === 0 ? "idle" : "Claude"}</span></div>
            {step === 0 && <p className="faint small">The planner has not run yet today. It runs when a manager asks, or at 07:40 on weekdays.</p>}
            {step >= 1 && step <= 4 && (
              <div className="lp-log mono">
                <div><b>read</b> dashboard <span>{sim.short.length} lines low at TLV</span></div>
                <div><b>read</b> reorder rules <span>{sim.short.map(([k]) => k).join(", ")}</span></div>
                <div><b>read</b> forecast TLV <span>Friday demand ×1.35</span></div>
                {step >= 2 && <div><b>propose</b> transfer <span>WH1 to TLV, {sim.transfer.length} lines</span></div>}
                {step >= 2 && <div><b>propose</b> purchase order <span>Emek Dairy, {sim.order.length} lines</span></div>}
              </div>
            )}
            {step >= 2 && step <= 4 && (
              <div className={`lp-slip ${sim.signed ? "signed" : ""}`}>
                <div className="row between"><b>Transfer WH1 to TLV</b><span className={`badge ${sim.signed ? "s-done" : "s-pending"}`}>{sim.signed ? "approved" : "needs sign-off"}</span></div>
                <ul>{sim.transfer.map((t) => <li key={t.sku}><span>{t.sku}</span><span>{t.qty}</span></li>)}</ul>
                {step === 3 && !sim.signed && <button className="primary small" onClick={() => setSignedEarly(true)}>Approve transfer</button>}
                {sim.signed && <p className="small muted">Signed by {step === 3 ? "you" : "Eli, shift manager"} at 07:43</p>}
              </div>
            )}
            {step >= 2 && step <= 4 && (
              <div className="lp-slip quiet">
                <div className="row between"><b>Order, Emek Dairy</b><span className="badge s-draft">{step >= 3 ? "PO-0040 sent" : "draft"}</span></div>
                <ul>{sim.order.map((o) => <li key={o.sku}><span>{o.sku}</span><span>{o.qty} @ ₪{o.cost.toFixed(2)}</span></li>)}</ul>
              </div>
            )}
            {step >= 5 && (
              <>
                <figure className="lp-note mono" aria-label="Photo of the delivery note">
                  <b>EMEK DAIRY CO-OP</b>
                  <span>Delivery note 7781 · 31/10</span>
                  {NOTE.map((n) => <span key={n.sku}>{n.printed.padEnd(17, ".")}{String(n.qty).padStart(4)}<br />lot {n.lot} · bb {n.expiry.slice(8)}/{n.expiry.slice(5, 7)} · ₪{n.cost.toFixed(2)}</span>)}
                </figure>
                <div className={`lp-slip ${step >= 6 ? "signed" : ""}`}>
                  <div className="row between"><b>Receipt, PO-0040</b><span className={`badge ${step >= 6 ? "s-done" : "s-pending"}`}>{step >= 6 ? "posted" : "check and post"}</span></div>
                  <ul>{sim.intake.map((r) => <li key={r.sku}><span>{r.sku} · lot {r.lot}</span><span>{r.receive}</span></li>)}</ul>
                  <ul className="warn-list">{sim.intake.flatMap((r) => r.warnings.map((w) => <li key={w}>{r.sku}: {w}</li>))}</ul>
                </div>
              </>
            )}
          </section>

          <section className="lp-ledger" aria-label="Ledger">
            <div className="lp-pane-head"><span className="label">Ledger</span><span className="faint small">{sim.moves.length} moves today, append only</span></div>
            {sim.moves.length === 0 ? <p className="faint small">No stock has moved yet today.</p> : (
              <ol className="mono">
                {sim.moves.slice(-8).map((m, i) => (
                  <li key={`${m.ref}-${m.sku}-${m.to}-${i}`}><span>{m.time}</span><span>{m.ref}</span><span>{m.sku}</span><span className="r">{m.qty}</span><span>{m.from} to {m.to}{m.lot ? `, lot ${m.lot}` : ""}</span></li>
                ))}
              </ol>
            )}
          </section>
        </div>

        <div className="lp-rail" ref={rail} aria-hidden="true">
          {STEPS.map((x, i) => <div key={x.time} data-step={i} className="lp-stop" />)}
        </div>
      </div>

      <SignIn onLogin={onLogin} />
    </div>
  );
}

/** A figure that marks its own change once. */
function Num({ v }: { v: number }) {
  const prev = useRef(v);
  const [flash, setFlash] = useState<"" | "up" | "down">("");
  useEffect(() => {
    if (v === prev.current) return;
    setFlash(v > prev.current ? "up" : "down");
    prev.current = v;
    const t = setTimeout(() => setFlash(""), 900);
    return () => clearTimeout(t);
  }, [v]);
  return <span className={`lp-num ${flash}`}>{v}</span>;
}

/* The close is an input: the first step into the real system. */
function SignIn({ onLogin }: { onLogin: (token: string, user: User) => void }) {
  const [email, setEmail] = useState<string>(DEMO[0][0]);
  const [password, setPassword] = useState<string>(DEMO[0][1]);
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
    <section className="lp-close" id="sign-in">
      <form onSubmit={submit} aria-labelledby="sign-in-title">
        <h2 id="sign-in-title">Open the system this morning came from.</h2>
        <p className="muted">Three sites, ninety days of history and the same planner. Choose who you are.</p>
        <div className="lp-roles" role="radiogroup" aria-label="Demo role">
          {DEMO.map(([e, p, label, what]) => (
            <button type="button" role="radio" key={e} aria-checked={email === e} onClick={() => { setEmail(e); setPassword(p); }}>
              <b>{label}</b>
              <span className="faint small">{what}</span>
            </button>
          ))}
        </div>
        <div className="lp-fields">
          <label>Email<input value={email} onChange={(e) => setEmail(e.target.value)} autoComplete="username" /></label>
          <label>Password<input type="password" value={password} onChange={(e) => setPassword(e.target.value)} autoComplete="current-password" /></label>
          <button className="primary" type="submit" disabled={busy}>{busy ? "Signing in" : "Sign in"}</button>
        </div>
        {error && <p className="error" role="alert">{error}</p>}
      </form>
    </section>
  );
}
