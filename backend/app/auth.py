"""JWT bearer auth with three roles: admin > manager > clerk."""
from __future__ import annotations

import os
from datetime import datetime, timedelta, timezone

import bcrypt
import jwt
from fastapi import Depends, HTTPException, status
from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer
from sqlalchemy.orm import Session

from .db import get_db
from .models import Role, User

SECRET = os.getenv("STOCKPILOT_SECRET", "dev-only-secret-change-me-in-production-0000")
ALGO = "HS256"
TTL_HOURS = 12
RANK = {Role.clerk: 1, Role.manager: 2, Role.admin: 3}

bearer = HTTPBearer(auto_error=False)


def hash_password(pw: str) -> str:
    return bcrypt.hashpw(pw.encode(), bcrypt.gensalt()).decode()


def verify_password(pw: str, hashed: str) -> bool:
    return bcrypt.checkpw(pw.encode(), hashed.encode())


def make_token(user: User) -> str:
    exp = datetime.now(timezone.utc) + timedelta(hours=TTL_HOURS)
    return jwt.encode({"sub": str(user.id), "role": user.role.value, "exp": exp}, SECRET, algorithm=ALGO)


def current_user(
    cred: HTTPAuthorizationCredentials | None = Depends(bearer), db: Session = Depends(get_db)
) -> User:
    if cred is None:
        raise HTTPException(status.HTTP_401_UNAUTHORIZED, "missing bearer token")
    try:
        payload = jwt.decode(cred.credentials, SECRET, algorithms=[ALGO])
    except jwt.PyJWTError:
        raise HTTPException(status.HTTP_401_UNAUTHORIZED, "invalid or expired token")
    user = db.get(User, int(payload["sub"]))
    if user is None:
        raise HTTPException(status.HTTP_401_UNAUTHORIZED, "user no longer exists")
    return user


def require(role: Role):
    def dep(user: User = Depends(current_user)) -> User:
        if RANK[user.role] < RANK[role]:
            raise HTTPException(status.HTTP_403_FORBIDDEN, f"requires role '{role.value}'")
        return user

    return dep
