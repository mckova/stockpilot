import { useMemo, useState } from "react";
import { Link } from "react-router-dom";
import { Cell, Pie, PieChart, ResponsiveContainer, Tooltip } from "recharts";
import { api, Insight, Site } from "../api";
import { Card, Loading, num, Page, Spark, useLoad } from "../components/ui";

const ABC_COLORS = { A: "#2563eb", B: "#0ea5e9", C: "#94a3b8" };

export default function Insights() {
  const [site, setSite] = useState("");
  const [sort, setSort] = useState<"cover" | "abc" | "demand">("cover");
  const sites = useLoad(() => api.get<Site[]>("/sites"));
  const { data, error } = useLoad(() => api.get<Insight[]>(`/insights${site ? `?site_id=${site}` : ""}`), [site]);

  const rows = useMemo(() => {
    const r = [...(data ?? [])];
    if (sort === "cover") r.sort((a, b) => (a.days_of_cover ?? 1e9) - (b.days_of_cover ?? 1e9));
    if (sort === "abc") r.sort((a, b) => a.abc.localeCompare(b.abc) || b.avg_daily_demand - a.avg_daily_demand);
    if (sort === "demand") r.sort((a, b) => b.avg_daily_demand - a.avg_daily_demand);
    return r;
  }, [data, sort]);

  if (!data) return <Page title="Insights"><Loading error={error} /></Page>;
  const abc = (["A", "B", "C"] as const).map((k) => ({ name: k, value: data.filter((d) => d.abc === k).length }));
  const atRisk = data.filter((d) => d.risk === "stockout");
  const dead = data.filter((d) => d.dead_stock);
  const lowCover = data.filter((d) => d.days_of_cover != null && d.days_of_cover < 14);

  return (
    <Page title="Insights" subtitle="Demand forecast (exponential smoothing × weekday seasonality), safety stock at 95% service, ABC and dead stock">
      <div className="toolbar">
        <select value={site} onChange={(e) => setSite(e.target.value)}>
          <option value="">Whole network</option>
          {sites.data?.map((s) => <option key={s.id} value={s.id}>{s.name}</option>)}
        </select>
        <div className="grow" />
        <span className="muted small">sort</span>
        {(["cover", "abc", "demand"] as const).map((s) => <button key={s} className={`chip ${sort === s ? "on" : ""}`} onClick={() => setSort(s)}>{s}</button>)}
      </div>

      <div className="grid3">
        <Card title="ABC by consumption value">
          <div className="row">
            <div style={{ width: 120, height: 120 }}>
              <ResponsiveContainer>
                <PieChart>
                  <Pie data={abc} dataKey="value" innerRadius={32} outerRadius={55} paddingAngle={2}>
                    {abc.map((a) => <Cell key={a.name} fill={ABC_COLORS[a.name]} />)}
                  </Pie>
                  <Tooltip />
                </PieChart>
              </ResponsiveContainer>
            </div>
            <div className="small">
              {abc.map((a) => <div key={a.name}><span className="dot" style={{ background: ABC_COLORS[a.name] }} /> <b>{a.name}</b>: {a.value} SKUs</div>)}
              <p className="muted">A = top 80% of value. Count A items most often.</p>
            </div>
          </div>
        </Card>
        <Card title="Attention">
          <ul className="bullets">
            <li><b>{atRisk.length}</b> SKUs at or below their reorder point{atRisk.length ? `: ${atRisk.map((a) => a.sku).join(", ")}` : ""}</li>
            <li><b>{lowCover.length}</b> SKUs with under 14 days of cover</li>
            <li><b>{dead.length}</b> dead-stock SKUs (no sale in 45+ days){dead.length ? `: ${dead.map((a) => a.sku).join(", ")}` : ""}</li>
          </ul>
        </Card>
        <Card title="How it's computed">
          <p className="small muted">Daily demand is read from the ledger (moves into the customer location). Level = SES (α=0.3) on demand de-seasonalised by a day-of-week index. Safety stock = 1.65·σ·√lead-time; reorder point = demand during lead time + safety stock.</p>
        </Card>
      </div>

      <div className="card flush">
        <table>
          <thead><tr><th>Product</th><th>ABC</th><th>Last 90 days</th><th className="r">Demand/day</th><th className="r">Available</th><th className="r">Reorder pt</th><th className="r">Cover</th><th>Runs out</th><th>Flag</th></tr></thead>
          <tbody>
            {rows.map((r) => (
              <tr key={r.product_id}>
                <td><Link to={`/products/${r.product_id}`}>{r.name}</Link> <span className="muted mono small">{r.sku}</span></td>
                <td><span className="badge" style={{ background: ABC_COLORS[r.abc] + "22", color: ABC_COLORS[r.abc] }}>{r.abc}</span></td>
                <td className="spark-cell"><Spark values={r.history_90d} /></td>
                <td className="r">{num(r.avg_daily_demand)}</td>
                <td className="r">{num(r.available)}</td>
                <td className="r">{num(r.reorder_point)}</td>
                <td className={`r ${r.days_of_cover != null && r.days_of_cover < 14 ? "neg" : ""}`}>{r.days_of_cover == null ? "∞" : `${r.days_of_cover}d`}</td>
                <td>{r.stockout_date ?? ""}</td>
                <td>
                  {r.risk === "stockout" && <span className="badge s-bad">reorder now</span>}
                  {r.risk === "overstock" && <span className="badge s-warn">overstock</span>}
                  {r.dead_stock && <span className="badge s-cancelled">dead stock</span>}
                </td>
              </tr>
            ))}
          </tbody>
        </table>
      </div>
    </Page>
  );
}
