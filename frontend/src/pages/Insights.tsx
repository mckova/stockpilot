import { useMemo, useState } from "react";
import { Link } from "react-router-dom";
import { api, Insight, Site } from "../api";
import { Loading, num, Page, Spark, useLoad } from "../components/ui";

const ABC_NOTE = { A: "top 80% of value, count often", B: "next 15%", C: "the long tail" };

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

  if (!data) return <Page title="Demand"><Loading error={error} /></Page>;
  const abc = (["A", "B", "C"] as const).map((k) => ({ name: k, value: data.filter((d) => d.abc === k).length }));
  const atRisk = data.filter((d) => d.risk === "stockout");
  const dead = data.filter((d) => d.dead_stock);
  const lowCover = data.filter((d) => d.days_of_cover != null && d.days_of_cover < 14);

  return (
    <Page title="Demand" subtitle="Forecast, safety stock and slow movers.">
      <div className="toolbar">
        <select aria-label="Site" value={site} onChange={(e) => setSite(e.target.value)}>
          <option value="">Whole network</option>
          {sites.data?.map((s) => <option key={s.id} value={s.id}>{s.name}</option>)}
        </select>
        <div className="grow" />
        <span className="muted small" title="Daily demand from the ledger, smoothed (SES, α 0.3) after a day-of-week index. Safety stock 1.65·σ·√lead time.">How it's computed</span>
        <span className="muted small">Sort</span>
        {(["cover", "abc", "demand"] as const).map((s) => <button key={s} className={`chip ${sort === s ? "on" : ""}`} onClick={() => setSort(s)}>{{ cover: "Cover", abc: "ABC", demand: "Demand" }[s]}</button>)}
      </div>

      <div className="abc-strip" aria-label="ABC classes">
        {abc.map((a) => (
          <div key={a.name} className={`abc abc-${a.name}`} style={{ flexGrow: Math.max(a.value, 1) }}>
            <span className="mono"><b>{a.name}</b> {a.value} SKUs</span>
            <span className="faint small">{ABC_NOTE[a.name]}</span>
          </div>
        ))}
      </div>
      <div className="footnote">
        <span><b>{atRisk.length}</b> at or below reorder point{atRisk.length ? ` (${atRisk.map((a) => a.sku).join(", ")})` : ""}</span>
        <span><b>{lowCover.length}</b> under 14 days of cover</span>
        <span><b>{dead.length}</b> with no sale in 45 days{dead.length ? ` (${dead.map((a) => a.sku).join(", ")})` : ""}</span>
      </div>

      <div className="card flush">
        <table>
          <thead><tr><th>Product</th><th>ABC</th><th>Last 90 days</th><th className="r">Demand/day</th><th className="r">Available</th><th className="r">Reorder pt</th><th className="r">Cover</th><th>Runs out</th><th>Flag</th></tr></thead>
          <tbody>
            {rows.map((r) => (
              <tr key={r.product_id}>
                <td><Link to={`/products/${r.product_id}`}>{r.name}</Link><span className="muted mono small block">{r.sku}</span></td>
                <td><span className={`badge abc-badge abc-${r.abc}`}>{r.abc}</span></td>
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
