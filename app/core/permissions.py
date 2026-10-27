from enum import StrEnum


class RoleName(StrEnum):
    SUPER_ADMIN = "Super Admin"
    ORGANIZATION_ADMIN = "Organization Admin"
    AUDITOR = "Auditor"
    ANALYST = "Analyst"
    REVIEWER = "Reviewer"


class Permission(StrEnum):
    ORGANIZATION_READ = "organization:read"
    ORGANIZATION_CREATE = "organization:create"
    ORGANIZATION_UPDATE = "organization:update"
    DEPARTMENT_MANAGE = "department:manage"
    USER_READ = "user:read"
    USER_INVITE = "user:invite"
    USER_UPDATE = "user:update"
    ROLE_ASSIGN = "role:assign"
    AUDIT_READ = "audit:read"
    DASHBOARD_READ = "dashboard:read"
    CASE_READ = "case:read"
    CASE_CREATE = "case:create"
    CASE_UPDATE = "case:update"
    CASE_ASSIGN = "case:assign"
    DOCUMENT_READ = "document:read"
    DOCUMENT_UPLOAD = "document:upload"
    DOCUMENT_UPDATE = "document:update"


ROLE_PERMISSIONS: dict[RoleName, set[Permission]] = {
    RoleName.SUPER_ADMIN: set(Permission),
    RoleName.ORGANIZATION_ADMIN: {
        Permission.ORGANIZATION_READ,
        Permission.ORGANIZATION_UPDATE,
        Permission.DEPARTMENT_MANAGE,
        Permission.USER_READ,
        Permission.USER_INVITE,
        Permission.USER_UPDATE,
        Permission.ROLE_ASSIGN,
        Permission.AUDIT_READ,
        Permission.DASHBOARD_READ,
        Permission.CASE_READ,
        Permission.CASE_CREATE,
        Permission.CASE_UPDATE,
        Permission.CASE_ASSIGN,
        Permission.DOCUMENT_READ,
        Permission.DOCUMENT_UPLOAD,
        Permission.DOCUMENT_UPDATE,
    },
    RoleName.AUDITOR: {
        Permission.ORGANIZATION_READ,
        Permission.USER_READ,
        Permission.AUDIT_READ,
        Permission.DASHBOARD_READ,
        Permission.CASE_READ,
        Permission.DOCUMENT_READ,
    },
    RoleName.ANALYST: {
        Permission.ORGANIZATION_READ,
        Permission.USER_READ,
        Permission.DASHBOARD_READ,
        Permission.CASE_READ,
        Permission.CASE_CREATE,
        Permission.CASE_UPDATE,
        Permission.DOCUMENT_READ,
        Permission.DOCUMENT_UPLOAD,
        Permission.DOCUMENT_UPDATE,
    },
    RoleName.REVIEWER: {
        Permission.ORGANIZATION_READ,
        Permission.USER_READ,
        Permission.DASHBOARD_READ,
        Permission.CASE_READ,
        Permission.CASE_UPDATE,
        Permission.DOCUMENT_READ,
    },
}
