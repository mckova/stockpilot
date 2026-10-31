import { FormEvent, Fragment, useState } from "react";
import { api, Loc, Partner, PO, Product, Site } from "../api";
import { blankLine, Line, LineEditor } from "../components/LineEditor";
import { day, Empty, Loading, Modal, money, money2, num, Page, Status, useAction, useLoad, useSession } from "../components/ui";

export default function Purchasing() {
  const [status, setStatus] = useState("");
  const [creating, setCreating] = useState(false);
  const [receiving, setReceiving] = useState<PO | null>(null);
  const [open, setOpen] = useState<number | null>(null);
  const { can } = useSession();
  const { run, busy } = useAction();
  const { data, error, reload } = useLoad(() => api.get<PO[]>(`/purchase-orders${status ? `?status=${status}` : ""}`), [status]);

  const act = (po: PO, verb: string) => run(async () => { await api.post(`/purchase-orders/${po.id}/${verb}`); reload(); }, `${po.number}: ${verb}ed`);

  return (
    <Page title="Purchasing" subtitle="Orders to suppliers and goods in."
      actions={can("manager") && <button className="primary" onClick={() => setCreating(true)}>+ New PO</button>}>
      <div className="toolbar">
        {["", "draft", "confirmed", "partial", "received", "cancelled"].map((s) => (
          <button key={s} className={`chip ${status === s ? "on" : ""}`} onClick={() => setStatus(s)}>{s || "all"}</button>
        ))}
      </div>
      {!data ? <Loading error={error} /> : data.length === 0 ? <Empty>No purchase orders.</Empty> : (
        <div className="card flush">
          <table>
            <thead><tr><th>Number</th><th>Supplier</th><th>Site</th><th>Created</th><th>Expected</th><th className="r">Lines</th><th className="r">Total</th><th>Status</th><th /></tr></thead>
            <tbody>
              {data.map((po) => (<Fragment key={po.id}>
                <tr key={po.id} className="click" onClick={() => setOpen(open === po.id ? null : po.id)}>
                  <td className="mono">{po.number}</td>
                  <td>{po.supplier}</td>
                  <td>{po.site}</td>
                  <td>{day(po.created_at)}</td>
                  <td>{po.expected_date ? day(po.expected_date) : ""}</td>
                  <td className="r">{po.lines.length}</td>
                  <td className="r">{money(po.total)}</td>
                  <td><Status value={po.status} /></td>
                  <td className="r nowrap" onClick={(e) => e.stopPropagation()}>
                    {po.status === "draft" && can("manager") && <>
                      <button className="small" disabled={busy} onClick={() => act(po, "confirm")}>Confirm</button>{" "}
                      <button className="ghost small" disabled={busy} onClick={() => act(po, "cancel")}>Cancel</button>
                    </>}
                    {(po.status === "confirmed" || po.status === "partial") && <button className="primary small" onClick={() => setReceiving(po)}>Receive</button>}
                  </td>
                </tr>
                {open === po.id && (
                  <tr key={`${po.id}-d`} className="detail"><td colSpan={9}>
                    {po.note && <p className="muted small">{po.note}</p>}
                    <table className="inner">
                      <thead><tr><th>Product</th><th className="r">Ordered</th><th className="r">Received</th><th className="r">Unit cost</th></tr></thead>
                      <tbody>{po.lines.map((l) => (
                        <tr key={l.id}><td>{l.sku} · {l.product}</td><td className="r">{num(l.qty_ordered)}</td><td className="r">{num(l.qty_received)}</td><td className="r">{money2(l.unit_cost)}</td></tr>
                      ))}</tbody>
                    </table>
                  </td></tr>
                )}
              </Fragment>))}
            </tbody>
          </table>
        </div>
      )}
      {creating && <NewPO onClose={() => setCreating(false)} onDone={() => { setCreating(false); reload(); }} />}
      {receiving && <Receive po={receiving} onClose={() => setReceiving(null)} onDone={() => { setReceiving(null); reload(); }} />}
    </Page>
  );
}

function NewPO({ onClose, onDone }: { onClose: () => void; onDone: () => void }) {
  const { data } = useLoad(() => Promise.all([api.get<Partner[]>("/partners?kind=supplier"), api.get<Site[]>("/sites"), api.get<Product[]>("/products")]));
  const [supplier, setSupplier] = useState("");
  const [site, setSite] = useState("");
  const [lines, setLines] = useState<Line[]>([blankLine()]);
  const { run, busy } = useAction();
  if (!data) return <Modal title="New purchase order" onClose={onClose}><Loading /></Modal>;
  const [sups, sites, products] = data;
  const submit = (e: FormEvent) => {
    e.preventDefault();
    run(async () => {
      await api.post("/purchase-orders", {
        supplier_id: +supplier, site_id: +site,
        lines: lines.map((l) => ({ product_id: +l.product_id, qty_ordered: +l.qty, unit_cost: +(l.price || 0) })),
      });
      onDone();
    }, "Purchase order created");
  };
  return (
    <Modal title="New purchase order" onClose={onClose}>
      <form className="form" onSubmit={submit}>
        <div className="grid2">
          <label>Supplier<select required value={supplier} onChange={(e) => setSupplier(e.target.value)}><option value="">Choose…</option>{sups.map((s) => <option key={s.id} value={s.id}>{s.name} ({s.lead_time_days}d)</option>)}</select></label>
          <label>Deliver to<select required value={site} onChange={(e) => setSite(e.target.value)}><option value="">Choose…</option>{sites.map((s) => <option key={s.id} value={s.id}>{s.name}</option>)}</select></label>
        </div>
        <LineEditor lines={lines} setLines={setLines} products={products.filter((p) => !supplier || p.preferred_supplier_id === +supplier)} priceLabel="Unit cost" />
        <button className="primary" disabled={busy}>Create draft</button>
      </form>
    </Modal>
  );
}

