import { useState } from "react";
import { Link, useNavigate } from "react-router-dom";
import { Bar, BarChart, CartesianGrid, Legend, ResponsiveContainer, Tooltip, XAxis, YAxis } from "recharts";
import { api, Dashboard as D, Product } from "../api";
import { Gauge, KindIcon } from "../components/Gauge";
import { Card, day, Loading, money, num, Page, useAction, useLoad, useSession } from "../components/ui";

type Proposal = { id: number; summary: string; rationale: string };

/** The overview answers one question: what needs a person today. Totals are a footnote. */
export default function Dashboard() {
  const [site, setSite] = useState<number | null>(null);
  const { data, error, reload } = useLoad(
    () => Promise.all([
      api.get<D>(`/dashboard${site ? `?site_id=${site}` : ""}`),
      api.get<Product[]>("/products"),
      api.get<Proposal[]>("/ai/proposals?status=pending").catch(() => [] as Proposal[]),
    ]),
    [site],
  );
  const nav = useNavigate();
  const { can } = useSession();
  const { run, busy } = useAction();
  if (!data) return <Page title="Today"><Loading error={error} /></Page>;
  const [d, products, proposals] = data;
  const pname = (id: number) => products.find((p) => p.id === id)?.name ?? `#${id}`;
  const scope = d.sites.find((s) => s.site_id === site)?.name;
  const brief = scope
    ? `What needs attention at ${scope} today: what is short, what is expiring, what should move or be ordered?`
    : "What needs my attention today?";
  const draft = (ruleId: number, label: string) => run(async () => {
    await api.post("/replenishment/generate", { rule_ids: [ruleId] });
    reload();
  }, `Draft created for ${label}`);
  const urgent = d.expiring_lots.filter((l) => l.days_left <= 14);
  const later = d.expiring_lots.filter((l) => l.days_left > 14);
  // weekly totals answer "more out than in?" better than a noisy daily line
  const n = d.movement_30d.length;
  const weeks = Object.values(d.movement_30d.reduce<Record<number, { week: string; inbound: number; outbound: number; days: number }>>((acc, m, i) => {
    const w = Math.floor((n - 1 - i) / 7); // count back from today so the last bar is a full week
    acc[w] ??= { week: m.date, inbound: 0, outbound: 0, days: 0 };
    acc[w].inbound += m.inbound;
    acc[w].outbound += m.outbound;
    acc[w].days += 1;
    return acc;
  }, {})).filter((w) => w.days === 7).reverse(); // a partial week would read as a slow one
  const count = d.reorder_top.length + urgent.length + proposals.length + (d.orders_to_ship ? 1 : 0);

  return (
    <Page title="Today" subtitle={scope ?? "All sites"}
      actions={<>
        <button onClick={() => nav(`/copilot?q=${encodeURIComponent(brief)}`)}>Ask the planner</button>
        {can("manager") && <button className={d.reorder_alerts ? "signal" : ""} onClick={() => nav("/copilot?planner=1")}>Run the morning review</button>}
      </>}>
      <div className="site-tabs" role="tablist" aria-label="Site">
        <button role="tab" className="site-tab" aria-selected={site === null} onClick={() => setSite(null)}>
          <b>All sites</b>
          <span className="mono">{money(d.sites.reduce((s, x) => s + x.stock_value, 0))}</span>
        </button>
        {d.sites.map((s) => (
          <button key={s.site_id} role="tab" className="site-tab" aria-selected={site === s.site_id} onClick={() => setSite(s.site_id)}>
            <b>{s.name}</b>
            <span className="mono">{money(s.stock_value)}{s.reorder_alerts > 0 && <span className="alerts"> · {s.reorder_alerts} low</span>}</span>
          </button>
        ))}
      </div>

      <div className="footnote" aria-label="Totals">
        <span><b>{money(d.stock_value)}</b> at average cost</span>
        <span><b>{num(d.units_on_hand)}</b> units in <b>{d.skus_in_stock}</b> SKUs</span>
        <span><Link to="/purchasing"><b>{d.open_purchase_orders}</b> purchase orders open</Link></span>
        <span><Link to="/sales"><b>{d.orders_to_ship}</b> {d.orders_to_ship === 1 ? "order" : "orders"} to ship</Link></span>
      </div>

      <div className="split">
        <section className="worklist" aria-labelledby="needs">
          <header>
            <h2 id="needs">Needs a person</h2>
            <span className="faint small">{count} {count === 1 ? "item" : "items"}</span>
          </header>
          {count === 0 && <p className="work-empty muted">Nothing is below its reorder point, nothing expires in the next two weeks, and no proposal is waiting.</p>}
          {proposals.map((p) => (
            <div key={`p${p.id}`} className="work">
              <span className="kind"><KindIcon kind="proposal" />Sign-off</span>
              <span className="what"><b>{p.summary}</b><span className="faint">{p.rationale}</span></span>
              <span />
              <Link className="btn small act" to="/copilot">Review</Link>
            </div>
          ))}
          {d.reorder_top.map((r) => (
            <div key={`r${r.rule_id}`} className="work">
              <span className="kind"><KindIcon kind="low" />Below min</span>
              <span className="what">
                <Link to={`/products/${r.product_id}`}><b>{r.name}</b></Link>
                <span className="faint">{r.site} · {num(r.projected)} projected, reorder at {num(r.min_qty)} · {r.route === "buy" ? `buy ${num(r.suggested_qty)} from ${r.supplier}` : `move ${num(r.suggested_qty)} from ${r.source_site}`}</span>
              </span>
              <Gauge qty={r.projected} min={r.min_qty} max={r.max_qty} />
              {can("manager")
                ? <button className="small act" disabled={busy} onClick={() => draft(r.rule_id, r.name)}>{r.route === "buy" ? "Draft order" : "Draft transfer"}</button>
                : <span className="faint small act">Manager</span>}
            </div>
          ))}
          {urgent.map((l) => (
            <div key={`e${l.lot}`} className="work">
              <span className="kind"><KindIcon kind="expiry" />Expires {l.days_left}d</span>
              <span className="what">
                <Link to={`/products/${l.product_id}`}><b>{pname(l.product_id)}</b></Link>
                <span className="faint">lot <span className="mono">{l.lot}</span> · {num(l.quantity)} units · best before {day(l.expiry_date)}</span>
              </span>
              <span />
              <Link className="btn small act" to={`/copilot?q=${encodeURIComponent(`Lot ${l.lot} of ${pname(l.product_id)} expires in ${l.days_left} days with ${l.quantity} units. Where will it sell fastest, and should we move it?`)}`}>Plan it</Link>
            </div>
          ))}
          {d.orders_to_ship > 0 && (
            <div className="work">
              <span className="kind"><KindIcon kind="ship" />To ship</span>
              <span className="what"><b>{d.orders_to_ship} sales {d.orders_to_ship === 1 ? "order is" : "orders are"} reserved</b><span className="faint">Stock is held; pick lists are ready.</span></span>
              <span />
              <Link className="btn small act" to="/sales">Open</Link>
            </div>
          )}
        </section>

        <div>
          <Card title="Is more leaving than arriving?" extra={<span className="faint small">value at cost, by week</span>}>
            <div style={{ height: 220 }}>
              <ResponsiveContainer>
                <BarChart data={weeks} margin={{ top: 8, right: 4, left: -8, bottom: 0 }} barGap={2} barCategoryGap="28%">
                  <CartesianGrid vertical={false} stroke="var(--line-soft)" />
                  <XAxis dataKey="week" tickFormatter={(v) => `w/c ${day(v)}`} fontSize={11} stroke="var(--ink-faint)" tickLine={false} axisLine={{ stroke: "var(--line)" }} fontFamily="IBM Plex Mono" />
                  <YAxis fontSize={11} stroke="var(--ink-faint)" tickLine={false} axisLine={false} tickFormatter={(v) => `₪${Math.round(v / 1000)}k`} fontFamily="IBM Plex Mono" width={44} />
                  <Tooltip formatter={(v: number) => money(v)} labelFormatter={(v) => `Week from ${day(v)}`} cursor={{ fill: "rgb(23 25 27 / 0.04)" }} contentStyle={{ borderRadius: 3, border: "1px solid var(--line)", fontSize: 12 }} />
                  <Legend iconType="square" wrapperStyle={{ fontSize: 12 }} formatter={(v) => <span style={{ color: "var(--ink-soft)" }}>{v}</span>} />
                  <Bar dataKey="inbound" name="Received" fill="#17191b" radius={[1, 1, 0, 0]} />
                  <Bar dataKey="outbound" name="Shipped" fill="#f0b323" radius={[1, 1, 0, 0]} />
                </BarChart>
              </ResponsiveContainer>
            </div>
          </Card>
          <Card title="Expiring later this month" extra={<span className="faint small">sold first</span>}>
            {later.length === 0 ? <p className="muted small">Nothing else expires in the next 30 days.</p> : (
              <table>
                <thead><tr><th>Lot</th><th>Item</th><th className="r">Units</th><th className="r">Days</th></tr></thead>
                <tbody>
                  {later.map((l) => (
                    <tr key={l.lot}>
                      <td className="mono">{l.lot}</td>
                      <td><Link to={`/products/${l.product_id}`}>{pname(l.product_id)}</Link></td>
                      <td className="r">{num(l.quantity)}</td>
                      <td className={`r ${l.days_left <= 7 ? "neg" : ""}`}>{l.days_left}</td>
                    </tr>
                  ))}
                </tbody>
              </table>
            )}
          </Card>
        </div>
      </div>
    </Page>
  );
}
