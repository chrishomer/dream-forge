#!/usr/bin/env bash
set -euo pipefail

DRY_RUN="${DRY_RUN:-0}"
OUT_DIR="${CDI_OUT_DIR:-/etc/cdi}"

run() {
  if [ "$DRY_RUN" = "1" ]; then
    echo "DRY_RUN: $*"
  else
    eval "$@"
  fi
}

echo "== Generating NVIDIA CDI spec =="

if ! command -v nvidia-ctk >/dev/null 2>&1; then
  echo "Error: nvidia-ctk not found. Install NVIDIA Container Toolkit first." >&2
  exit 1
fi

if ! command -v nvidia-smi >/dev/null 2>&1; then
  echo "Warning: nvidia-smi not found; GPU drivers may be missing." >&2
fi

echo "Creating output dir: $OUT_DIR (may require sudo)"
run "sudo mkdir -p '$OUT_DIR'"

echo "Generating CDI spec to $OUT_DIR/nvidia.yaml"
run "sudo nvidia-ctk cdi generate --output-file '$OUT_DIR/nvidia.yaml'"

echo "Listing CDI devices"
run "nvidia-ctk cdi list || true"

cat <<'NOTE'

Optional: configure the NVIDIA container runtime to prefer CDI mode.
  sudo nvidia-ctk config --in-place --set nvidia-container-runtime.mode=cdi
  sudo systemctl restart docker

With Docker Compose, request GPUs in a service by setting:
  runtime: nvidia
  environment:
    NVIDIA_VISIBLE_DEVICES: nvidia.com/gpu=all
    NVIDIA_DRIVER_CAPABILITIES: compute,utility

NOTE

echo "Done."

