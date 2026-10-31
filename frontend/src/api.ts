// Thin typed client over the FastAPI backend.

export type User = { id: number; email: string; name: string; role: "admin" | "manager" | "clerk" };
export type Site = { id: number; code: string; name: string; kind: string; city: string | null };
export type Loc = { id: number; site_id: number | null; parent_id: number | null; code: string; full_code: string; name: string; kind: string };
export type Partner = { id: number; name: string; kind: string; email: string | null; lead_time_days: number };
export type Product = {
  id: number; sku: string; barcode: string | null; name: string; category: string | null; uom: string;
  tracking: "none" | "lot"; avg_cost: number; sale_price: number; preferred_supplier: string | null;
  preferred_supplier_id: number | null; category_id: number | null;
  on_hand?: number; available?: number; incoming?: number;
};
export type Avail = { product_id: number; site_id: number; on_hand: number; reserved: number; available: number; incoming: number; projected: number };
export type Quant = {
  id: number; product_id: number; sku: string; product: string; location_id: number; location: string; site_id: number;
  lot_id: number | null; lot: string | null; expiry_date: string | null; quantity: number; reserved: number; available: number; value: number;
};
export type Move = {
  id: number; created_at: string; sku: string; product: string; lot: string | null; quantity: number; from: string; to: string;
  from_kind: string; to_kind: string; unit_cost: number; reference: string; reason: string | null; user: string | null;
};
export type POLine = { id: number; product_id: number; sku: string; product: string; tracking: string; qty_ordered: number; qty_received: number; unit_cost: number };
export type PO = { id: number; number: string; status: string; supplier: string; site: string; site_id: number; expected_date: string | null; created_at: string; total: number; note: string | null; lines: POLine[] };
export type SOLine = { id: number; sku: string; product: string; qty: number; unit_price: number; reserved: number; picks: { location: string; lot: string | null; qty: number }[] };
export type SO = { id: number; number: string; status: string; customer: string; site: string; created_at: string; total: number; lines: SOLine[] };
export type Transfer = { id: number; number: string; status: string; from_site: string; to_site: string; created_at: string; lines: { id: number; sku: string; product: string; qty: number }[] };
export type Count = {
  id: number; number: string; status: string; location: string; created_at: string;
  lines: { id: number; sku: string; product: string; lot: string | null; expected: number; counted: number | null; variance: number | null; variance_value: number | null }[];
};
export type Suggestion = {
  rule_id: number; product_id: number; sku: string; name: string; site: string; site_id: number; route: "buy" | "transfer";
  source_site: string | null; min_qty: number; max_qty: number; multiple: number; on_hand: number; incoming: number;
  projected: number; suggested_qty: number; supplier: string | null; unit_cost: number; forecast_reorder_point: number | null;
};
export type Insight = {
  product_id: number; sku: string; name: string; abc: "A" | "B" | "C"; available: number; avg_daily_demand: number;
  demand_sigma: number; forecast_14d: number[]; lead_time_days: number; safety_stock: number; reorder_point: number;
  days_of_cover: number | null; stockout_date: string | null; dead_stock: boolean; risk: string; history_90d: number[];
};
export type Dashboard = {
  stock_value: number; units_on_hand: number; skus_in_stock: number; open_purchase_orders: number; orders_to_ship: number;
  reorder_alerts: number; reorder_top: Suggestion[];
  expiring_lots: { lot: string; product_id: number; expiry_date: string; days_left: number; quantity: number }[];
  movement_30d: { date: string; inbound: number; outbound: number }[];
};

const TOKEN_KEY = "stockpilot.token";
export const auth = {
  get token() { return localStorage.getItem(TOKEN_KEY); },
  set(token: string | null) { token ? localStorage.setItem(TOKEN_KEY, token) : localStorage.removeItem(TOKEN_KEY); },
};

export class ApiError extends Error {
  constructor(public status: number, message: string) { super(message); }
}

async function request<T>(method: string, path: string, body?: unknown): Promise<T> {
  const headers: Record<string, string> = { "Content-Type": "application/json" };
  if (auth.token) headers.Authorization = `Bearer ${auth.token}`;
  const res = await fetch(`/api${path}`, { method, headers, body: body === undefined ? undefined : JSON.stringify(body) });
  if (res.status === 401 && !path.startsWith("/auth/login")) {
    auth.set(null);
    window.location.reload();
  }
  const data = res.status === 204 ? null : await res.json().catch(() => null);
  if (!res.ok) {
    const detail = data?.detail;
    const msg = typeof detail === "string" ? detail : Array.isArray(detail) ? detail.map((d: { msg: string }) => d.msg).join("; ") : res.statusText;
    throw new ApiError(res.status, msg);
  }
  return data as T;
}

export const api = {
  get: <T,>(p: string) => request<T>("GET", p),
  post: <T,>(p: string, b?: unknown) => request<T>("POST", p, b ?? {}),
  put: <T,>(p: string, b: unknown) => request<T>("PUT", p, b),
};