function Receive({ po, onClose, onDone }: { po: PO; onClose: () => void; onDone: () => void }) {
  const { data: locs } = useLoad(() => api.get<Loc[]>(`/locations?site_id=${po.site_id}`));
  const [rows, setRows] = useState(
    po.lines.map((l) => ({ line_id: l.id, qty: String(l.qty_ordered - l.qty_received), lot_code: "", expiry_date: "", location_id: "" })),
  );
  const { run, busy } = useAction();
  const upd = (i: number, k: string, v: string) => setRows(rows.map((r, j) => (j === i ? { ...r, [k]: v } : r)));
  const [intake, setIntake] = useState<Intake | null>(null);
  const [reading, setReading] = useState(false);
  const { toast } = useSession();
  const readNote = async (file: File | undefined) => {
    if (!file) return;
    const form = new FormData();
    form.append("file", file);
    form.append("po_id", String(po.id));
    setReading(true);
    try {
      const r = await api.upload<Intake>("/ai/intake/receipt", form);
      setIntake(r);
      setRows((cur) => cur.map((row) => {
        const hit = r.receipts.find((x) => x.line_id === row.line_id);
        return hit ? { ...row, qty: String(hit.qty), lot_code: hit.lot_code ?? row.lot_code, expiry_date: hit.expiry_date ?? row.expiry_date }
          : { ...row, qty: "0" };
      }));
      if (r.receipts.length) toast(`Filled ${r.receipts.length} line${r.receipts.length === 1 ? "" : "s"} from the document: check and post`);
      else toast("Nothing on the document matches this order: see the notes above", "err");
    } catch (e) {
      toast((e as Error).message, "err");
    } finally {
      setReading(false);
    }
  };
  const submit = (e: FormEvent) => {
    e.preventDefault();
    const body = rows.filter((r) => +r.qty > 0).map((r) => ({
      line_id: r.line_id, qty: +r.qty, lot_code: r.lot_code || null, expiry_date: r.expiry_date || null,
      location_id: r.location_id ? +r.location_id : null,
    }));
    run(async () => { await api.post(`/purchase-orders/${po.id}/receive`, body); onDone(); }, `${po.number} received`);
  };
  return (
    <Modal title={`Receive ${po.number} · ${po.supplier}`} onClose={onClose}>
      <form className="form" onSubmit={submit}>
        <div className="ai-intake">
          <div className="row between">
            <span className="small"><b>Fill from the delivery note.</b> <span className="muted">Upload a photo or PDF. Claude reads quantities, lots and expiry dates into the rows below; nothing posts until you do.</span></span>
            <label className="btn upload">
              {reading ? "Reading…" : "Upload"}
              <input type="file" accept="image/*,application/pdf" hidden disabled={reading} onChange={(e) => { readNote(e.target.files?.[0]); e.target.value = ""; }} />
            </label>
          </div>
          {intake && <>
            <div className="small muted">Document {intake.document_number || "without number"} from {intake.supplier || "unknown supplier"}{intake.po_number && intake.po_number !== po.number ? ` (looks like ${intake.po_number})` : ""}</div>
            {intake.warnings.length > 0 && <ul className="warn-list">{intake.warnings.map((w, i) => <li key={i}>{w}</li>)}</ul>}
            {intake.unmatched.length > 0 && <div className="small">Not on this PO: {intake.unmatched.map((u) => `${u.description} × ${u.quantity}`).join(", ")}</div>}
          </>}
        </div>
        <table>
          <thead><tr><th>Product</th><th className="r">Open</th><th>Qty</th><th>Put away to</th><th>Lot</th><th>Expiry</th></tr></thead>
          <tbody>
            {po.lines.map((l, i) => {
              const openQty = l.qty_ordered - l.qty_received;
              return (
                <tr key={l.id}>
                  <td>{l.sku}<div className="muted small">{l.product}</div></td>
                  <td className="r">{num(openQty)}</td>
                  <td><input className="w80" type="number" min="0" max={openQty} step="any" aria-label={`Quantity ${l.sku}`} value={rows[i].qty} onChange={(e) => upd(i, "qty", e.target.value)} disabled={openQty <= 0} /></td>
                  <td>
                    <select aria-label={`Put-away location ${l.sku}`} value={rows[i].location_id} onChange={(e) => upd(i, "location_id", e.target.value)}>
                      <option value="">Site default</option>
                      {(locs ?? []).filter((x) => x.kind === "internal").map((x) => <option key={x.id} value={x.id}>{x.full_code}</option>)}
                    </select>
                  </td>
                  <td>{l.tracking === "lot" ? <input className="w120" required={+rows[i].qty > 0} placeholder="Lot code" aria-label={`Lot ${l.sku}`} value={rows[i].lot_code} onChange={(e) => upd(i, "lot_code", e.target.value)} /> : <span className="faint">none</span>}</td>
                  <td>{l.tracking === "lot" ? <input type="date" aria-label={`Expiry ${l.sku}`} value={rows[i].expiry_date} onChange={(e) => upd(i, "expiry_date", e.target.value)} /> : null}</td>
                </tr>
              );
            })}
          </tbody>
        </table>
        <button className="primary" disabled={busy}>Post receipt</button>
      </form>
    </Modal>
  );
}

type Intake = {
  po_id: number | null; po_number: string | null; supplier: string; document_number: string;
  receipts: { line_id: number; sku: string; qty: number; lot_code: string | null; expiry_date: string | null; confidence: number }[];
  unmatched: { description: string; quantity: number; matched_sku: string | null }[];
  warnings: string[];
};
