"""Invite codes + beta accounts + beta sessions persistence."""

from __future__ import annotations

import logging
import secrets
import string
import threading
import uuid
from dataclasses import dataclass, field
from datetime import datetime, timedelta, timezone
from typing import Optional

from backend.database import SessionLocal, engine
from backend.orm_models import BetaAccountRow, BetaSessionRow, InviteCodeRow

logger = logging.getLogger(__name__)

SESSION_TTL = timedelta(hours=3)
COOKIE_NAME = "nesto_session"


def utcnow() -> datetime:
    return datetime.now(timezone.utc)


def generate_invite_code() -> str:
    chars = string.ascii_uppercase + string.digits
    body = "".join(secrets.choice(chars) for _ in range(8))
    return f"NESTO-{body}"


def new_token() -> str:
    return secrets.token_urlsafe(32)


def new_id(prefix: str = "") -> str:
    return f"{prefix}{uuid.uuid4().hex[:12]}"


@dataclass
class InviteCode:
    id: str
    code: str
    status: str = "active"  # active | used | expired
    used_by: Optional[str] = None
    device_id: Optional[str] = None
    created_at: datetime = field(default_factory=utcnow)
    activated_at: Optional[datetime] = None
    expires_at: Optional[datetime] = None


@dataclass
class BetaAccount:
    """Durable beta identity — one invite code → one account (no email)."""

    id: str
    invite_code_id: str
    invite_code: str
    user_token: str
    device_id: Optional[str] = None
    status: str = "active"  # active | revoked
    revoked_at: Optional[datetime] = None
    created_at: datetime = field(default_factory=utcnow)
    expires_at: Optional[datetime] = None


@dataclass
class BetaSession:
    id: str
    invite_code: str
    token: str
    device_id: Optional[str] = None
    beta_account_id: Optional[str] = None
    heartbeat_at: Optional[datetime] = None
    current_page: Optional[str] = None
    current_project: Optional[str] = None
    current_stage: Optional[str] = None
    user_agent: Optional[str] = None
    client_ip: Optional[str] = None
    read_only: bool = False
    created_at: datetime = field(default_factory=utcnow)
    expires_at: datetime = field(default_factory=lambda: utcnow() + SESSION_TTL)


def _row_to_invite(row: InviteCodeRow) -> InviteCode:
    return InviteCode(
        id=row.id,
        code=row.code,
        status=row.status,
        used_by=row.used_by,
        device_id=row.device_id,
        created_at=row.created_at,
        activated_at=row.activated_at,
        expires_at=row.expires_at,
    )


def _row_to_account(row: BetaAccountRow) -> BetaAccount:
    return BetaAccount(
        id=row.id,
        invite_code_id=row.invite_code_id,
        invite_code=row.invite_code,
        user_token=row.user_token,
        device_id=row.device_id,
        status=getattr(row, "status", None) or "active",
        revoked_at=getattr(row, "revoked_at", None),
        created_at=row.created_at,
        expires_at=row.expires_at,
    )


def _row_to_session(row: BetaSessionRow) -> BetaSession:
    return BetaSession(
        id=row.id,
        invite_code=row.invite_code,
        token=row.token,
        device_id=row.device_id,
        beta_account_id=getattr(row, "beta_account_id", None),
        heartbeat_at=getattr(row, "heartbeat_at", None),
        current_page=getattr(row, "current_page", None),
        current_project=getattr(row, "current_project", None),
        current_stage=getattr(row, "current_stage", None),
        user_agent=getattr(row, "user_agent", None),
        client_ip=getattr(row, "client_ip", None),
        read_only=bool(getattr(row, "read_only", False)),
        created_at=row.created_at,
        expires_at=row.expires_at,
    )


