## Summary

Describe the change and why it’s needed.

## Checklist

- [ ] Simplicity: Scope fits MVP and avoids premature generalization (see Masters 02 §5.1)
- [ ] OpenAPI updated (`make openapi`) and committed (diff is clean)
- [ ] Lint & type check pass locally (`make lint type`)
- [ ] Tests added/updated and pass (`make test`)
- [ ] Migrations added (if schema changed) and applied locally (`make migrate-head`)
- [ ] Docs updated (DEV.md/README/masters) as needed

## Testing Notes

How did you validate this change? Include commands/logs and screenshots as appropriate.

## ADR

If this PR introduces a new service, external dependency, public endpoint, or schema addition, link the ADR here.

