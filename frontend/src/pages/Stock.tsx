import { FormEvent, useMemo, useState } from "react";
import { Link } from "react-router-dom";
import { api, Loc, Quant, Site } from "../api";
import { Loading, Modal, money, money2, num, Page, useAction, useLoad } from "../components/ui";

export default function Stock() {
  const [siteId, setSiteId] = useState("");
  const [locId, setLocId] = useState("");
  const [moving, setMoving] = useState<Quant | null>(null);
  const refs = useLoad(() => Promise.all([api.get<Site[]>("/sites"), api.get<Loc[]>("/locations")]));
  const qs = new URLSearchParams();
  if (siteId) qs.set("site_id", siteId);
  if (locId) qs.set("location_id", locId);
  const { data, error, reload } = useLoad(() => api.get<Quant[]>(`/stock/quants?${qs}`), [siteId, locId]);
  const [sites, locs] = refs.data ?? [[], []];
  const internal = locs.filter((l) => l.kind === "internal" && (!siteId || l.site_id === +siteId));
  const total = useMemo(() => (data ?? []).reduce((s, q) => s + q.value, 0), [data]);

  return (
    <Page title="Stock" subtitle="Every quant: product × location × lot">
      <div className="toolbar">
        <select value={siteId} onChange={(e) => { setSiteId(e.target.value); setLocId(""); }}>
          <option value="">All sites</option>
          {sites.map((s) => <option key={s.id} value={s.id}>{s.name}</option>)}
        </select>
        <select value={locId} onChange={(e) => setLocId(e.target.value)}>
          <option value="">All locations</option>
          {internal.map((l) => <option key={l.id} value={l.id}>{l.full_code} · {l.name}</option>)}
        </select>
        <div className="grow" />
        <span className="muted">{data?.length ?? 0} quants · value <b>{money(total)}</b></span>
      </div>
      {!data ? <Loading error={error} /> : (
        <div className="card flush">
          <table>
            <thead><tr><th>Product</th><th>Location</th><th>Lot</th><th>Expiry</th><th className="r">Qty</th><th className="r">Reserved</th><th className="r">Available</th><th className="r">Value</th><th /></tr></thead>
            <tbody>
              {data.map((q) => (
                <tr key={q.id}>
                  <td><Link to={`/products/${q.product_id}`}>{q.product}</Link> <span className="muted mono small">{q.sku}</span></td>
                  <td className="mono">{q.location}</td>
                  <td className="mono">{q.lot ?? ""}</td>
                  <td>{q.expiry_date ?? ""}</td>
                  <td className="r">{num(q.quantity)}</td>
                  <td className="r">{q.reserved ? num(q.reserved) : ""}</td>
                  <td className="r"><b>{num(q.available)}</b></td>
                  <td className="r">{money2(q.value)}</td>
                  <td className="r"><button className="ghost small" disabled={q.available <= 0} onClick={() => setMoving(q)}>Move</button></td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      )}
      {moving && <MoveModal quant={moving} locs={locs} onClose={() => setMoving(null)} onDone={() => { setMoving(null); reload(); }} />}
    </Page>
  );
}

function MoveModal({ quant, locs, onClose, onDone }: { quant: Quant; locs: Loc[]; onClose: () => void; onDone: () => void }) {
  const targets = locs.filter((l) => l.kind === "internal" && l.site_id === quant.site_id && l.id !== quant.location_id);
  const [to, setTo] = useState(String(targets[0]?.id ?? ""));
  const [qty, setQty] = useState(String(quant.available));
  const { run, busy } = useAction();
  const submit = (e: FormEvent) => {
    e.preventDefault();
    run(async () => {
      await api.post("/stock/move", { product_id: quant.product_id, qty: +qty, from_location_id: quant.location_id, to_location_id: +to, lot_id: quant.lot_id });
      onDone();
    }, "Moved");
  };
  return (
    <Modal title={`Move ${quant.product}`} onClose={onClose}>
      <form className="form" onSubmit={submit}>
        <p className="muted">From <span className="mono">{quant.location}</span>{quant.lot && <> · lot <span className="mono">{quant.lot}</span></>} · {num(quant.available)} available</p>
        <label>To location
          <select value={to} onChange={(e) => setTo(e.target.value)}>
            {targets.map((l) => <option key={l.id} value={l.id}>{l.full_code} · {l.name}</option>)}
          </select>
        </label>
        <label>Quantity<input type="number" min="0.01" step="any" max={quant.available} value={qty} onChange={(e) => setQty(e.target.value)} /></label>
        <button className="primary" disabled={busy || !to}>Move stock</button>
      </form>
    </Modal>
  );
}
