from app.main import create_app


def test_app_factory_registers_routes():
    app = create_app()
    paths = set(app.openapi()["paths"].keys())

    assert "/health" in paths
    assert "/api/v1/auth/login" in paths
    assert "/api/v1/cases" in paths
    assert "/api/v1/documents" in paths
