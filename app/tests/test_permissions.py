from app.core.permissions import Permission, ROLE_PERMISSIONS, RoleName


def test_super_admin_has_all_permissions():
    assert ROLE_PERMISSIONS[RoleName.SUPER_ADMIN] == set(Permission)


def test_reviewer_has_case_read_permission():
    assert Permission.CASE_READ in ROLE_PERMISSIONS[RoleName.REVIEWER]
