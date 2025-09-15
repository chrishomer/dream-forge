# M3 Follow‑ups and Enhancements

Status: Candidate backlog (prioritize by impact and complexity)

## Downloader & Adapters

- CivitAI rich refs: accept `civitai:<model_id_or_slug>@<version_name>` by querying the Models API to resolve to a numeric version id.
- Resume downloads: segmented transfer with resume on retry; integrity verified post‑merge.
- Concurrency & progress: concurrent chunk fetching with rate limiting and simple TTY progress for CLI.
- License gating UX: preflight license checks for HF/CivitAI; clear remediation messages and links.
- Signature and safety: optional safetensors header validation and allowlist of known hashes.

## Registry & Descriptor

- Parameters schema: generate richer, model‑specific `parameters_schema` for UI validation (e.g., supported sizes/aspect ratios).
- Provenance: capture additional provenance (e.g., HF commit SHA, CivitAI metadata) and embed in descriptor.
- Model categories: support kinds beyond `sdxl-checkpoint` and indicate capabilities (e.g., `upscale`).

## API & Worker

- Filters: add `enabled` query param to `/v1/models` and optional pagination.
- Background download job (M9): admin‑triggered `model_download` queue for server‑side downloads that upsert the registry.
- VRAM preflight (M5): add headroom checks and early error when the selected model cannot fit.
- Error taxonomy: explicit `invalid_model` error code across API when a specified `model_id` is missing/disabled/not installed.

## DevEx & Ops

- Cache: shared local cache for downloaded files across different refs; hardlink into normalized installs.
- Checksums store: optional central file of sha256 → paths to speed up verify.
- Spec diffs: CI step to diff OpenAPI for `/models*` and `model_id` changes.