class _MemoryInviteStore:
    def __init__(self) -> None:
        self._lock = threading.Lock()
        self.codes: dict[str, InviteCode] = {}
        self.by_code: dict[str, str] = {}
        self.accounts: dict[str, BetaAccount] = {}
        self.account_by_invite_id: dict[str, str] = {}
        self.sessions: dict[str, BetaSession] = {}
        self.by_token: dict[str, str] = {}

    def create_code(self, code: Optional[str] = None) -> InviteCode:
        with self._lock:
            raw = (code or generate_invite_code()).strip().upper()
            if raw in self.by_code:
                raise ValueError("code already exists")
            inv = InviteCode(id=new_id("inv_"), code=raw)
            self.codes[inv.id] = inv
            self.by_code[raw] = inv.id
            return inv

    def get_by_code(self, code: str) -> Optional[InviteCode]:
        with self._lock:
            iid = self.by_code.get(code.strip().upper())
            return self.codes.get(iid) if iid else None

    def save_invite(self, inv: InviteCode) -> InviteCode:
        with self._lock:
            self.codes[inv.id] = inv
            self.by_code[inv.code.upper()] = inv.id
            return inv

    def get_account(self, account_id: str) -> Optional[BetaAccount]:
        with self._lock:
            return self.accounts.get(account_id)

    def get_account_by_invite_id(self, invite_code_id: str) -> Optional[BetaAccount]:
        with self._lock:
            aid = self.account_by_invite_id.get(invite_code_id)
            return self.accounts.get(aid) if aid else None

    def create_account(self, account: BetaAccount) -> BetaAccount:
        with self._lock:
            self.accounts[account.id] = account
            self.account_by_invite_id[account.invite_code_id] = account.id
            return account

    def save_account(self, account: BetaAccount) -> BetaAccount:
        with self._lock:
            self.accounts[account.id] = account
            self.account_by_invite_id[account.invite_code_id] = account.id
            return account

    def list_accounts(self, limit: int = 200) -> list[BetaAccount]:
        with self._lock:
            items = list(self.accounts.values())
        items.sort(key=lambda a: a.created_at, reverse=True)
        return items[:limit]

    def create_session(self, session: BetaSession) -> BetaSession:
        with self._lock:
            self.sessions[session.id] = session
            self.by_token[session.token] = session.id
            return session

    def save_session(self, session: BetaSession) -> BetaSession:
        with self._lock:
            self.sessions[session.id] = session
            self.by_token[session.token] = session.id
            return session

    def get_session_by_token(self, token: str) -> Optional[BetaSession]:
        with self._lock:
            sid = self.by_token.get(token)
            return self.sessions.get(sid) if sid else None

    def delete_session(self, token: str) -> None:
        with self._lock:
            sid = self.by_token.pop(token, None)
            if sid:
                self.sessions.pop(sid, None)

    def delete_sessions_for_account(self, beta_account_id: str) -> int:
        with self._lock:
            doomed = [
                s
                for s in self.sessions.values()
                if s.beta_account_id == beta_account_id
            ]
            for s in doomed:
                self.by_token.pop(s.token, None)
                self.sessions.pop(s.id, None)
            return len(doomed)

    def list_sessions_for_account(self, beta_account_id: str) -> list[BetaSession]:
        with self._lock:
            return [
                s
                for s in self.sessions.values()
                if s.beta_account_id == beta_account_id
            ]

    def list_codes(self, limit: int = 50) -> list[InviteCode]:
        with self._lock:
            items = list(self.codes.values())
        items.sort(key=lambda c: c.created_at, reverse=True)
        return items[:limit]

    def delete_invite(self, code: str) -> bool:
        with self._lock:
            iid = self.by_code.pop(code.strip().upper(), None)
            if not iid:
                return False
            self.codes.pop(iid, None)
            return True


