import { FormEvent, useState } from "react";
import { Link, useNavigate } from "react-router-dom";
import { api, Partner, Product } from "../api";
import { Loading, Modal, money2, num, Page, useAction, useLoad, useSession } from "../components/ui";

export default function Products() {
  const [q, setQ] = useState("");
  const [creating, setCreating] = useState(false);
  const { can } = useSession();
  const nav = useNavigate();
  const { data, error, reload } = useLoad(() => api.get<Product[]>(`/products${q ? `?q=${encodeURIComponent(q)}` : ""}`), [q]);

  // Enter on an exact barcode/SKU jumps straight to the product (scanner-friendly)
  const scan = async (e: FormEvent) => {
    e.preventDefault();
    try {
      const p = await api.get<Product>(`/products/barcode/${encodeURIComponent(q.trim())}`);
      nav(`/products/${p.id}`);
    } catch { /* not an exact code: keep the filtered list */ }
  };

  return (
    <Page
      title="Products"
      subtitle="The catalogue, with stock at every site."
      actions={can("manager") && <button className="primary" onClick={() => setCreating(true)}>+ New product</button>}
    >
      <form onSubmit={scan} className="toolbar">
        <input aria-label="Search products" placeholder="Search name or SKU, or scan a barcode and press Enter" value={q} onChange={(e) => setQ(e.target.value)} className="grow" />
      </form>
      {!data ? <Loading error={error} /> : (
        <div className="card flush">
          <table>
            <thead>
              <tr><th>SKU</th><th>Name</th><th>Category</th><th>Tracking</th><th className="r">Avg cost</th><th className="r">Price</th><th className="r">On hand</th><th className="r">Available</th><th className="r">Incoming</th></tr>
            </thead>
            <tbody>
              {data.map((p) => (
                <tr key={p.id} className="click" onClick={() => nav(`/products/${p.id}`)}>
                  <td className="mono">{p.sku}</td>
                  <td><Link to={`/products/${p.id}`} onClick={(e) => e.stopPropagation()}>{p.name}</Link></td>
                  <td>{p.category}</td>
                  <td>{p.tracking === "lot" ? <span className="badge s-info">lot + expiry</span> : <span className="faint">none</span>}</td>
                  <td className="r">{money2(p.avg_cost)}</td>
                  <td className="r">{money2(p.sale_price)}</td>
                  <td className="r">{num(p.on_hand ?? 0)}</td>
                  <td className="r"><b>{num(p.available ?? 0)}</b></td>
                  <td className="r muted">{p.incoming ? num(p.incoming) : ""}</td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      )}
      {creating && <NewProduct onClose={() => setCreating(false)} onDone={() => { setCreating(false); reload(); }} />}
    </Page>
  );
}

function NewProduct({ onClose, onDone }: { onClose: () => void; onDone: () => void }) {
  const { data } = useLoad(() => Promise.all([api.get<{ id: number; name: string }[]>("/categories"), api.get<Partner[]>("/partners?kind=supplier")]));
  const [f, setF] = useState({ sku: "", name: "", barcode: "", category_id: "", tracking: "none", sale_price: "0", avg_cost: "0", preferred_supplier_id: "" });
  const { run, busy } = useAction();
  const set = (k: string) => (e: { target: { value: string } }) => setF({ ...f, [k]: e.target.value });

  const submit = (e: FormEvent) => {
    e.preventDefault();
    run(async () => {
      await api.post("/products", {
        ...f, barcode: f.barcode || null, sale_price: +f.sale_price, avg_cost: +f.avg_cost,
        category_id: f.category_id ? +f.category_id : null, preferred_supplier_id: f.preferred_supplier_id ? +f.preferred_supplier_id : null,
      });
      onDone();
    }, `Created ${f.sku}`);
  };

  return (
    <Modal title="New product" onClose={onClose}>
      <form onSubmit={submit} className="form">
        <div className="grid2">
          <label>SKU<input required value={f.sku} onChange={set("sku")} /></label>
          <label>Barcode<input value={f.barcode} onChange={set("barcode")} /></label>
        </div>
        <label>Name<input required value={f.name} onChange={set("name")} /></label>
        <div className="grid2">
          <label>Category
            <select value={f.category_id} onChange={set("category_id")}>
              <option value="">Choose…</option>
              {data?.[0].map((c) => <option key={c.id} value={c.id}>{c.name}</option>)}
            </select>
          </label>
          <label>Preferred supplier
            <select value={f.preferred_supplier_id} onChange={set("preferred_supplier_id")}>
              <option value="">Choose…</option>
              {data?.[1].map((s) => <option key={s.id} value={s.id}>{s.name}</option>)}
            </select>
          </label>
          <label>Tracking
            <select value={f.tracking} onChange={set("tracking")}>
              <option value="none">None</option>
              <option value="lot">Lot + expiry (FEFO)</option>
            </select>
          </label>
          <label>Sale price<input type="number" step="0.01" min="0" value={f.sale_price} onChange={set("sale_price")} /></label>
        </div>
        <button className="primary" disabled={busy}>Create</button>
      </form>
    </Modal>
  );
}
