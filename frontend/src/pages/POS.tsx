import { FormEvent, useMemo, useRef, useState } from "react";
import { api, Avail, Product, Site, SO } from "../api";
import { Card, Empty, Loading, money2, num, Page, useAction, useLoad } from "../components/ui";

type CartLine = { product: Product; qty: number };

/** Store counter: scan or tap products, check out in one step (stock leaves this store only). */
export default function POS() {
  const sites = useLoad(() => api.get<Site[]>("/sites"));
  const stores = (sites.data ?? []).filter((s) => s.kind === "store");
  const [siteId, setSiteId] = useState<number | null>(null);
  const site = siteId ?? stores[0]?.id ?? null;
  const data = useLoad(
    () => (site ? Promise.all([api.get<Product[]>("/products"), api.get<Avail[]>(`/stock/availability?site_id=${site}`)]) : Promise.resolve(null)),
    [site],
  );
  const [cart, setCart] = useState<CartLine[]>([]);
  const [scan, setScan] = useState("");
  const [receipt, setReceipt] = useState<SO | null>(null);
  const scanRef = useRef<HTMLInputElement>(null);
  const { run, busy } = useAction();

  const avail = useMemo(() => new Map((data.data?.[1] ?? []).map((a) => [a.product_id, a.available])), [data.data]);
  const products = (data.data?.[0] ?? []).filter((p) => (avail.get(p.id) ?? 0) > 0);
  const inCart = (id: number) => cart.find((l) => l.product.id === id)?.qty ?? 0;

  const add = (p: Product, qty = 1) => {
    setReceipt(null);
    setCart((c) => {
      const left = (avail.get(p.id) ?? 0) - inCart(p.id);
      if (left < qty) return c;
      const found = c.find((l) => l.product.id === p.id);
      return found ? c.map((l) => (l.product.id === p.id ? { ...l, qty: l.qty + qty } : l)) : [...c, { product: p, qty }];
    });
  };
  const setQty = (id: number, qty: number) => setCart((c) => (qty <= 0 ? c.filter((l) => l.product.id !== id) : c.map((l) => (l.product.id === id ? { ...l, qty: Math.min(qty, avail.get(id) ?? 0) } : l))));

  const onScan = (e: FormEvent) => {
    e.preventDefault();
    const code = scan.trim();
    if (!code) return;
    run(async () => {
      const p = await api.get<Product>(`/products/barcode/${encodeURIComponent(code)}`);
      if ((avail.get(p.id) ?? 0) - inCart(p.id) <= 0) throw new Error(`${p.name} is out of stock in this store`);
      add(p);
      setScan("");
    });
    scanRef.current?.focus();
  };

  const total = cart.reduce((s, l) => s + l.qty * l.product.sale_price, 0);
  const checkout = () => run(async () => {
    const so = await api.post<SO>("/pos/checkout", { site_id: site, lines: cart.map((l) => ({ product_id: l.product.id, qty: l.qty })) });
    setReceipt(so);
    setCart([]);
    data.reload();
  }, "Sale completed");

  if (!sites.data) return <Page title="Point of sale"><Loading error={sites.error} /></Page>;
  return (
    <Page title="Point of sale" subtitle="Ring up a sale. Oldest expiry leaves first."
      actions={<select aria-label="Store" value={site ?? ""} onChange={(e) => { setSiteId(+e.target.value); setCart([]); }}>{stores.map((s) => <option key={s.id} value={s.id}>{s.name}</option>)}</select>}>
      <div className="grid-pos">
        <div>
          <form onSubmit={onScan} className="toolbar">
            <input ref={scanRef} autoFocus className="grow" placeholder="Barcode or SKU, then Enter" aria-label="Barcode or SKU" value={scan} onChange={(e) => setScan(e.target.value)} />
          </form>
          {!data.data ? <Loading error={data.error} /> : (
            <div className="tiles">
              {products.map((p) => {
                const left = (avail.get(p.id) ?? 0) - inCart(p.id);
                return (
                  <button key={p.id} className="pos-tile" disabled={left <= 0} onClick={() => add(p)}>
                    <b>{p.name}</b>
                    <span className="mono faint small">{p.sku}</span>
                    <span className="foot"><span>{money2(p.sale_price)}</span><span className={left < 5 ? "neg" : "faint"}>{num(left)} on shelf</span></span>
                  </button>
                );
              })}
            </div>
          )}
        </div>
        <Card title="Cart">
          {receipt ? (
            <div className="receipt">
              <div className="row between"><b>Receipt {receipt.number}</b><span className="muted small">{receipt.site}</span></div>
              {receipt.lines.map((l) => <div key={l.id} className="row between small"><span>{num(l.qty)} × {l.product}</span><span>{money2(l.qty * l.unit_price)}</span></div>)}
              <div className="row between total"><span>Total</span><span>{money2(receipt.total)}</span></div>
              <button className="ghost small" onClick={() => setReceipt(null)}>New sale</button>
            </div>
          ) : cart.length === 0 ? <Empty>Scan a barcode or tap a product.</Empty> : (
            <>
              {cart.map((l) => (
                <div key={l.product.id} className="cart-line">
                  <div><b>{l.product.name}</b><div className="muted small">{money2(l.product.sale_price)}</div></div>
                  <div className="row">
                    <button className="ghost small" aria-label={`One less ${l.product.name}`} onClick={() => setQty(l.product.id, l.qty - 1)}>−</button>
                    <span className="w-qty">{num(l.qty)}</span>
                    <button className="ghost small" aria-label={`One more ${l.product.name}`} onClick={() => setQty(l.product.id, l.qty + 1)}>+</button>
                  </div>
                  <div className="r">{money2(l.qty * l.product.sale_price)}</div>
                </div>
              ))}
              <div className="row between total"><span>Total</span><span>{money2(total)}</span></div>
              <button className="primary big-btn" disabled={busy} onClick={checkout}>Charge {money2(total)}</button>
            </>
          )}
        </Card>
      </div>
    </Page>
  );
}