class _SqlInviteStore:
    def create_code(self, code: Optional[str] = None) -> InviteCode:
        assert SessionLocal is not None
        raw = (code or generate_invite_code()).strip().upper()
        with SessionLocal() as session:
            existing = (
                session.query(InviteCodeRow)
                .filter(InviteCodeRow.code == raw)
                .one_or_none()
            )
            if existing:
                raise ValueError("code already exists")
            row = InviteCodeRow(
                id=new_id("inv_"),
                code=raw,
                status="active",
            )
            session.add(row)
            session.commit()
            session.refresh(row)
            return _row_to_invite(row)

    def get_by_code(self, code: str) -> Optional[InviteCode]:
        assert SessionLocal is not None
        raw = code.strip().upper()
        with SessionLocal() as session:
            row = (
                session.query(InviteCodeRow)
                .filter(InviteCodeRow.code == raw)
                .one_or_none()
            )
            return _row_to_invite(row) if row else None

    def save_invite(self, inv: InviteCode) -> InviteCode:
        assert SessionLocal is not None
        with SessionLocal() as session:
            row = session.get(InviteCodeRow, inv.id)
            if not row:
                row = InviteCodeRow(id=inv.id, code=inv.code)
                session.add(row)
            row.code = inv.code
            row.status = inv.status
            row.used_by = inv.used_by
            row.device_id = inv.device_id
            row.activated_at = inv.activated_at
            row.expires_at = inv.expires_at
            session.commit()
            session.refresh(row)
            return _row_to_invite(row)

    def get_account(self, account_id: str) -> Optional[BetaAccount]:
        assert SessionLocal is not None
        with SessionLocal() as session:
            row = session.get(BetaAccountRow, account_id)
            return _row_to_account(row) if row else None

    def get_account_by_invite_id(self, invite_code_id: str) -> Optional[BetaAccount]:
        assert SessionLocal is not None
        with SessionLocal() as session:
            row = (
                session.query(BetaAccountRow)
                .filter(BetaAccountRow.invite_code_id == invite_code_id)
                .one_or_none()
            )
            return _row_to_account(row) if row else None

    def create_account(self, account: BetaAccount) -> BetaAccount:
        assert SessionLocal is not None
        with SessionLocal() as session:
            row = BetaAccountRow(
                id=account.id,
                invite_code_id=account.invite_code_id,
                invite_code=account.invite_code,
                user_token=account.user_token,
                device_id=account.device_id,
                status=account.status or "active",
                revoked_at=account.revoked_at,
                expires_at=account.expires_at,
            )
            session.add(row)
            session.commit()
            session.refresh(row)
            return _row_to_account(row)

    def save_account(self, account: BetaAccount) -> BetaAccount:
        assert SessionLocal is not None
        with SessionLocal() as session:
            row = session.get(BetaAccountRow, account.id)
            if not row:
                return self.create_account(account)
            row.invite_code_id = account.invite_code_id
            row.invite_code = account.invite_code
            row.user_token = account.user_token
            row.device_id = account.device_id
            row.status = account.status or "active"
            row.revoked_at = account.revoked_at
            row.expires_at = account.expires_at
            session.commit()
            session.refresh(row)
            return _row_to_account(row)

    def list_accounts(self, limit: int = 200) -> list[BetaAccount]:
        assert SessionLocal is not None
        with SessionLocal() as session:
            rows = (
                session.query(BetaAccountRow)
                .order_by(BetaAccountRow.created_at.desc())
                .limit(limit)
                .all()
            )
            return [_row_to_account(r) for r in rows]

    def create_session(self, beta: BetaSession) -> BetaSession:
        assert SessionLocal is not None
        with SessionLocal() as session:
            row = BetaSessionRow(
                id=beta.id,
                invite_code=beta.invite_code,
                token=beta.token,
                device_id=beta.device_id,
                beta_account_id=beta.beta_account_id,
                heartbeat_at=beta.heartbeat_at,
                current_page=beta.current_page,
                current_project=beta.current_project,
                current_stage=beta.current_stage,
                user_agent=beta.user_agent,
                client_ip=beta.client_ip,
                read_only=bool(beta.read_only),
                expires_at=beta.expires_at,
            )
            session.add(row)
            session.commit()
            session.refresh(row)
            return _row_to_session(row)

    def save_session(self, beta: BetaSession) -> BetaSession:
        assert SessionLocal is not None
        with SessionLocal() as session:
            row = session.get(BetaSessionRow, beta.id)
            if not row:
                return self.create_session(beta)
            row.invite_code = beta.invite_code
            row.token = beta.token
            row.device_id = beta.device_id
            row.beta_account_id = beta.beta_account_id
            row.heartbeat_at = beta.heartbeat_at
            row.current_page = beta.current_page
            row.current_project = beta.current_project
            row.current_stage = beta.current_stage
            row.user_agent = beta.user_agent
            row.client_ip = beta.client_ip
            row.read_only = bool(beta.read_only)
            row.expires_at = beta.expires_at
            session.commit()
            session.refresh(row)
            return _row_to_session(row)

    def get_session_by_token(self, token: str) -> Optional[BetaSession]:
        assert SessionLocal is not None
        with SessionLocal() as session:
            row = (
                session.query(BetaSessionRow)
                .filter(BetaSessionRow.token == token)
                .one_or_none()
            )
            return _row_to_session(row) if row else None

    def delete_session(self, token: str) -> None:
        assert SessionLocal is not None
        with SessionLocal() as session:
            row = (
                session.query(BetaSessionRow)
                .filter(BetaSessionRow.token == token)
                .one_or_none()
            )
            if row:
                session.delete(row)
                session.commit()

    def delete_sessions_for_account(self, beta_account_id: str) -> int:
        assert SessionLocal is not None
        with SessionLocal() as session:
            rows = (
                session.query(BetaSessionRow)
                .filter(BetaSessionRow.beta_account_id == beta_account_id)
                .all()
            )
            count = len(rows)
            for row in rows:
                session.delete(row)
            session.commit()
            return count

    def list_sessions_for_account(self, beta_account_id: str) -> list[BetaSession]:
        assert SessionLocal is not None
        with SessionLocal() as session:
            rows = (
                session.query(BetaSessionRow)
                .filter(BetaSessionRow.beta_account_id == beta_account_id)
                .all()
            )
            return [_row_to_session(r) for r in rows]

    def list_codes(self, limit: int = 50) -> list[InviteCode]:
        assert SessionLocal is not None
        with SessionLocal() as session:
            rows = (
                session.query(InviteCodeRow)
                .order_by(InviteCodeRow.created_at.desc())
                .limit(limit)
                .all()
            )
            return [_row_to_invite(r) for r in rows]

    def delete_invite(self, code: str) -> bool:
        assert SessionLocal is not None
        raw = code.strip().upper()
        with SessionLocal() as session:
            row = (
                session.query(InviteCodeRow)
                .filter(InviteCodeRow.code == raw)
                .one_or_none()
            )
            if not row:
                return False
            session.delete(row)
            session.commit()
            return True


