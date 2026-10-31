"""AI copilot endpoints: chat with the agent, and the human approval queue."""
from __future__ import annotations

import os

from fastapi import APIRouter, Depends, File, Form, HTTPException, UploadFile
from pydantic import BaseModel, Field
from sqlalchemy import select
from sqlalchemy.orm import Session

from ..ai import agent, intake
from ..ai.demo import DEMO_MODEL, DemoMessages
from ..ai.tools import approve_proposal, proposal_out
from ..auth import current_user, require
from ..db import get_db
from ..models import AIConversation, AIProposal, Role, User

router = APIRouter(prefix="/api/ai")


def demo_enabled() -> bool:
    return os.getenv("STOCKPILOT_AI_DEMO", "1") != "0"

# Overridable in tests (app.dependency_overrides) to inject a fake Claude client.
def get_client():
    """Claude when a key is set; otherwise the rule-based demo client (unless STOCKPILOT_AI_DEMO=0)."""
    try:
        return agent.default_client()
    except agent.AIUnavailable as e:
        if demo_enabled():
            return DemoMessages()
        raise HTTPException(503, str(e))


class ChatIn(BaseModel):
    message: str = Field(min_length=1, max_length=4000)
    conversation_id: int | None = None


@router.get("/status")
def status(_=Depends(current_user)):
    try:
        agent.default_client()
        return {"enabled": True, "demo": False, "model": agent.MODEL, "effort": agent.EFFORT}
    except agent.AIUnavailable as e:
        if demo_enabled():
            return {"enabled": True, "demo": True, "model": DEMO_MODEL,
                    "reason": "Demo mode: rule-based answers over your live data. Set ANTHROPIC_API_KEY to use Claude."}
        return {"enabled": False, "demo": False, "model": agent.MODEL, "reason": str(e)}


@router.post("/chat")
def chat(body: ChatIn, db: Session = Depends(get_db), user: User = Depends(current_user), client=Depends(get_client)):
    if body.conversation_id:
        conv = db.get(AIConversation, body.conversation_id)
        if conv is None or conv.user_id != user.id:
            raise HTTPException(404, "conversation not found")
    else:
        conv = AIConversation(user_id=user.id)
        db.add(conv)
        db.flush()
    turn = agent.run_turn(db, conv, user, body.message, client)
    db.commit()
    props = [proposal_out(db, db.get(AIProposal, pid)) for pid in turn.proposal_ids]
    return {
        "conversation_id": conv.id, "text": turn.text, "steps": turn.steps, "proposals": props,
        "model": turn.model, "usage": {"input_tokens": conv.input_tokens, "output_tokens": conv.output_tokens},
    }


@router.get("/conversations")
def conversations(db: Session = Depends(get_db), user: User = Depends(current_user)):
    rows = db.scalars(select(AIConversation).where(AIConversation.user_id == user.id).order_by(AIConversation.id.desc()).limit(30))
    return [{"id": c.id, "title": c.title, "created_at": c.created_at.isoformat()} for c in rows]


@router.get("/conversations/{cid}")
def conversation(cid: int, db: Session = Depends(get_db), user: User = Depends(current_user)):
    conv = db.get(AIConversation, cid)
    if conv is None or conv.user_id != user.id:
        raise HTTPException(404, "conversation not found")
    props = db.scalars(select(AIProposal).where(AIProposal.conversation_id == cid)).all()
    return {"id": conv.id, "title": conv.title, "messages": agent.visible_history(conv), "proposals": [proposal_out(db, p) for p in props]}


@router.get("/proposals")
def proposals(status: str | None = "pending", db: Session = Depends(get_db), _=Depends(current_user)):
    stmt = select(AIProposal).order_by(AIProposal.id.desc()).limit(100)
    if status:
        stmt = stmt.where(AIProposal.status == status)
    return [proposal_out(db, p) for p in db.scalars(stmt)]


@router.post("/proposals/{pid}/approve")
def approve(pid: int, db: Session = Depends(get_db), user: User = Depends(require(Role.manager))):
    p = db.get(AIProposal, pid)
    if p is None:
        raise HTTPException(404, "proposal not found")
    out = approve_proposal(db, p, user)
    db.commit()
    return out


@router.post("/proposals/{pid}/reject")
def reject(pid: int, db: Session = Depends(get_db), user: User = Depends(require(Role.manager))):
    p = db.get(AIProposal, pid)
    if p is None:
        raise HTTPException(404, "proposal not found")
    if p.status != "pending":
        raise HTTPException(409, f"proposal is already {p.status}")
    p.status, p.decided_by = "rejected", user.id
    db.commit()
    return proposal_out(db, p)


@router.post("/planner/run")
def run_planner(db: Session = Depends(get_db), user: User = Depends(require(Role.manager)), client=Depends(get_client)):
    """Autonomous review: the agent audits the network and fills the approval queue."""
    conv = AIConversation(user_id=user.id, title="AI planner run")
    db.add(conv)
    db.flush()
    turn = agent.run_turn(db, conv, user, agent.PLANNER_TASK, client)
    db.commit()
    return {
        "conversation_id": conv.id, "text": turn.text, "steps": turn.steps,
        "proposals": [proposal_out(db, db.get(AIProposal, pid)) for pid in turn.proposal_ids],
    }


@router.post("/intake/receipt")
async def intake_receipt(
    file: UploadFile = File(...),
    po_id: int | None = Form(None),
    db: Session = Depends(get_db),
    _: User = Depends(require(Role.clerk)),
    client=Depends(get_client),
):
    """Read a delivery note / invoice and return a receipt pre-filled against the matching PO."""
    data = await file.read()
    extraction = intake.extract(db, client, data, file.content_type or "")
    return {"extraction": extraction, **intake.match_to_po(db, extraction, po_id)}
