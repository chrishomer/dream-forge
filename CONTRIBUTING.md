# Contributing to Dream Forge

Thanks for your interest in contributing! This repo aims to stay lean and maintainable. Please follow these guidelines:

## Getting Started
- Install `uv` and sync deps: `make uv-sync`
- Run quality gates: `make lint type test openapi`
- Use Docker Compose for local runs: `make up` / `make down`

## Coding Standards
- Keep the API surface small and stable; prefer explicit configuration and clear seams.
- Follow the Masters documents for requirements and design principles (see `docs/masters/`).
- Keep changes focused and avoid unrelated refactors.

## PR Process
- Use the PR template; fill in the Simplicity Checklist.
- Update the OpenAPI spec (`make openapi`) and commit it.
- Add tests for new behavior, and run `make test`.
- For schema changes, add an Alembic migration and run `make migrate-head` locally.
- Write an ADR in `docs/adrs/` if you introduce new services, dependencies, public endpoints, or schema additions.

## Contact
Open an issue or start a discussion for planning larger changes.

