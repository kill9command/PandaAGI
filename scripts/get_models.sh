#!/usr/bin/env bash
set -euo pipefail

# Downloads selected HF models into a local models directory for offline/explicit use.
# Usage: bash scripts/get_models.sh

ROOT_DIR=$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)
DEST_DIR="${1:-$ROOT_DIR/models}"
mkdir -p "$DEST_DIR"

# Defaults — adjust as desired
SOLVER_REPO=${SOLVER_REPO:-"QuantTrio/Qwen3-Coder-30B-A3B-Instruct-AWQ"}
THINK_REPO=${THINK_REPO:-"unsloth/Qwen3-4B-Instruct-2507"}

echo "[dl] destination: $DEST_DIR"
echo "[dl] solver repo: $SOLVER_REPO"
echo "[dl] thinker repo: $THINK_REPO"

have_hf() { command -v huggingface-cli >/dev/null 2>&1; }
have_python() { command -v python >/dev/null 2>&1; }

download_repo() {
  local repo="$1"; local out="$2"
  mkdir -p "$out"
  if have_hf; then
    echo "[dl] huggingface-cli download $repo → $out"
    huggingface-cli download "$repo" --local-dir "$out" --resume-download || true
  elif have_python; then
    echo "[dl] python snapshot_download $repo → $out"
    python - <<PY || true
from huggingface_hub import snapshot_download
snapshot_download(repo_id="$repo", local_dir=r"$out", resume_download=True)
print("OK")
PY
  else
    echo "[dl] ERROR: neither huggingface-cli nor python available." >&2
    exit 1
  fi
}

download_repo "$SOLVER_REPO" "$DEST_DIR/solver"
download_repo "$THINK_REPO" "$DEST_DIR/thinker"

echo "[dl] done. Set env for vLLM start script, e.g.:"
echo "  export VLLM_SOLVER_MODEL_PATH=$DEST_DIR/solver"
echo "  export VLLM_THINK_MODEL_PATH=$DEST_DIR/thinker"
echo "Then: bash scripts/vllm_start.sh"

