/** Bin gauge: quantity against a min/max rule, drawn like the fill line on a shelf label. */
export function Gauge({ qty, min, max, label }: { qty: number; min: number; max: number; label?: string }) {
  const top = Math.max(max * 1.15, qty, 1);
  const pct = (v: number) => `${Math.min(100, (Math.max(v, 0) / top) * 100)}%`;
  return (
    <span className={`gauge ${qty < min ? "low" : ""}`} role="img" aria-label={label ?? `${qty} on hand, reorder at ${min}, fill to ${max}`}>
      <span className="fill" style={{ width: pct(qty) }} />
      <span className="min" style={{ left: pct(min) }} />
      <span className="max" style={{ left: pct(max) }} />
    </span>
  );
}

/** Status shapes so colour never carries meaning alone. */
export function KindIcon({ kind }: { kind: "low" | "expiry" | "proposal" | "ship" | "receive" }) {
  const c = { low: "#c98f05", expiry: "#b3261e", proposal: "#17191b", ship: "#50565c", receive: "#50565c" }[kind];
  return (
    <svg width="12" height="12" viewBox="0 0 12 12" aria-hidden="true">
      {kind === "low" && <path d="M6 1 11 10H1Z" fill={c} />}
      {kind === "expiry" && <><circle cx="6" cy="6" r="5" fill="none" stroke={c} strokeWidth="1.5" /><path d="M6 3v3.2l2 1.3" stroke={c} strokeWidth="1.5" fill="none" /></>}
      {kind === "proposal" && <rect x="1.5" y="1.5" width="9" height="9" fill="none" stroke={c} strokeWidth="1.5" />}
      {kind === "ship" && <path d="M1 6h8M6 2.5 9.5 6 6 9.5" stroke={c} strokeWidth="1.5" fill="none" />}
      {kind === "receive" && <path d="M11 6H3M6 2.5 2.5 6 6 9.5" stroke={c} strokeWidth="1.5" fill="none" />}
    </svg>
  );
}
