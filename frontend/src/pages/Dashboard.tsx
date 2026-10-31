import { ChevronRight, Clock, Download, Truck, TriangleAlert } from "lucide-react";
import { useState } from "react";
import { Link, useNavigate } from "react-router-dom";
import { api, Dashboard as D, Product } from "../api";
import { Loading, money, num, day, useAction, useLoad, useSession } from "../components/ui";

type Proposal = { id: number; kind: string; summary: string; rationale: string; lines: { sku: string; product: string; qty: number }[] };

/** Home answers one question: what needs a person today. Totals are secondary. */
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
  const { user, can } = useSession();
  const { run, busy } = useAction();
  if (!data) return <div className="page"><Loading error={error} /></div>;
  const [d, products, proposals] = data;
  const pname = (id: number) => products.find((p) => p.id === id)?.name ?? `#${id}`;
  const scope = d.sites.find((s) => s.site_id === site)?.name;
  const first = user.name.split(" ")[0];
  const hour = new Date().getHours();
  const greeting = hour < 12 ? "Good morning" : hour < 18 ? "Good afternoon" : "Good evening";
  const urgent = d.expiring_lots.filter((l) => l.days_left <= 14);
  const alerts = d.reorder_alerts;
  const plural = (n: number, w: string) => `${n} ${w}${n === 1 ? "" : "s"}`;

  const draft = (ruleIds: number[], label: string) => run(async () => {
    await api.post("/replenishment/generate", { rule_ids: ruleIds });
    reload();
  }, `Draft created for ${label}`);
  const approve = (p: Proposal) => run(async () => {
    await api.post(`/ai/proposals/${p.id}/approve`, {});
    reload();
  }, "Approved: a draft was created");

  const last14 = d.movement_30d.slice(-14);
  const prev14 = d.movement_30d.slice(-28, -14);
  const sum = (xs: typeof last14) => xs.reduce((s, m) => s + m.outbound, 0);
  const sales = sum(last14);
  const delta = prev14.length === 14 && sum(prev14) > 0 ? Math.round((sales / sum(prev14) - 1) * 100) : null;
  const maxOut = Math.max(...last14.map((m) => m.outbound), 1);

  const brief = scope
    ? `What needs attention at ${scope} today: what is short, what is expiring, what should move or be ordered?`
    : "What needs my attention today?";
  const top = d.reorder_top.slice(0, 4);
  const ask = proposals[0];

  const headline = proposals.length > 0
    ? <>{greeting}, {first}. <b>{plural(proposals.length, "suggestion")}</b> from the planner {proposals.length === 1 ? "is" : "are"} waiting for you. <span>{alerts > 0 ? `${plural(alerts, "product")} below the reorder point.` : "Nothing is below its reorder point."}</span></>
    : alerts > 0
      ? <>{greeting}, {first}. <b>{plural(alerts, "product")}</b> {alerts === 1 ? "is" : "are"} below the reorder point. <span>{urgent.length > 0 ? `${plural(urgent.length, "lot")} expire within two weeks.` : "No lot expires within two weeks."}</span></>
      : <>{greeting}, {first}. <b>Stock is in good shape.</b> <span>Nothing needs you right now.</span></>;

  return (
    <div className="page">
      <div className="hello">
        <h1>{headline}</h1>
        <div className="row" style={{ flexWrap: "nowrap" }}>
          <div className="seg glass" role="tablist" aria-label="Site">
            <button role="tab" aria-selected={site === null} onClick={() => setSite(null)}>All sites</button>
            {d.sites.map((s) => <button key={s.site_id} role="tab" aria-selected={site === s.site_id} onClick={() => setSite(s.site_id)}>{s.name.replace(/ (Store|Warehouse)$/, "")}</button>)}
          </div>
          {can("manager") && <button className="primary" onClick={() => nav("/copilot?planner=1")}>Run the morning review</button>}
        </div>
      </div>

      <div className="bento">
        <section className="tile glass ask wide" aria-label="Needs your approval">
          {ask ? (
            <>
              <span className="cap">Planner suggestion{proposals.length > 1 ? `, 1 of ${proposals.length}` : ""}</span>
              <h2>{ask.summary}</h2>
              <p>{ask.rationale}</p>
              <div className="items">
                {ask.lines.slice(0, 4).map((l) => (
                  <div key={l.sku} className="it"><div className="n">{l.product}</div><div className="s">{l.sku}</div><div className="send">{num(l.qty)}</div></div>
                ))}
              </div>
              <div className="acts">
                {can("manager") && <button className="primary" disabled={busy} onClick={() => approve(ask)}>Approve</button>}
                <Link className="btn" to="/copilot">Review in the planner</Link>
              </div>
            </>
          ) : top.length > 0 ? (
            <>
              <span className="cap">Below the reorder point</span>
              <h2>{plural(top.length, "item")} to restock{scope ? ` at ${scope}` : ""}</h2>
              <p>These are under their minimum once incoming orders are counted. Each draft goes to a manager before anything moves.</p>
              <div className="items">
                {top.map((r) => (
                  <div key={r.rule_id} className="it">
                    <div className="n">{r.name}</div>
                    <div className="s"><em>{num(r.projected)} left</em>, reorder at {num(r.min_qty)}</div>
                    <div className="send">{num(r.suggested_qty)}</div>
                  </div>
                ))}
              </div>
              <div className="acts">
                {can("manager") && <button className="primary" disabled={busy} onClick={() => draft(top.map((r) => r.rule_id), "these items")}>Create drafts</button>}
                <Link className="btn" to="/replenishment">Open replenishment</Link>
              </div>
            </>
          ) : (
            <>
              <span className="cap">Planner</span>
              <h2>Nothing is waiting for you</h2>
              <p>No suggestion is open and nothing is below its reorder point. Ask the planner if you want a second look.</p>
              <div className="acts" style={{ marginTop: 24 }}>
                <button onClick={() => nav(`/copilot?q=${encodeURIComponent(brief)}`)}>Ask the planner</button>
              </div>
            </>
          )}
        </section>

        <section className="tile glass" aria-label="Sales">
          <h2>Sales</h2><span className="cap">Last 14 days, shipped at cost</span>
          <Link className="more" to="/sales">Orders <ChevronRight size={14} strokeWidth={2} /></Link>
          <div className="big">{money(sales)}{delta !== null && <small>{delta >= 0 ? "+" : ""}{delta}% on the 14 days before</small>}</div>
          <div className="bars" role="img" aria-label={`Daily shipments, ${money(sales)} in total`}>
            {last14.map((m, i) => (
              <i key={m.date} className={i === last14.length - 1 ? "n" : ""} style={{ height: `${Math.max(6, (m.outbound / maxOut) * 100)}%` }} title={`${day(m.date)}: ${money(m.outbound)}`} />
            ))}
          </div>
          <div className="ax"><span>{day(last14[0]?.date ?? new Date().toISOString())}</span><span>Today</span></div>
        </section>

        <section className="tile glass" aria-label="Stock">
          <h2>Stock</h2><span className="cap">{scope ?? "All sites"}, at average cost</span>
          <Link className="more" to="/stock">Records <ChevronRight size={14} strokeWidth={2} /></Link>
          <div className="big">{money(scope ? d.sites.find((s) => s.site_id === site)!.stock_value : d.stock_value)}</div>
          <div className="meter" aria-hidden="true">
            <i style={{ flex: Math.max(d.skus_in_stock - alerts - urgent.length, 1) }} />
            {alerts > 0 && <i className="l" style={{ flex: alerts }} />}
            {urgent.length > 0 && <i className="e" style={{ flex: urgent.length }} />}
          </div>
          <div className="kv">
            <span><i style={{ background: "var(--pine)" }} />Units on hand</span><b>{num(scope ? d.sites.find((s) => s.site_id === site)!.units : d.units_on_hand)}</b>
            <span><i style={{ background: "#c68a2c" }} />Below reorder point</span><b>{plural(alerts, "product")}</b>
            <span><i style={{ background: "var(--terracotta)" }} />Expiring in 14 days</span><b>{plural(urgent.length, "lot")}</b>
            <span><i style={{ background: "var(--ink-faint)" }} />Open purchase orders</span><b>{d.open_purchase_orders}</b>
          </div>
        </section>

        <section className="tile glass right-wide" aria-label="To do today">
          <h2>To do today</h2>
          <div className="todo-list">
            {d.open_purchase_orders > 0 && (
              <div className="todo-row"><Download size={20} strokeWidth={1.6} />
                <div><div className="ttl">Receive {plural(d.open_purchase_orders, "purchase order")}</div><div className="m">Scan the delivery note to fill the receipt</div></div>
                <Link className="go" to="/purchasing">Open purchasing <ChevronRight size={14} strokeWidth={2} /></Link></div>
            )}
            {d.orders_to_ship > 0 && (
              <div className="todo-row"><Truck size={20} strokeWidth={1.6} />
                <div><div className="ttl">Ship {plural(d.orders_to_ship, "sales order")}</div><div className="m">Stock is reserved and the pick lists are ready</div></div>
                <Link className="go" to="/sales">Pick lists <ChevronRight size={14} strokeWidth={2} /></Link></div>
            )}
            {urgent.map((l) => (
              <div key={l.lot} className="todo-row"><Clock size={20} strokeWidth={1.6} color="var(--terracotta)" />
                <div><div className="ttl">{pname(l.product_id)}, lot {l.lot}, expires in {l.days_left} {l.days_left === 1 ? "day" : "days"}</div><div className="m">{num(l.quantity)} units · best before {day(l.expiry_date)}</div></div>
                <Link className="go" to={`/copilot?q=${encodeURIComponent(`Lot ${l.lot} of ${pname(l.product_id)} expires in ${l.days_left} days with ${l.quantity} units. Where will it sell fastest, and should we move it?`)}`}>Ask the planner <ChevronRight size={14} strokeWidth={2} /></Link></div>
            ))}
            {ask && d.reorder_top.slice(0, 3).map((r) => (
              <div key={r.rule_id} className="todo-row"><TriangleAlert size={20} strokeWidth={1.6} color="var(--ochre)" />
                <div><div className="ttl">{r.name} is low at {r.site}</div><div className="m">{num(r.projected)} projected, reorder at {num(r.min_qty)} · {r.route === "buy" ? `buy ${num(r.suggested_qty)} from ${r.supplier}` : `move ${num(r.suggested_qty)} from ${r.source_site}`}</div></div>
                {can("manager") ? <button className="small" disabled={busy} onClick={() => draft([r.rule_id], r.name)}>{r.route === "buy" ? "Draft order" : "Draft transfer"}</button> : <span />}</div>
            ))}
            {d.open_purchase_orders === 0 && d.orders_to_ship === 0 && urgent.length === 0 && !(ask && d.reorder_top.length) && (
              <p className="todo-empty">Nothing else is open. Counts and demand are under <Link to="/counts">Counts</Link> and <Link to="/insights">Demand</Link>.</p>
            )}
          </div>
        </section>
      </div>
    </div>
  );
}
