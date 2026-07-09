#!/bin/bash
# run_w1c_certification.sh -- Execute W1c K-batch certification runner for #372
#
# Usage:
#   export EMBER_SHARD_DIR=/path/to/shards
#   bash scripts/w2_heldout/run_w1c_certification.sh [--k 10] [--estimate-only]
#
# Outputs:
#   - Index build receipt
#   - K batch receipts
#   - Per-batch SHAs for PR body

set -euo pipefail

REPO_ROOT=$(cd "$(dirname "$0")/../.." && pwd)
SHARD_DIR="${EMBER_SHARD_DIR:-}"
K="${K:-10}"
ESTIMATE_ONLY="${ESTIMATE_ONLY:-false}"

if [ -z "$SHARD_DIR" ]; then
    echo "ERROR: EMBER_SHARD_DIR not set"
    exit 1
fi

echo "=========================================="
echo "W1c Certification Runner (#372)"
echo "=========================================="
echo "Shard dir: $SHARD_DIR"
echo "K batches: $K"
echo ""

# Estimate index build time
echo "Estimating index build wall-time..."
CORPUS_SIZE=$(du -s "$SHARD_DIR" | awk '{print $1}')
CORPUS_TOKENS=$((CORPUS_SIZE * 512))  # 2 bytes/token
SAMPLE_STEP=10
WINDOWS_TO_SCAN=$((CORPUS_TOKENS / 1024 / SAMPLE_STEP))

# Rule of thumb: ~0.001s per window on this machine
ESTIMATED_INDEX_WALL_S=$(echo "scale=1; $WINDOWS_TO_SCAN * 0.001" | bc)

echo "  Corpus size: $CORPUS_SIZE KB = $CORPUS_TOKENS tokens"
echo "  Windows to scan (step=$SAMPLE_STEP): $WINDOWS_TO_SCAN"
echo "  Estimated wall-time: ${ESTIMATED_INDEX_WALL_S}s"

if (( $(echo "$ESTIMATED_INDEX_WALL_S > 5400" | bc -l) )); then
    echo ""
    echo "WARNING: Index build projects >${ESTIMATED_INDEX_WALL_S}s (>90 min)"
    echo "Checkpointing and stopping per #372 runtime cap."
    echo ""
    echo "To proceed with caution, set FORCE_PROCEED=1:"
    echo "  FORCE_PROCEED=1 bash $0"
    exit 1
fi

if [ "$ESTIMATE_ONLY" = "true" ]; then
    echo ""
    echo "Estimate-only mode; exiting."
    exit 0
fi

echo ""
echo "Index build wall-time acceptable (${ESTIMATED_INDEX_WALL_S}s < 5400s)"
echo ""

# Run the K-batch builder
cd "$REPO_ROOT"
python -u scripts/w2_heldout/build_k_certified_batches.py \
    --shard-dir "$SHARD_DIR" \
    --k "$K"

echo ""
echo "=========================================="
echo "Certification complete. Check outputs above."
echo "=========================================="
