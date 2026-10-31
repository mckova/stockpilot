import { FormEvent, useEffect, useRef, useState } from "react";
import { api } from "../api";
import { Card, Empty, num, Page, Status, useAction, useLoad, useSession } from "../components/ui";

type Proposal = {
  id: number; kind: string; status: string; summary: string; rationale: string; result_ref: string | null;
  lines: { sku: string; product: string; qty: number; unit_cost?: number }[];
};
type Step = { tool: string; input: Record<string, unknown>; ok: boolean };
type Msg = { role: "user" | "assistant"; text: string; steps?: Step[]; proposals?: Proposal[] };
type AIStatus = { enabled: boolean; model: string; effort?: string; reason?: string };

const SUGGESTIONS = [
  "Give me a morning brief: what needs my attention today?",
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
  const { toast } = useSession();
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

  const st = status.data;
  return (
    <Page title="Copilot" subtitle={st ? `Claude agent with live access to stock, forecasts and orders · ${st.model}` : "AI operations analyst"}
      actions={conv && <button className="ghost" onClick={() => { setConv(null); setMsgs([]); }}>New conversation</button>}>
      {st && !st.enabled && <div className="error" style={{ marginBottom: 14 }}>AI is off: {st.reason}</div>}
      <div className="grid-copilot">
        <Card>
          <div className="chat">
            {msgs.length === 0 && (
              <div className="suggest">
                <p className="muted">Ask about stock, demand or orders. The copilot reads the same data as the app and can <b>propose</b> purchase orders, transfers and reorder rules; a manager approves them.</p>
                {SUGGESTIONS.map((s) => <button key={s} className="chip-wide" onClick={() => send(s)} disabled={!st?.enabled}>{s}</button>)}
              </div>
            )}
            {msgs.map((m, i) => (
              <div key={i} className={`bubble ${m.role}`}>
                {m.steps && m.steps.length > 0 && (
                  <details className="trace">
                    <summary>{m.steps.length} tool call{m.steps.length > 1 ? "s" : ""}: {[...new Set(m.steps.map((s) => s.tool))].join(", ")}</summary>
                    {m.steps.map((s, j) => <div key={j} className="mono small">{s.ok ? "✓" : "✗"} {s.tool}({JSON.stringify(s.input)})</div>)}
                  </details>
                )}
                <Markdownish text={m.text} />
                {m.proposals?.map((p) => <ProposalCard key={p.id} p={p} onDone={queue.reload} />)}
              </div>
            ))}
            {thinking && <div className="bubble assistant muted">Analysing inventory…</div>}
            <div ref={end} />
          </div>
          <form className="chat-input" onSubmit={submit}>
            <input value={input} onChange={(e) => setInput(e.target.value)} placeholder="Ask the copilot… (Hebrew or English)" disabled={!st?.enabled} />
            <button className="primary" disabled={thinking || !input.trim() || !st?.enabled}>Send</button>
          </form>
        </Card>
        <Card title="Approval queue" extra={<span className="muted small">AI proposes · you decide</span>}>
          {!queue.data?.length ? <Empty>No pending proposals.</Empty> : queue.data.map((p) => <ProposalCard key={p.id} p={p} onDone={queue.reload} />)}
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
  return (
    <div className="proposal">
      <div className="row between"><b>{p.summary}</b><Status value={p.status === "pending" ? "draft" : p.status === "approved" ? "done" : "cancelled"} /></div>
      {p.rationale && <p className="small muted">{p.rationale}</p>}
      {p.lines.length > 0 && <ul className="small">{p.lines.map((l, i) => <li key={i}>{l.sku} × {num(l.qty)}{l.unit_cost != null ? ` @ ₪${l.unit_cost}` : ""}</li>)}</ul>}
      {p.status === "pending" ? (
        <div className="row">
          <button className="primary small" disabled={busy || !can("manager")} title={can("manager") ? "" : "Managers approve"} onClick={() => decide("approve")}>Approve</button>
          <button className="ghost small" disabled={busy || !can("manager")} onClick={() => decide("reject")}>Reject</button>
        </div>
      ) : p.result_ref && <div className="small">Created <span className="mono">{p.result_ref}</span> (draft)</div>}
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
          return <table key={i}><thead><tr>{rows[0].map((c, j) => <th key={j}>{inline(c)}</th>)}</tr></thead><tbody>{rows.slice(1).map((r, k) => <tr key={k}>{r.map((c, j) => <td key={j}>{inline(c)}</td>)}</tr>)}</tbody></table>;
        }
        if (lines.every((l) => /^\s*([-*]|\d+\.)\s/.test(l))) return <ul key={i}>{lines.map((l, j) => <li key={j}>{inline(l.replace(/^\s*([-*]|\d+\.)\s/, ""))}</li>)}</ul>;
        return <p key={i} dir="auto">{lines.map((l, j) => <span key={j}>{inline(l.replace(/^#+\s*/, ""))}{j < lines.length - 1 && <br />}</span>)}</p>;
      })}
    </div>
  );
}