def build_invite_store() -> _MemoryInviteStore | _SqlInviteStore:
    if engine is not None and SessionLocal is not None:
        return _SqlInviteStore()
    return _MemoryInviteStore()


invite_db = build_invite_store()


def mark_expired_if_needed(inv: InviteCode) -> InviteCode:
    """Flip used → expired when wall clock passes expires_at."""
    if is_expired(inv) and inv.status != "expired":
        inv.status = "expired"
        invite_db.save_invite(inv)
    return inv


def _aware(dt: Optional[datetime]) -> Optional[datetime]:
    if dt is None:
        return None
    if dt.tzinfo is None:
        return dt.replace(tzinfo=timezone.utc)
    return dt


def is_expired(inv: InviteCode) -> bool:
    exp = _aware(inv.expires_at)
    return bool(exp and utcnow() >= exp)


def session_valid(sess: BetaSession) -> bool:
    return utcnow() < _aware(sess.expires_at)  # type: ignore[operator]


def get_or_create_beta_account(
    inv: InviteCode,
    *,
    device_id: str,
    expires_at: Optional[datetime],
) -> BetaAccount:
    """One invite code → one durable beta account (reused on same-device re-entry)."""
    existing = invite_db.get_account_by_invite_id(inv.id)
    if existing:
        if expires_at and existing.expires_at != expires_at:
            existing.expires_at = expires_at
            invite_db.save_account(existing)
        return existing

    account = BetaAccount(
        id=new_id("beta_"),
        invite_code_id=inv.id,
        invite_code=inv.code,
        user_token=new_token(),
        device_id=device_id,
        expires_at=expires_at,
    )
    return invite_db.create_account(account)


