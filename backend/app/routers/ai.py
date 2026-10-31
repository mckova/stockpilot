"""AI copilot endpoints: chat with the agent, and the human approval queue."""
from __future__ import annotations

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel, Field
from sqlalchemy import select
from sqlalchemy.orm import Session

from ..ai import agent
from ..ai.tools import approve_proposal, proposal_out
from ..auth import current_user, require
from ..db import get_db
from ..models import AIConversation, AIProposal, Role, User

router = APIRouter(prefix="/api/ai")

# Overridable in tests (app.dependency_overrides) to inject a fake Claude client.
def get_client():
    try:
        return agent.default_client()
    except agent.AIUnavailable as e:
        raise HTTPException(503, str(e))


class ChatIn(BaseModel):
    message: str = Field(min_length=1, max_length=4000)
    conversation_id: int | None = None


@router.get("/status")
def status(_=Depends(current_user)):
    try:
        agent.default_client()
        return {"enabled": True, "model": agent.MODEL, "effort": agent.EFFORT}
    except agent.AIUnavailable as e:
        return {"enabled": False, "model": agent.MODEL, "reason": str(e)}


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
