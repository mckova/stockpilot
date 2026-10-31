import { FormEvent, useState } from "react";
import { api, Product, Site, Transfer } from "../api";
import { blankLine, Line, LineEditor } from "../components/LineEditor";
import { dt, Empty, Loading, Modal, num, Page, Status, useAction, useLoad } from "../components/ui";

export default function Transfers() {
  const [creating, setCreating] = useState(false);
  const { run, busy } = useAction();
  const { data, error, reload } = useLoad(() => api.get<Transfer[]>("/transfers"));
  const act = (t: Transfer, verb: string) => run(async () => { await api.post(`/transfers/${t.id}/${verb}`); reload(); }, `${t.number}: ${verb === "dispatch" ? "dispatched" : "received"}`);

  return (
    <Page title="Transfers" subtitle="Warehouse to store. Lots travel with the goods."
      actions={<button className="primary" onClick={() => setCreating(true)}>+ New transfer</button>}>
      {!data ? <Loading error={error} /> : data.length === 0 ? <Empty>No transfers.</Empty> : (
        <div className="card flush">
          <table>
            <thead><tr><th>Number</th><th>From</th><th>To</th><th>Created</th><th>Items</th><th>Status</th><th /></tr></thead>
            <tbody>
              {data.map((t) => (
                <tr key={t.id}>
                  <td className="mono">{t.number}</td>
                  <td>{t.from_site}</td>
                  <td>{t.to_site}</td>
                  <td className="nowrap">{dt(t.created_at)}</td>
                  <td className="small">{t.lines.slice(0, 4).map((l) => `${l.sku} ×${num(l.qty)}`).join(", ")}{t.lines.length > 4 ? ` +${t.lines.length - 4}` : ""}</td>
                  <td><Status value={t.status} /></td>
                  <td className="r nowrap">
                    {t.status === "draft" && <button className="small" disabled={busy} onClick={() => act(t, "dispatch")}>Dispatch</button>}
                    {t.status === "in_transit" && <button className="primary small" disabled={busy} onClick={() => act(t, "receive")}>Receive</button>}
                  </td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      )}
      {creating && <NewTransfer onClose={() => setCreating(false)} onDone={() => { setCreating(false); reload(); }} />}
    </Page>
  );
}

function NewTransfer({ onClose, onDone }: { onClose: () => void; onDone: () => void }) {
  const { data } = useLoad(() => Promise.all([api.get<Site[]>("/sites"), api.get<Product[]>("/products")]));
  const [from, setFrom] = useState("");
  const [to, setTo] = useState("");
  const [lines, setLines] = useState<Line[]>([blankLine()]);
  const { run, busy } = useAction();
  if (!data) return <Modal title="New transfer" onClose={onClose}><Loading /></Modal>;
  const [sites, products] = data;
  const submit = (e: FormEvent) => {
    e.preventDefault();
    run(async () => {
      await api.post("/transfers", { from_site_id: +from, to_site_id: +to, lines: lines.map((l) => ({ product_id: +l.product_id, qty: +l.qty })) });
      onDone();
    }, "Transfer created");
  };
  return (
    <Modal title="New transfer" onClose={onClose}>
      <form className="form" onSubmit={submit}>
        <div className="grid2">
          <label>From<select required value={from} onChange={(e) => setFrom(e.target.value)}><option value="">Choose…</option>{sites.map((s) => <option key={s.id} value={s.id}>{s.name}</option>)}</select></label>
          <label>To<select required value={to} onChange={(e) => setTo(e.target.value)}><option value="">Choose…</option>{sites.filter((s) => String(s.id) !== from).map((s) => <option key={s.id} value={s.id}>{s.name}</option>)}</select></label>
        </div>
        <LineEditor lines={lines} setLines={setLines} products={products} />
        <button className="primary" disabled={busy}>Create draft</button>
      </form>
    </Modal>
  );
}