def verify_and_activate(
    code: str,
    *,
    device_id: str,
    used_by: Optional[str] = None,
) -> tuple[BetaSession, InviteCode, BetaAccount]:
    """Validate invite code, ensure beta account, return a fresh 3h session."""
    inv = invite_db.get_by_code(code)
    if not inv:
        raise LookupError("Invalid code")

    inv = mark_expired_if_needed(inv)

    if inv.status == "expired" or is_expired(inv):
        inv.status = "expired"
        invite_db.save_invite(inv)
        raise PermissionError("Expired")

    if inv.status == "used":
        if inv.device_id and inv.device_id != device_id:
            raise PermissionError("Already used")
        if is_expired(inv):
            inv.status = "expired"
            invite_db.save_invite(inv)
            raise PermissionError("Expired")
        expires = _aware(inv.expires_at) or (utcnow() + SESSION_TTL)
    elif inv.status == "active":
        now = utcnow()
        inv.status = "used"
        inv.device_id = device_id
        inv.used_by = used_by or device_id
        inv.activated_at = now
        inv.expires_at = now + SESSION_TTL
        invite_db.save_invite(inv)
        expires = inv.expires_at
    else:
        raise PermissionError("Invalid code")

    existing = invite_db.get_account_by_invite_id(inv.id)
    if existing and (existing.status or "active") == "revoked":
        raise PermissionError("Revoked")

    account = get_or_create_beta_account(
        inv,
        device_id=device_id,
        expires_at=expires,
    )
    if (account.status or "active") == "revoked":
        raise PermissionError("Revoked")

    sess = BetaSession(
        id=new_id("sess_"),
        invite_code=inv.code,
        token=new_token(),
        device_id=device_id,
        beta_account_id=account.id,
        expires_at=expires,  # type: ignore[arg-type]
    )
    invite_db.create_session(sess)
    return sess, inv, account


def get_valid_session(token: str) -> Optional[BetaSession]:
    if not token:
        return None
    failure = describe_session_failure(token)
    if failure:
        return None
    sess = invite_db.get_session_by_token(token)
    return sess


def describe_session_failure(token: str) -> Optional[dict]:
    """Return ``{code, message}`` when the token cannot be used; else ``None``."""
    if not token:
        return {
            "code": "session_missing",
            "message": "Invite expired or missing. Enter a valid invite code.",
        }
    sess = invite_db.get_session_by_token(token)
    if not sess:
        return {
            "code": "session_missing",
            "message": "Invite expired or missing. Enter a valid invite code.",
        }
    if not session_valid(sess):
        invite_db.delete_session(token)
        return {
            "code": "session_expired",
            "message": "Your session has expired. Enter a valid invite code.",
        }
    inv = invite_db.get_by_code(sess.invite_code)
    # Prefer account_revoked over invite-expired so Force logout / Revoke
    # surface the admin kick modal instead of a generic expiry message.
    if sess.beta_account_id:
        account = invite_db.get_account(sess.beta_account_id)
        if account and (account.status or "active") == "revoked":
            return {
                "code": "account_revoked",
                "message": (
                    "Your beta access was ended by an administrator. "
                    "Please contact Nesto if you need a new invite."
                ),
            }
    if inv and (inv.status == "expired" or is_expired(inv)):
        invite_db.delete_session(token)
        return {
            "code": "session_expired",
            "message": "Your invite window has expired. Enter a valid invite code.",
        }
    # Legacy sessions created before beta_accounts — attach account on read
    if not sess.beta_account_id and inv:
        account = get_or_create_beta_account(
            inv,
            device_id=sess.device_id or "",
            expires_at=_aware(inv.expires_at),
        )
        sess.beta_account_id = account.id
        invite_db.save_session(sess)
        if (account.status or "active") == "revoked":
            return {
                "code": "account_revoked",
                "message": (
                    "Your beta access was ended by an administrator. "
                    "Please contact Nesto if you need a new invite."
                ),
            }
    return None


