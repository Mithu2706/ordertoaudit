"""Authentication and user management."""
from datetime import UTC, datetime
from functools import lru_cache

from sqlalchemy import or_, select
from sqlalchemy.orm import Session

from app.core.errors import AuthenticationError, BusinessRuleError, NotFoundError, PermissionDeniedError
from app.core.security import hash_password, verify_password
from app.models import Role, User
from app.models.enums import RoleCode
from app.schemas.users import UserCreate, UserUpdate
from app.services import audit
from app.services.common import apply_changes, ensure_unique, get_or_404, paginate

@lru_cache
def _dummy_hash() -> str:
    """Verified against when the username does not exist, so a wrong username and a wrong
    password take similar time (prevents user enumeration by timing)."""
    return hash_password("not-a-real-password")


def authenticate(db: Session, username: str, password: str, ip: str | None = None) -> User:
    user = db.scalars(select(User).where(User.username == username.strip().lower())).first()
    if user is None:
        verify_password(password, _dummy_hash())
        raise AuthenticationError("Incorrect username or password")
    if not verify_password(password, user.password_hash):
        raise AuthenticationError("Incorrect username or password")
    if not user.is_active:
        raise AuthenticationError("This account is disabled")
    user.last_login_at = datetime.now(UTC)
    audit.record(db, user_id=user.id, action="LOGIN", entity_type="user", entity_id=user.id, ip=ip)
    db.flush()
    return user


def get_role(db: Session, code: RoleCode) -> Role:
    role = db.scalars(select(Role).where(Role.code == code)).first()
    if role is None:
        raise BusinessRuleError(f"Role {code.value} is not configured; run the seed script")
    return role


def _guard_owner_privilege(actor: User, target_role: RoleCode | None, target_user: User | None = None) -> None:
    """Only an OWNER may create owners or modify an owner's account (no privilege escalation)."""
    touches_owner = target_role == RoleCode.OWNER or (
        target_user is not None and target_user.role.code == RoleCode.OWNER
    )
    if touches_owner and actor.role.code != RoleCode.OWNER:
        raise PermissionDeniedError("Only an owner can create or modify owner accounts")


def list_users(db: Session, q: str | None, role: RoleCode | None, limit: int, offset: int):
    stmt = select(User).join(Role).order_by(User.username)
    if q:
        like = f"%{q.strip()}%"
        stmt = stmt.where(or_(User.username.ilike(like), User.full_name.ilike(like)))
    if role:
        stmt = stmt.where(Role.code == role)
    return paginate(db, stmt, limit, offset)


def create_user(db: Session, data: UserCreate, actor: User, ip: str | None = None) -> User:
    _guard_owner_privilege(actor, data.role)
    ensure_unique(db, User.username, data.username, "Username")
    ensure_unique(db, User.email, data.email, "Email")
    user = User(
        username=data.username, full_name=data.full_name, email=data.email, phone=data.phone,
        password_hash=hash_password(data.password), role_id=get_role(db, data.role).id, is_active=True,
    )
    db.add(user)
    db.flush()
    db.refresh(user)
    audit.record(db, user_id=actor.id, action="CREATE", entity_type="user", entity_id=user.id,
                 after=audit.snapshot(user), ip=ip)
    return user


def update_user(db: Session, user_id: int, data: UserUpdate, actor: User, ip: str | None = None) -> User:
    user = get_or_404(db, User, user_id, "User")
    changes = data.model_dump(exclude_unset=True)
    _guard_owner_privilege(actor, changes.get("role"), user)
    if user.id == actor.id and (changes.get("is_active") is False or "role" in changes):
        raise BusinessRuleError("You cannot deactivate yourself or change your own role")
    if "email" in changes:
        ensure_unique(db, User.email, changes["email"], "Email", exclude_pk=user.id)

    before = audit.snapshot(user)
    password = changes.pop("password", None)
    role = changes.pop("role", None)
    apply_changes(user, changes, required={"full_name", "is_active"})
    if role is not None:
        user.role_id = get_role(db, role).id
    if password:
        user.password_hash = hash_password(password)
    db.flush()
    db.refresh(user)
    after = audit.snapshot(user)
    audit.record_update(db, user_id=actor.id, entity_type="user", entity_id=user.id, before=before, after=after, ip=ip)
    if password:
        audit.record(db, user_id=actor.id, action="PASSWORD_RESET", entity_type="user", entity_id=user.id, ip=ip)
    return user


def require_user(db: Session, user_id: int) -> User:
    user = db.get(User, user_id)
    if user is None:
        raise NotFoundError(f"User {user_id} not found")
    return user
