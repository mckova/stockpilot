import { Link } from "react-router-dom";
import { Area, AreaChart, CartesianGrid, Legend, ResponsiveContainer, Tooltip, XAxis, YAxis } from "recharts";
import { api, Dashboard as D, Product } from "../api";
import { Card, day, Empty, Loading, money, num, Page, useLoad } from "../components/ui";

export default function Dashboard() {
  const { data, error } = useLoad(() => Promise.all([api.get<D>("/dashboard"), api.get<Product[]>("/products")]));
  if (!data) return <Page title="Dashboard"><Loading error={error} /></Page>;
  const [d, products] = data;
  const pname = (id: number) => products.find((p) => p.id === id)?.name ?? `#${id}`;

  return (
    <Page title="Dashboard" subtitle="Live position across the warehouse and stores">
      <div className="kpis">
        <Kpi label="Stock value (AVCO)" value={money(d.stock_value)} />
        <Kpi label="Units on hand" value={num(d.units_on_hand)} hint={`${d.skus_in_stock} SKUs`} />
        <Kpi label="Incoming POs" value={d.open_purchase_orders} link="/purchasing" />
        <Kpi label="Orders to ship" value={d.orders_to_ship} link="/sales" />
        <Kpi label="Reorder alerts" value={d.reorder_alerts} link="/replenishment" tone={d.reorder_alerts ? "warn" : undefined} />
        <Kpi label="Lots expiring ≤30d" value={d.expiring_lots.length} tone={d.expiring_lots.some((l) => l.days_left <= 7) ? "bad" : undefined} />
      </div>

      <Card title="Inbound vs outbound value, last 30 days">
        <div style={{ height: 260 }}>
          <ResponsiveContainer>
            <AreaChart data={d.movement_30d} margin={{ top: 8, right: 12, left: 0, bottom: 0 }}>
              <CartesianGrid strokeDasharray="3 3" stroke="var(--line)" />
              <XAxis dataKey="date" tickFormatter={day} fontSize={11} stroke="var(--muted)" />
              <YAxis fontSize={11} stroke="var(--muted)" tickFormatter={(v) => `₪${Math.round(v / 1000)}k`} />
              <Tooltip formatter={(v: number) => money(v)} labelFormatter={day} />
              <Legend />
              <Area type="monotone" dataKey="inbound" name="Received" stroke="#2563eb" fill="#2563eb33" />
              <Area type="monotone" dataKey="outbound" name="Shipped (at cost)" stroke="#16a34a" fill="#16a34a33" />
            </AreaChart>
          </ResponsiveContainer>
        </div>
      </Card>

      <div className="grid2">
        <Card title="Needs replenishment" extra={<Link to="/replenishment">All →</Link>}>
          {d.reorder_top.length === 0 ? <Empty>Everything is above its minimum.</Empty> : (
            <table>
              <thead><tr><th>Product</th><th>Site</th><th className="r">Projected</th><th className="r">Min</th><th className="r">Suggest</th></tr></thead>
              <tbody>
                {d.reorder_top.map((r) => (
                  <tr key={r.rule_id}>
                    <td><Link to={`/products/${r.product_id}`}>{r.name}</Link></td>
                    <td>{r.site}</td>
                    <td className="r">{num(r.projected)}</td>
                    <td className="r muted">{num(r.min_qty)}</td>
                    <td className="r"><b>{num(r.suggested_qty)}</b> <span className="muted small">{r.route}</span></td>
                  </tr>
                ))}
              </tbody>
            </table>
          )}
        </Card>
        <Card title="Expiring soon (FEFO picks these first)">
          {d.expiring_lots.length === 0 ? <Empty>No lot expires in the next 30 days.</Empty> : (
            <table>
              <thead><tr><th>Lot</th><th>Product</th><th className="r">Qty</th><th className="r">Expires</th></tr></thead>
              <tbody>
                {d.expiring_lots.map((l) => (
                  <tr key={l.lot}>
                    <td className="mono">{l.lot}</td>
                    <td><Link to={`/products/${l.product_id}`}>{pname(l.product_id)}</Link></td>
                    <td className="r">{num(l.quantity)}</td>
                    <td className="r"><span className={`badge ${l.days_left <= 7 ? "s-bad" : "s-warn"}`}>{l.days_left}d</span></td>
                  </tr>
                ))}
              </tbody>
            </table>
          )}
        </Card>
      </div>
    </Page>
  );
}

function Kpi({ label, value, hint, link, tone }: { label: string; value: string | number; hint?: string; link?: string; tone?: string }) {
  const body = (
    <div className={`kpi ${tone ?? ""}`}>
      <div className="muted small">{label}</div>
      <div className="kpi-v">{value}</div>
      {hint && <div className="muted small">{hint}</div>}
    </div>
  );
  return link ? <Link to={link} className="kpi-link">{body}</Link> : body;
}
