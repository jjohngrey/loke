# Shared boundary

B owns Python contracts; A consumes generated TypeScript; C implements MemoryPort.
Run `npm run contracts:generate` after an agreed schema change. Do not manually edit generated types.

Current request/view/context/error examples and memory commit semantics are published in
[shared/fixtures](../fixtures/README.md). API success response models now appear in OpenAPI.
Validation errors (422) retain FastAPI's separate array shape; ApiError covers string-detail errors.
