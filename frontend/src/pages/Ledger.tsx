import { useState } from "react";
import { api, Move } from "../api";
import { Loading, Page, useLoad } from "../components/ui";
import { MoveTable } from "./ProductDetail";

export default function Ledger() {
  const [ref, setRef] = useState("");
  const { data, error } = useLoad(() => api.get<Move[]>(`/stock/moves?limit=300${ref ? `&reference=${encodeURIComponent(ref)}` : ""}`), [ref]);
  return (
    <Page title="Ledger" subtitle="Every unit's path, from one location to another.">
      <div className="toolbar">
        <input aria-label="Filter by reference" className="w-ref" placeholder="Reference, e.g. PO-0012" value={ref} onChange={(e) => setRef(e.target.value.toUpperCase())} />
      </div>
      {!data ? <Loading error={error} /> : <div className="card flush"><MoveTable moves={data} showProduct /></div>}
    </Page>
  );
}
