import { useState } from "react";
import { Link } from "react-router-dom";
import { api, PO, Suggestion, Transfer } from "../api";
import { Loading, money, num, Page, useAction, useLoad, useSession } from "../components/ui";

export default function Replenishment() {
  const [onlyNeeded, setOnlyNeeded] = useState(true);
  const [picked, setPicked] = useState<Set<number>>(new Set());
  const { can } = useSession();
  const { run, busy } = useAction();
  const { data, error, reload } = useLoad(() => api.get<Suggestion[]>("/replenishment"));
  if (!data) return <Page title="Replenishment"><Loading error={error} /></Page>;
  const rows = data.filter((r) => !onlyNeeded || r.suggested_qty > 0);
  const needed = data.filter((r) => r.suggested_qty > 0);
  const toggle = (id: number) => { const s = new Set(picked); s.has(id) ? s.delete(id) : s.add(id); setPicked(s); };

  const generate = () => run(async () => {
    const out = await api.post<{ purchase_orders: PO[]; transfers: Transfer[] }>("/replenishment/generate", { rule_ids: picked.size ? [...picked] : null });
    setPicked(new Set());
    reload();
    return out;
  }, "Draft purchase orders and transfers created");

  const buyValue = needed.filter((r) => r.route === "buy").reduce((s, r) => s + r.suggested_qty * r.unit_cost, 0);

  return (
    <Page title="Replenishment" subtitle="Min/max reorder rules: when projected stock drops below min, order up to max"
      actions={can("manager") && <button className="primary" disabled={busy || needed.length === 0} onClick={generate}>
        Generate drafts {picked.size ? `(${picked.size})` : `(all ${needed.length})`}
      </button>}>
      <div className="toolbar">
        <label className="check"><input type="checkbox" checked={onlyNeeded} onChange={(e) => setOnlyNeeded(e.target.checked)} /> Only rules that need action</label>
        <div className="grow" />
        <span className="muted">{needed.length} to replenish · purchase value ≈ <b>{money(buyValue)}</b></span>
      </div>
      <div className="card flush">
        <table>
          <thead><tr><th /><th>Product</th><th>Site</th><th>Route</th><th className="r">On hand</th><th className="r">Incoming</th><th className="r">Projected</th><th className="r">Min / Max</th><th className="r">Forecast ROP</th><th className="r">Suggest</th></tr></thead>
          <tbody>
            {rows.map((r) => (
              <tr key={r.rule_id} className={r.suggested_qty > 0 ? "" : "dim"}>
                <td>{r.suggested_qty > 0 && <input type="checkbox" checked={picked.has(r.rule_id)} onChange={() => toggle(r.rule_id)} />}</td>
                <td><Link to={`/products/${r.product_id}`}>{r.name}</Link> <span className="muted mono small">{r.sku}</span></td>
                <td>{r.site}</td>
                <td>{r.route === "buy" ? <span className="badge s-info">buy · {r.supplier}</span> : <span className="badge s-in_transit">from {r.source_site}</span>}</td>
                <td className="r">{num(r.on_hand)}</td>
                <td className="r">{r.incoming ? num(r.incoming) : ""}</td>
                <td className={`r ${r.projected < r.min_qty ? "neg" : ""}`}>{num(r.projected)}</td>
                <td className="r muted">{num(r.min_qty)} / {num(r.max_qty)}{r.multiple > 1 ? ` ×${r.multiple}` : ""}</td>
                <td className="r muted" title="Reorder point from the demand forecast (network-wide)">{r.route === "buy" && r.forecast_reorder_point != null ? num(r.forecast_reorder_point) : ""}</td>
                <td className="r"><b>{r.suggested_qty ? num(r.suggested_qty) : ""}</b></td>
              </tr>
            ))}
          </tbody>
        </table>
      </div>
    </Page>
  );
}
