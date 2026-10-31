import { ArrowLeft } from "lucide-react";
import { Link, useParams } from "react-router-dom";
import { Bar, BarChart, CartesianGrid, ResponsiveContainer, Tooltip, XAxis, YAxis } from "recharts";
import { api, Avail, Insight, Move, Product, Quant, Site } from "../api";
import { Card, dt, Loading, money2, num, Page, useLoad } from "../components/ui";

type Detail = Product & { availability: Avail[]; quants: Quant[]; moves: Move[]; lots: { id: number; code: string; expiry_date: string | null }[] };

export default function ProductDetail() {
  const { id } = useParams();
  const { data, error } = useLoad(
    () => Promise.all([api.get<Detail>(`/products/${id}`), api.get<Site[]>("/sites"), api.get<Insight[]>("/insights")]),
    [id],
  );
  if (!data) return <Page title="Product"><Loading error={error} /></Page>;
  const [p, sites, insights] = data;
  const ins = insights.find((i) => i.product_id === p.id);
  const site = (sid: number) => sites.find((s) => s.id === sid)?.name ?? sid;
  const chart = ins
    ? [
        ...ins.history_90d.slice(-28).map((v, i) => ({ d: `-${28 - i}`, actual: v })),
        ...ins.forecast_14d.map((v, i) => ({ d: `+${i + 1}`, forecast: v })),
      ]
    : [];

  return (
    <Page title={p.name} subtitle={`${p.sku} · ${p.category ?? "uncategorised"} · ${p.tracking === "lot" ? "lot-tracked, FEFO" : "FIFO"}`}
      actions={<>
        <Link to="/products" className="btn ghost"><ArrowLeft size={15} strokeWidth={1.75} aria-hidden="true" /> Products</Link>
        <Link className="btn" to={`/copilot?q=${encodeURIComponent(`Analyse ${p.sku} (${p.name}): stock by site, demand trend, expiry risk and whether its reorder rules fit the forecast. Propose fixes if needed.`)}`}>Ask the planner about this item</Link>
      </>}>
      <div className="kpis">
        <div className="kpi"><div className="muted small">Average cost</div><div className="kpi-v">{money2(p.avg_cost)}</div></div>
        <div className="kpi"><div className="muted small">Sale price</div><div className="kpi-v">{money2(p.sale_price)}</div><div className="muted small">margin {p.sale_price ? Math.round((1 - p.avg_cost / p.sale_price) * 100) : 0}%</div></div>
        {ins && <>
          <div className="kpi"><div className="muted small">Forecast demand / day</div><div className="kpi-v">{num(ins.avg_daily_demand)}</div><div className="muted small">σ {num(ins.demand_sigma)}</div></div>
          <div className="kpi"><div className="muted small">Reorder point</div><div className="kpi-v">{num(ins.reorder_point)}</div><div className="muted small">safety {num(ins.safety_stock)} · LT {ins.lead_time_days}d</div></div>
          <div className="kpi"><div className="muted small">Days of cover</div><div className="kpi-v">{ins.days_of_cover == null ? "∞" : `${ins.days_of_cover} d`}</div><div className="muted small">ABC class {ins.abc}</div></div>
        </>}
      </div>

      <div className="grid2">
        <Card title="By site">
          <table>
            <thead><tr><th>Site</th><th className="r">On hand</th><th className="r">Reserved</th><th className="r">Available</th><th className="r">Incoming</th><th className="r">Projected</th></tr></thead>
            <tbody>
              {p.availability.map((a) => (
                <tr key={a.site_id}><td>{site(a.site_id)}</td><td className="r">{num(a.on_hand)}</td><td className="r">{num(a.reserved)}</td><td className="r"><b>{num(a.available)}</b></td><td className="r">{num(a.incoming)}</td><td className="r">{num(a.projected)}</td></tr>
              ))}
            </tbody>
          </table>
        </Card>
        <Card title="How much sells a day, and what comes next?" extra={<span className="faint small">28 days back, 14 ahead</span>}>
          <div style={{ height: 200 }}>
            <ResponsiveContainer>
              <BarChart data={chart} margin={{ top: 4, right: 4, left: -20, bottom: 0 }}>
                <CartesianGrid stroke="var(--line-soft)" vertical={false} />
                <XAxis dataKey="d" fontSize={10} interval={3} stroke="var(--ink-faint)" tickLine={false} fontFamily="IBM Plex Mono" />
                <YAxis fontSize={10} stroke="var(--ink-faint)" tickLine={false} axisLine={false} fontFamily="IBM Plex Mono" />
                <Tooltip cursor={{ fill: "rgb(23 25 27 / 0.04)" }} contentStyle={{ borderRadius: 3, border: "1px solid var(--line)", fontSize: 12 }} />
                <Bar dataKey="actual" fill="#17191b" name="Shipped" />
                <Bar dataKey="forecast" fill="#b9bdc1" name="Forecast" />
              </BarChart>
            </ResponsiveContainer>
          </div>
        </Card>
      </div>

      <Card title="Stock by location and lot">
        <table>
          <thead><tr><th>Location</th><th>Lot</th><th>Expiry</th><th className="r">Qty</th><th className="r">Reserved</th><th className="r">Value</th></tr></thead>
          <tbody>
            {p.quants.map((q) => (
              <tr key={q.id}><td className="mono">{q.location}</td><td className="mono">{q.lot ?? ""}</td><td>{q.expiry_date ?? ""}</td><td className="r">{num(q.quantity)}</td><td className="r">{q.reserved ? num(q.reserved) : ""}</td><td className="r">{money2(q.value)}</td></tr>
            ))}
          </tbody>
        </table>
      </Card>

      <Card title="Recent ledger entries">
        <MoveTable moves={p.moves} />
      </Card>
    </Page>
  );
}

export function MoveTable({ moves, showProduct }: { moves: Move[]; showProduct?: boolean }) {
  return (
    <table>
      <thead><tr><th>When</th><th>Ref</th>{showProduct && <th>Product</th>}<th>Lot</th><th>From</th><th>To</th><th className="r">Qty</th><th className="r">Unit cost</th><th>By</th></tr></thead>
      <tbody>
        {moves.map((m) => (
          <tr key={m.id}>
            <td className="nowrap">{dt(m.created_at)}</td>
            <td className="mono">{m.reference}</td>
            {showProduct && <td>{m.product}</td>}
            <td className="mono">{m.lot ?? ""}</td>
            <td className={`mono ${m.from_kind !== "internal" ? "virt" : ""}`}>{m.from}</td>
            <td className={`mono ${m.to_kind !== "internal" ? "virt" : ""}`}>{m.to}</td>
            <td className="r">{num(m.quantity)}</td>
            <td className="r">{money2(m.unit_cost)}</td>
            <td className="muted">{m.user ?? ""}</td>
          </tr>
        ))}
      </tbody>
    </table>
  );
}
