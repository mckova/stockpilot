import { useState } from "react";
import { api, Move } from "../api";
import { Loading, Page, useLoad } from "../components/ui";
import { MoveTable } from "./ProductDetail";

export default function Ledger() {
  const [ref, setRef] = useState("");
  const { data, error } = useLoad(() => api.get<Move[]>(`/stock/moves?limit=300${ref ? `&reference=${encodeURIComponent(ref)}` : ""}`), [ref]);
  return (
    <Page title="Stock ledger" subtitle="Append-only, double-entry: every row moves stock from one location to another. Grey = virtual location.">
      <div className="toolbar">
        <input placeholder="Filter by reference, e.g. PO-0012" value={ref} onChange={(e) => setRef(e.target.value.toUpperCase())} />
      </div>
      {!data ? <Loading error={error} /> : <div className="card flush"><MoveTable moves={data} showProduct /></div>}
    </Page>
  );
}