def revoke_account(account_id: str) -> Optional[BetaAccount]:
    account = invite_db.get_account(account_id)
    if not account:
        return None
    account.status = "revoked"
    account.revoked_at = utcnow()
    invite_db.save_account(account)
    # Keep sessions so the next API/heartbeat can return account_revoked
    # (sessions are deleted when the client receives that 401).
    return account


def force_logout_account(account_id: str) -> Optional[tuple[BetaAccount, int]]:
    """Kick the user (revoke) and cancel their waiting/running jobs.

    Returns ``(account, cancelled_job_count)`` or ``None`` if account missing.
    """
    from backend.database import db

    account = revoke_account(account_id)
    if not account:
        return None

    cancelled = 0
    active = {"waiting", "running", "processing"}
    for project in db.list_projects_for_beta_account(account_id):
        killed_here = False
        for job in db.list_jobs_for_project(project.project_id):
            if job.status in active:
                job.status = "cancelled"
                job.stage = "Cancelled"
                job.error = "Stopped by admin force logout"
                db.save_job(job)
                cancelled += 1
                killed_here = True
        if killed_here or project.status in ("processing", "queued", "running"):
            project.status = "error"
            project.error = "Stopped by admin force logout"
            project.active_job_id = None
            db.save_project(project)
    return account, cancelled


def reactivate_account(account_id: str) -> Optional[BetaAccount]:
    account = invite_db.get_account(account_id)
    if not account:
        return None
    account.status = "active"
    account.revoked_at = None
    invite_db.save_account(account)
    return account


def create_view_as_session(account_id: str, *, ttl_hours: float = 1.0) -> BetaSession:
    """Admin-issued read-only session that impersonates a beta account."""
    account = invite_db.get_account(account_id)
    if not account:
        raise LookupError("account not found")
    if (account.status or "active") == "revoked":
        raise PermissionError("account revoked")
    sess = BetaSession(
        id=new_id("view_"),
        invite_code=account.invite_code,
        token=new_token(),
        device_id="admin-view-as",
        beta_account_id=account.id,
        heartbeat_at=utcnow(),
        current_page="view-as",
        read_only=True,
        expires_at=utcnow() + timedelta(hours=ttl_hours),
    )
    return invite_db.create_session(sess)


def touch_session_heartbeat(
    token: str,
    *,
    current_page: Optional[str] = None,
    current_project: Optional[str] = None,
    current_stage: Optional[str] = None,
    user_agent: Optional[str] = None,
    client_ip: Optional[str] = None,
) -> Optional[BetaSession]:
    sess = get_valid_session(token)
    if not sess:
        return None
    sess.heartbeat_at = utcnow()
    if current_page is not None:
        sess.current_page = current_page
    if current_project is not None:
        sess.current_project = current_project
    if current_stage is not None:
        sess.current_stage = current_stage
    if user_agent is not None:
        sess.user_agent = user_agent
    if client_ip is not None:
        sess.client_ip = client_ip
    return invite_db.save_session(sess)


ONLINE_WINDOW = timedelta(seconds=45)


def session_is_online(sess: BetaSession) -> bool:
    hb = _aware(sess.heartbeat_at)
    if not hb:
        return False
    return utcnow() - hb <= ONLINE_WINDOW
