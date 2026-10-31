import { X } from "lucide-react";
import { Product } from "../api";

export type Line = { product_id: string; qty: string; price: string };
export const blankLine = (): Line => ({ product_id: "", qty: "1", price: "" });

/** Product/qty(/price) rows for creating orders and transfers. */
export function LineEditor({ lines, setLines, products, priceLabel }: {
  lines: Line[]; setLines: (l: Line[]) => void; products: Product[]; priceLabel?: string;
}) {
  const upd = (i: number, k: keyof Line, v: string) => {
    const next = lines.map((l, j) => (j === i ? { ...l, [k]: v } : l));
    if (k === "product_id" && priceLabel) {
      const p = products.find((x) => x.id === +v);
      if (p) next[i].price = String(priceLabel === "Unit cost" ? p.avg_cost.toFixed(2) : p.sale_price);
    }
    setLines(next);
  };
  return (
    <div className="lines">
      {lines.map((l, i) => (
        <div key={i} className="line-row">
          <select required aria-label={`Product, line ${i + 1}`} value={l.product_id} onChange={(e) => upd(i, "product_id", e.target.value)}>
            <option value="">Select product…</option>
            {products.map((p) => <option key={p.id} value={p.id}>{p.sku} · {p.name}</option>)}
          </select>
          <input type="number" min="0.01" step="any" required value={l.qty} onChange={(e) => upd(i, "qty", e.target.value)} placeholder="Qty" aria-label={`Quantity, line ${i + 1}`} />
          {priceLabel && <input type="number" min="0" step="0.01" value={l.price} onChange={(e) => upd(i, "price", e.target.value)} placeholder={priceLabel} aria-label={`${priceLabel}, line ${i + 1}`} />}
          <button type="button" className="ghost" onClick={() => setLines(lines.filter((_, j) => j !== i))} disabled={lines.length === 1} aria-label={`Remove line ${i + 1}`}><X size={15} strokeWidth={1.75} /></button>
        </div>
      ))}
      <button type="button" className="ghost small" onClick={() => setLines([...lines, blankLine()])}>+ Add line</button>
    </div>
  );
}
