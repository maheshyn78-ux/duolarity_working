# Backend API Documentation

Interactive OpenAPI documentation is served by FastAPI at:

- Swagger UI: `http://localhost:8000/docs`
- OpenAPI JSON: `http://localhost:8000/openapi.json`

## Milestone 1 API Areas

- Authentication: `/api/v1/auth/*`
- Users and RBAC: `/api/v1/users/*`
- Organizations: `/api/v1/organizations/*`
- Cases: `/api/v1/cases/*`
- Documents: `/api/v1/documents/*`
- Health: `/health`

## Default Local Administrator

The local seed process creates a Super Admin account when one does not already exist.

- Email: `admin@example.com`
- Password: `ChangeMe123!@#`

Override these values with `SEED_SUPER_ADMIN_EMAIL` and `SEED_SUPER_ADMIN_PASSWORD`.
