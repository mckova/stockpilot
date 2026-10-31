import { useState } from "react";
import { api, Count, Loc } from "../api";
import { Card, dt, Empty, Loading, money2, num, Page, Status, useAction, useLoad, useSession } from "../components/ui";

export default function Counts() {
  const [loc, setLoc] = useState("");
  const [openId, setOpenId] = useState<number | null>(null);
  const { can } = useSession();
  const { run, busy } = useAction();
  const { data, error, reload } = useLoad(() => Promise.all([api.get<Count[]>("/counts"), api.get<Loc[]>("/locations")]));
  if (!data) return <Page title="Cycle counts"><Loading error={error} /></Page>;
  const [counts, locs] = data;
  const current = counts.find((c) => c.id === (openId ?? counts.find((x) => x.status === "open")?.id));

  const start = () => run(async () => {
    const c = await api.post<Count>("/counts", { location_id: +loc });
    setOpenId(c.id);
    reload();
  }, "Count started: expected quantities frozen");

  return (
    <Page title="Cycle counts" subtitle="Freeze expected stock, count, review variances, then post adjustments">
      <div className="toolbar">
        <select value={loc} onChange={(e) => setLoc(e.target.value)}>
          <option value="">Choose a location to count…</option>
          {locs.filter((l) => l.kind === "internal").map((l) => <option key={l.id} value={l.id}>{l.full_code} · {l.name}</option>)}
        </select>
        <button className="primary" disabled={!loc || busy} onClick={start}>Start count</button>
      </div>
      <div className="grid-side">
        <Card title="Counts">
          {counts.length === 0 ? <Empty>No counts yet.</Empty> : (
            <ul className="list">
              {counts.map((c) => (
                <li key={c.id} className={current?.id === c.id ? "on" : ""} onClick={() => setOpenId(c.id)}>
                  <span className="mono">{c.number}</span> <span className="mono small muted">{c.location}</span>
                  <Status value={c.status} />
                </li>
              ))}
            </ul>
          )}
        </Card>
        {current ? <CountSheet key={current.id} count={current} canApply={can("manager")} onChange={reload} /> : <Empty>Select or start a count.</Empty>}
      </div>
    </Page>
  );
}

function CountSheet({ count, canApply, onChange }: { count: Count; canApply: boolean; onChange: () => void }) {
  const [vals, setVals] = useState<Record<number, string>>(
    Object.fromEntries(count.lines.map((l) => [l.id, l.counted == null ? "" : String(l.counted)])),
  );
  const { run, busy } = useAction();
  const editable = count.status === "open";
  const save = () => run(async () => {
    const body = Object.entries(vals).filter(([, v]) => v !== "").map(([id, v]) => ({ line_id: +id, counted: +v }));
    await api.put(`/counts/${count.id}`, body);
    onChange();
  }, "Counts saved");
  const apply = () => run(async () => { await api.post(`/counts/${count.id}/apply`); onChange(); }, `${count.number} posted to the ledger`);
  const totalVar = count.lines.reduce((s, l) => s + (l.variance_value ?? 0), 0);

  return (
    <Card title={`${count.number} · ${count.location}`} extra={<span className="muted small">{dt(count.created_at)}</span>}>
      <table>
        <thead><tr><th>Product</th><th>Lot</th><th className="r">Expected</th><th className="r">Counted</th><th className="r">Variance</th><th className="r">Value</th></tr></thead>
        <tbody>
          {count.lines.map((l) => (
            <tr key={l.id}>
              <td>{l.sku}<div className="muted small">{l.product}</div></td>
              <td className="mono">{l.lot ?? ""}</td>
              <td className="r">{num(l.expected)}</td>
              <td className="r">{editable ? <input className="w80" type="number" min="0" step="any" value={vals[l.id]} onChange={(e) => setVals({ ...vals, [l.id]: e.target.value })} /> : l.counted ?? "—"}</td>
              <td className={`r ${l.variance ? (l.variance > 0 ? "pos" : "neg") : ""}`}>{l.variance == null ? "" : (l.variance > 0 ? "+" : "") + num(l.variance)}</td>
              <td className="r">{l.variance_value ? money2(l.variance_value) : ""}</td>
            </tr>
          ))}
        </tbody>
      </table>
      <div className="row between pad-t">
        <span className="muted">Net variance (saved lines): <b className={totalVar < 0 ? "neg" : ""}>{money2(totalVar)}</b></span>
        {editable && <div className="row">
          <button disabled={busy} onClick={save}>Save counts</button>
          <button className="primary" disabled={busy || !canApply} title={canApply ? "" : "Managers approve adjustments"} onClick={apply}>Apply adjustments</button>
        </div>}
      </div>
    </Card>
  );
}
