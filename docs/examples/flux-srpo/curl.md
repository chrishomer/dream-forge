Quick Curl Examples

- Simple 1× generate @1024×1024
  - `curl -sS "$API/jobs" -H 'Content-Type: application/json' -d @simple.json | jq .`

- Portrait batch (3 items) + upscale×2
  - `curl -sS "$API/jobs" -H 'Content-Type: application/json' -d @portrait_batch_upscale.json | jq .`

- Landscape with custom scheduler + fixed seed
  - `curl -sS "$API/jobs" -H 'Content-Type: application/json' -d @landscape_custom_scheduler.json | jq .`

Replace `$API` with your endpoint, e.g. `export API=http://127.0.0.1:8001/v1`.

