#!/usr/bin/env bash
set -euo pipefail

COMPOSE_FILE="compose/docker-compose.yml"
API_HEALTH="http://127.0.0.1:8001/healthz"
API_READY="http://127.0.0.1:8001/readyz"
WORKER_METRICS="http://127.0.0.1:9010/metrics"
MINIO_HEALTH="http://127.0.0.1:9000/minio/health/ready"

ok=0; fail=0

echo "== Containers (docker compose ps) =="
docker compose -f "$COMPOSE_FILE" ps || { echo "compose ps failed"; }
echo

echo "== API /healthz =="
code=$(curl -s -o /dev/null -w '%{http_code}' "$API_HEALTH" || true)
body=$(curl -s "$API_HEALTH" || true)
echo "code=$code body=$body"
if [ "$code" = "200" ]; then ok=$((ok+1)); else fail=$((fail+1)); fi
echo

echo "== API /readyz (DB+S3) =="
code=$(curl -s -o /dev/null -w '%{http_code}' "$API_READY" || true)
body=$(curl -s "$API_READY" || true)
echo "code=$code body=$body"
if [ "$code" = "200" ]; then ok=$((ok+1)); else fail=$((fail+1)); fi
echo

echo "== Worker metrics =="
tries=0
while [ $tries -lt 10 ]; do
  if curl -fsS "$WORKER_METRICS" 2>/dev/null | grep -q "df_worker_ready"; then
    echo "worker metrics OK"
    ok=$((ok+1))
    break
  fi
  tries=$((tries+1))
  sleep 1
done
if [ $tries -ge 10 ]; then
  echo "worker metrics MISSING or unreachable"
  fail=$((fail+1))
fi
echo

echo "== Redis ping =="
if docker exec -i dream-forge-redis-1 redis-cli ping 2>/dev/null | grep -q PONG; then
  echo "redis PONG"
  ok=$((ok+1))
else
  echo "redis ping FAILED"
  fail=$((fail+1))
fi
echo

echo "== Postgres connectivity (inside container) =="
if docker exec -e PGPASSWORD=dfs -i dream-forge-postgres-1 psql -U dfs -d dreamforge -tAc 'select 1' 2>/dev/null | grep -q 1; then
  echo "postgres OK"
  ok=$((ok+1))
else
  echo "postgres FAILED"
  fail=$((fail+1))
fi
echo

echo "== MinIO health =="
if curl -fsS "$MINIO_HEALTH" >/dev/null 2>&1; then
  echo "minio ready"
  ok=$((ok+1))
else
  echo "minio health FAILED"
  fail=$((fail+1))
fi
echo

echo "Summary: OK=$ok FAIL=$fail"
test "$fail" = 0
