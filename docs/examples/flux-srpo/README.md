Flux-SRPO Example Jobs

These examples demonstrate submitting jobs that use the `flux-srpo` engine via the Dream Forge HTTP API.

Prereqs
- API running locally (Compose or `make up`).
- FLUX base + SRPO transformer prefetched as described in `DEV.md` (section: FLUX.1-dev + SRPO).
- `HF_TOKEN` available to the worker if the FLUX base is gated.

Setup
- Set endpoint: `export API=http://127.0.0.1:8001/v1`

Examples
- Simple generate (1024×1024 PNG)
  - File: `simple.json`
  - Run: `curl -sS "$API/jobs" -H 'Content-Type: application/json' -d @docs/examples/flux-srpo/simple.json | jq .`

- Portrait batch (3 items) + upscale×2
  - File: `portrait_batch_upscale.json`
  - Run: `curl -sS "$API/jobs" -H 'Content-Type: application/json' -d @docs/examples/flux-srpo/portrait_batch_upscale.json | jq .`

- Landscape with custom scheduler + fixed seed (JPG)
  - File: `landscape_custom_scheduler.json`
  - Run: `curl -sS "$API/jobs" -H 'Content-Type: application/json' -d @docs/examples/flux-srpo/landscape_custom_scheduler.json | jq .`

Notes
- You can also run the live helper: `ENGINE=flux-srpo python scripts/run_live_generate2_upscale.py`.
- If `/v1/models` returns installed models, you may include `model_id` in the JSON payload. Otherwise, the worker falls back to its default registry resolution.
