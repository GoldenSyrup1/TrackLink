"""
Role-based access control.

Roles
-----
admin    — full read/write on all resources
analyst  — read/write persons and startups; read-only relationships
viewer   — read-only on all resources

Permissions are checked per-resource-type per-action.  Route handlers
inject `require_permission(Permission.READ_PERSON)` as a dependency.
"""
from __future__ import annotations

from enum import Enum

from fastapi import Depends, HTTPException, status

from auth.jwt import TokenData, get_current_user


# ---------------------------------------------------------------------------
# Enumerations
# ---------------------------------------------------------------------------

class Role(str, Enum):
    ADMIN = "admin"
    ANALYST = "analyst"
    VIEWER = "viewer"


class Permission(str, Enum):
    READ_PERSON = "read:person"
    WRITE_PERSON = "write:person"
    READ_STARTUP = "read:startup"
    WRITE_STARTUP = "write:startup"
    READ_RELATIONSHIP = "read:relationship"
    WRITE_RELATIONSHIP = "write:relationship"
    READ_SEARCH = "read:search"
    ADMIN_ALL = "admin:all"


# ---------------------------------------------------------------------------
# Role → permission mapping
# ---------------------------------------------------------------------------

_ROLE_PERMISSIONS: dict[Role, frozenset[Permission]] = {
    Role.VIEWER: frozenset({
        Permission.READ_PERSON,
        Permission.READ_STARTUP,
        Permission.READ_RELATIONSHIP,
        Permission.READ_SEARCH,
    }),
    Role.ANALYST: frozenset({
        Permission.READ_PERSON,
        Permission.WRITE_PERSON,
        Permission.READ_STARTUP,
        Permission.WRITE_STARTUP,
        Permission.READ_RELATIONSHIP,
        Permission.READ_SEARCH,
    }),
    Role.ADMIN: frozenset({p for p in Permission}),  # all permissions
}


# ---------------------------------------------------------------------------
# Permission check helpers
# ---------------------------------------------------------------------------

def has_permission(token: TokenData, permission: Permission) -> bool:
    for role_str in token.roles:
        try:
            role = Role(role_str)
        except ValueError:
            continue
        if permission in _ROLE_PERMISSIONS.get(role, frozenset()):
            return True
    return False


def require_permission(permission: Permission):
    """
    Dependency factory.  Returns a FastAPI dependency that verifies the
    authenticated user holds `permission`, raising 403 otherwise.

    Usage::

        @router.get("/persons/{id}")
        async def get_person(
            id: str,
            _: None = Depends(require_permission(Permission.READ_PERSON)),
            user: TokenData = Depends(get_current_user),
        ):
            ...
    """
    async def _check(token: TokenData = Depends(get_current_user)) -> TokenData:
        if not has_permission(token, permission):
            raise HTTPException(
                status_code=status.HTTP_403_FORBIDDEN,
                detail=f"Permission denied: {permission.value}",
            )
        return token

    # Give the dependency a stable name so FastAPI's OpenAPI schema is readable
    _check.__name__ = f"require_{permission.value.replace(':', '_')}"
    return _check
