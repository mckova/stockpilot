import { FormEvent, Fragment, useState } from "react";
import { api, Partner, Product, Site, SO } from "../api";
import { blankLine, Line, LineEditor } from "../components/LineEditor";
import { dt, Empty, Loading, Modal, money, money2, num, Page, Status, useAction, useLoad } from "../components/ui";

export default function Sales() {
  const [status, setStatus] = useState("");
  const [creating, setCreating] = useState(false);
  const [open, setOpen] = useState<number | null>(null);
  const { run, busy } = useAction();
  const { data, error, reload } = useLoad(() => api.get<SO[]>(`/sales-orders${status ? `?status=${status}` : ""}`), [status]);
  const act = (so: SO, verb: string, done: string) =>
    run(async () => { await api.post(`/sales-orders/${so.id}/${verb}`); reload(); setOpen(so.id); }, `${so.number} ${done}`);

  return (
    <Page title="Sales orders" subtitle="Reserved before they ship, oldest stock first."
      actions={<button className="primary" onClick={() => setCreating(true)}>+ New order</button>}>
      <div className="toolbar">
        {["", "draft", "reserved", "shipped", "cancelled"].map((s) => (
          <button key={s} className={`chip ${status === s ? "on" : ""}`} onClick={() => setStatus(s)}>{s || "all"}</button>
        ))}
      </div>
      {!data ? <Loading error={error} /> : data.length === 0 ? <Empty>No orders.</Empty> : (
        <div className="card flush">
          <table>
            <thead><tr><th>Number</th><th>Customer</th><th>Site</th><th>Created</th><th className="r">Lines</th><th className="r">Total</th><th>Status</th><th /></tr></thead>
            <tbody>
              {data.slice(0, 150).map((so) => (<Fragment key={so.id}>
                <tr key={so.id} className="click" onClick={() => setOpen(open === so.id ? null : so.id)}>
                  <td className="mono">{so.number}</td>
                  <td>{so.customer}</td>
                  <td>{so.site}</td>
                  <td className="nowrap">{dt(so.created_at)}</td>
                  <td className="r">{so.lines.length}</td>
                  <td className="r">{money(so.total)}</td>
                  <td><Status value={so.status} /></td>
                  <td className="r nowrap" onClick={(e) => e.stopPropagation()}>
                    {so.status === "draft" && <button className="small" disabled={busy} onClick={() => act(so, "reserve", "reserved")}>Reserve</button>}{" "}
                    {so.status === "reserved" && <button className="primary small" disabled={busy} onClick={() => act(so, "ship", "shipped")}>Ship</button>}{" "}
                    {(so.status === "draft" || so.status === "reserved") && <button className="ghost small" disabled={busy} onClick={() => act(so, "cancel", "cancelled")}>Cancel</button>}
                  </td>
                </tr>
                {open === so.id && (
                  <tr key={`${so.id}-d`} className="detail"><td colSpan={8}>
                    <table className="inner">
                      <thead><tr><th>Product</th><th className="r">Qty</th><th className="r">Price</th><th className="r">Reserved</th><th>Pick list</th></tr></thead>
                      <tbody>{so.lines.map((l) => (
                        <tr key={l.id}>
                          <td>{l.sku} · {l.product}</td><td className="r">{num(l.qty)}</td><td className="r">{money2(l.unit_price)}</td>
                          <td className="r">{l.reserved ? num(l.reserved) : ""}</td>
                          <td>{l.picks.map((p, i) => <span key={i} className="pick mono">{p.location}{p.lot ? ` · ${p.lot}` : ""} × {num(p.qty)}</span>)}</td>
                        </tr>
                      ))}</tbody>
                    </table>
                  </td></tr>
                )}
              </Fragment>))}
            </tbody>
          </table>
        </div>
      )}
      {creating && <NewSO onClose={() => setCreating(false)} onDone={() => { setCreating(false); setStatus(""); reload(); }} />}
    </Page>
  );
}

function NewSO({ onClose, onDone }: { onClose: () => void; onDone: () => void }) {
  const { data } = useLoad(() => Promise.all([api.get<Partner[]>("/partners?kind=customer"), api.get<Site[]>("/sites"), api.get<Product[]>("/products")]));
  const [customer, setCustomer] = useState("");
  const [site, setSite] = useState("");
  const [lines, setLines] = useState<Line[]>([blankLine()]);
  const { run, busy } = useAction();
  if (!data) return <Modal title="New sales order" onClose={onClose}><Loading /></Modal>;
  const [custs, sites, products] = data;
  const submit = (e: FormEvent) => {
    e.preventDefault();
    run(async () => {
      await api.post("/sales-orders", {
        customer_id: +customer, site_id: +site,
        lines: lines.map((l) => ({ product_id: +l.product_id, qty: +l.qty, unit_price: l.price === "" ? null : +l.price })),
      });
      onDone();
    }, "Order created");
  };
  return (
    <Modal title="New sales order" onClose={onClose}>
      <form className="form" onSubmit={submit}>
        <div className="grid2">
          <label>Customer<select required value={customer} onChange={(e) => setCustomer(e.target.value)}><option value="">Choose…</option>{custs.map((c) => <option key={c.id} value={c.id}>{c.name}</option>)}</select></label>
          <label>Ship from<select required value={site} onChange={(e) => setSite(e.target.value)}><option value="">Choose…</option>{sites.map((s) => <option key={s.id} value={s.id}>{s.name}</option>)}</select></label>
        </div>
        <LineEditor lines={lines} setLines={setLines} products={products} priceLabel="Unit price" />
        <button className="primary" disabled={busy}>Create draft</button>
      </form>
    </Modal>
  );
}
