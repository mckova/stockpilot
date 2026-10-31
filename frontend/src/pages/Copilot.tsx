import { FormEvent, useEffect, useRef, useState } from "react";
import { useSearchParams } from "react-router-dom";
import { api } from "../api";
import { Card, Empty, num, Page, useAction, useLoad, useSession } from "../components/ui";

type Proposal = {
  id: number; kind: string; status: string; summary: string; rationale: string; result_ref: string | null;
  lines: { sku: string; product: string; qty: number; unit_cost?: number }[];
};
type Step = { tool: string; input: Record<string, unknown>; ok: boolean };
type Msg = { role: "user" | "assistant"; text: string; steps?: Step[]; proposals?: Proposal[] };
type AIStatus = { enabled: boolean; model: string; effort?: string; reason?: string };

const SUGGESTIONS = [
  "What needs my attention today?",
  "What should we reorder this week, and from whom? Propose the purchase orders.",
  "Which short-dated lots are at risk of expiring before they sell? Suggest a plan.",
  "Are any reorder rules out of line with the demand forecast? Propose fixes.",
  "מה מצב המלאי בסניף תל אביב ומה חסר שם?",
];

export default function Copilot() {
  const status = useLoad(() => api.get<AIStatus>("/ai/status"));
  const queue = useLoad(() => api.get<Proposal[]>("/ai/proposals?status=pending"));
  const [msgs, setMsgs] = useState<Msg[]>([]);
  const [conv, setConv] = useState<number | null>(null);
  const [input, setInput] = useState("");
  const [thinking, setThinking] = useState(false);
  const { toast, can, user } = useSession();
  const end = useRef<HTMLDivElement>(null);
  useEffect(() => { end.current?.scrollIntoView({ behavior: "smooth" }); }, [msgs, thinking]);

  const send = async (text: string) => {
    if (!text.trim() || thinking) return;
    setMsgs((m) => [...m, { role: "user", text }]);
    setInput("");
    setThinking(true);
    try {
      const r = await api.post<{ conversation_id: number; text: string; steps: Step[]; proposals: Proposal[] }>("/ai/chat", { message: text, conversation_id: conv });
      setConv(r.conversation_id);
      setMsgs((m) => [...m, { role: "assistant", text: r.text, steps: r.steps, proposals: r.proposals }]);
      if (r.proposals.length) queue.reload();
    } catch (e) {
      toast((e as Error).message, "err");
      setMsgs((m) => m.slice(0, -1));
      setInput(text);
    } finally {
      setThinking(false);
    }
  };
  const submit = (e: FormEvent) => { e.preventDefault(); send(input); };

  const runPlanner = async () => {
    if (thinking) return;
    setMsgs((m) => [...m, { role: "user", text: "Run the daily replenishment and stock-health review for the whole network." }]);
    setThinking(true);
    try {
      const r = await api.post<{ conversation_id: number; text: string; steps: Step[]; proposals: Proposal[] }>("/ai/planner/run");
      setConv(r.conversation_id);
      setMsgs((m) => [...m, { role: "assistant", text: r.text, steps: r.steps, proposals: r.proposals }]);
      queue.reload();
    } catch (e) {
      toast((e as Error).message, "err");
      setMsgs((m) => m.slice(0, -1));
    } finally {
      setThinking(false);
    }
  };

  // Deep links from other screens: /copilot?q=... asks a question, /copilot?planner=1 runs the planner.
  const [params, setParams] = useSearchParams();
  const started = useRef(false);
  useEffect(() => {
    if (started.current || !status.data?.enabled) return;
    const q = params.get("q");
    if (!q && !params.get("planner")) return;
    started.current = true;
    setParams({}, { replace: true });
    if (q) send(q); else runPlanner();
  }, [status.data]); // eslint-disable-line react-hooks/exhaustive-deps

  const st = status.data;
  const reset = () => { setConv(null); setMsgs([]); };
  return (
    <Page title="Planner" subtitle="Claude reads your stock and proposes. Managers sign off."
      actions={<>
        {conv && <button className="ghost" onClick={reset}>New conversation</button>}
        {can("manager") && <button className="primary" disabled={thinking || !st?.enabled} onClick={() => { reset(); runPlanner(); }}>Run the morning review</button>}
      </>}>
      {st && !st.enabled && <div className="error" style={{ marginBottom: 14 }}>The planner is offline: {st.reason}</div>}
      <div className="grid-copilot">
        <Card>
          <div className="chat" aria-live="polite">
            {msgs.length === 0 && (
              <div className="suggest">
                <p className="muted">Ask in Hebrew or English. Answers cite the numbers they come from, and anything that would change stock arrives as a proposal in the queue on the right.</p>
                {SUGGESTIONS.map((s) => <button key={s} className="chip-wide" dir="auto" onClick={() => send(s)} disabled={!st?.enabled}>{s}</button>)}
              </div>
            )}
            {msgs.map((m, i) => (
              <div key={i} className={`turn ${m.role}`}>
                <div className="who label">{m.role === "user" ? user.name.split(" ")[0] : "Planner"}</div>
                <div className="body">
                  {m.steps && m.steps.length > 0 && (
                    <details className="trace">
                      <summary>Looked at {[...new Set(m.steps.map((s) => s.tool.replace(/_/g, " ")))].join(", ")}</summary>
                      {m.steps.map((s, j) => <div key={j} className="mono">{s.ok ? "ok " : "err"} {s.tool}({JSON.stringify(s.input)})</div>)}
                    </details>
                  )}
                  {m.role === "user" ? <p dir="auto">{m.text}</p> : <Markdownish text={m.text} />}
                  {m.proposals?.map((p) => <ProposalCard key={p.id} p={p} onDone={queue.reload} />)}
                </div>
              </div>
            ))}
            {thinking && (
              <div className="turn assistant">
                <div className="who label">Planner</div>
                <Working />
              </div>
            )}
            <div ref={end} />
          </div>
          <form className="chat-input" onSubmit={submit}>
            <input value={input} onChange={(e) => setInput(e.target.value)} placeholder="What should we reorder for Haifa this week?" aria-label="Message to the planner" dir="auto" disabled={!st?.enabled} />
            <button className="primary" disabled={thinking || !input.trim() || !st?.enabled}>Ask</button>
          </form>
        </Card>
        <Card title="Waiting for sign-off" extra={<span className="faint small">{queue.data?.length ?? 0} open</span>}>
          {!queue.data?.length ? <Empty>Nothing waiting. Proposals from the planner land here.</Empty> : queue.data.map((p) => <ProposalCard key={p.id} p={p} onDone={queue.reload} />)}
        </Card>
      </div>
    </Page>
  );
}

