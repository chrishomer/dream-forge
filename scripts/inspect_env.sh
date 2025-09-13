#!/usr/bin/env bash
set -euo pipefail

echo "== System =="
uname -a || true
if command -v lsb_release >/dev/null 2>&1; then lsb_release -a || true; fi
echo

echo "== Docker =="
docker version || true
echo
docker compose version || true
echo
echo "== Docker info (runtimes) =="
docker info 2>/dev/null | egrep -i "runtimes|default runtime|nvidia|containerd" || true
echo

echo "== NVIDIA Drivers / GPU =="
if command -v nvidia-smi >/dev/null 2>&1; then
  nvidia-smi -L || true
  nvidia-smi || true
else
  echo "nvidia-smi not found"
fi
echo

echo "== NVIDIA Container Toolkit =="
if command -v nvidia-ctk >/dev/null 2>&1; then
  nvidia-ctk --version || true
  echo
  echo "-- CDI devices (via nvidia-ctk) --"
  nvidia-ctk cdi list || true
else
  echo "nvidia-ctk not found"
fi
echo

echo "== CDI Specs on host =="
for d in /etc/cdi /var/run/cdi /var/lib/cdi; do
  if [ -d "$d" ]; then
    echo "Listing: $d"; ls -la "$d" || true; echo
  fi
done

echo "== Kernel groups / user perms =="
id || true
getent group video render 2>/dev/null || true
echo

echo "== Env (DF_* / NVIDIA_*) =="
env | egrep '^(DF_|NVIDIA_)' || true
echo

echo "== Compose GPU hints =="
echo "- Ensure NVIDIA Container Toolkit is installed"
echo "- Ensure CDI spec exists (nvidia-ctk cdi generate ...)"
echo "- Docker Engine >= 24 and Compose v2 recommended"
echo

echo "Done."