function ProposalCard({ p: initial, onDone }: { p: Proposal; onDone: () => void }) {
  const [p, setP] = useState(initial);
  const { can } = useSession();
  const { run, busy } = useAction();
  const decide = (verb: "approve" | "reject") => run(async () => {
    setP(await api.post<Proposal>(`/ai/proposals/${p.id}/${verb}`));
    onDone();
  }, verb === "approve" ? "Approved: draft created" : "Rejected");
  const tone = p.status === "approved" ? "done" : p.status === "rejected" ? "rejected" : "";
  return (
    <div className={`proposal ${tone}`}>
      <div className="row between"><b>{p.summary}</b><span className={`badge ${p.status === "pending" ? "s-pending" : p.status === "approved" ? "s-done" : "s-cancelled"}`}>{p.status === "pending" ? "needs sign-off" : p.status}</span></div>
      {p.rationale && <p className="small muted">{p.rationale}</p>}
      {p.lines.length > 0 && <ul>{p.lines.map((l, i) => <li key={i}><span>{l.sku}</span><span>{num(l.qty)}{l.unit_cost != null ? ` @ ₪${l.unit_cost}` : ""}</span></li>)}</ul>}
      {p.status === "pending" ? (
        <div className="row">
          <button className="primary small" disabled={busy || !can("manager")} onClick={() => decide("approve")}>Approve</button>
          <button className="ghost small" disabled={busy || !can("manager")} onClick={() => decide("reject")}>Reject</button>
          {!can("manager") && <span className="faint small">A manager signs off</span>}
        </div>
      ) : p.result_ref && <div className="small">Created <span className="mono">{p.result_ref}</span> as a draft</div>}
    </div>
  );
}

/** Minimal, safe rendering: paragraphs, bullets, **bold**, and pipe tables. No HTML injection. */
function Markdownish({ text }: { text: string }) {
  const blocks = text.split(/\n{2,}/);
  const inline = (s: string) => s.split(/(\*\*[^*]+\*\*)/g).map((part, i) => part.startsWith("**") ? <b key={i}>{part.slice(2, -2)}</b> : part);
  return (
    <div className="md">
      {blocks.map((b, i) => {
        const lines = b.split("\n");
        if (lines.length > 1 && lines.every((l) => l.trim().startsWith("|"))) {
          const rows = lines.filter((l) => !/^\s*\|[\s:|-]+\|\s*$/.test(l)).map((l) => l.trim().replace(/^\||\|$/g, "").split("|").map((c) => c.trim()));
          const body = rows.slice(1);
          const numeric = rows[0].map((_, j) => body.length > 0 && body.every((r) => /^[-−+]?[₪$]?[\d,.]+%?$/.test((r[j] ?? "").trim())));
          const code = rows[0].map((_, j) => body.length > 0 && body.every((r) => /^[A-Z0-9]+(-[A-Z0-9]+)+$/.test((r[j] ?? "").trim())));
          const cls = (j: number) => (numeric[j] ? "r" : code[j] ? "mono" : undefined);
          return <table key={i}><thead><tr>{rows[0].map((c, j) => <th key={j} className={cls(j)}>{inline(c)}</th>)}</tr></thead><tbody>{body.map((r, k) => <tr key={k}>{r.map((c, j) => <td key={j} className={cls(j)}>{inline(c)}</td>)}</tr>)}</tbody></table>;
        }
        if (lines.every((l) => /^\s*([-*]|\d+\.)\s/.test(l))) return <ul key={i}>{lines.map((l, j) => <li key={j}>{inline(l.replace(/^\s*([-*]|\d+\.)\s/, ""))}</li>)}</ul>;
        return <p key={i} dir="auto">{lines.map((l, j) => <span key={j}>{inline(l.replace(/^#+\s*/, ""))}{j < lines.length - 1 && <br />}</span>)}</p>;
      })}
    </div>
  );
}

/** One live status line, in words, with an honest elapsed time. */
function Working() {
  const [t, setT] = useState(0);
  useEffect(() => { const id = setInterval(() => setT((x) => x + 1), 1000); return () => clearInterval(id); }, []);
  const line = t < 4 ? "Reading stock and reorder rules" : t < 10 ? "Checking forecasts and open orders" : "Writing it up";
  return (
    <div className="working" role="status">
      {line}<span className="mono">0:{String(t).padStart(2, "0")}</span>
      {t >= 30 && <span className="faint small">This is taking longer than usual.</span>}
    </div>
  );
}
