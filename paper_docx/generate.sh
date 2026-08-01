#!/usr/bin/env bash
# generate.sh — single entry point for the question-paper pipeline.
#
# Usage:
#   ./generate.sh <config.json> <outdir>
#
# Requires:
#   - questions.db and images/ in QUESTION_BANK_DIR (set below or via env var)
#   - python3, node (with docx + image-size installed in this pipeline dir)
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
QUESTION_BANK_DIR="${QUESTION_BANK_DIR:-/sessions/great-gifted-franklin/mnt/QUESTION_BANK}"
CONFIG="${1:?Usage: generate.sh <config.json> <outdir>}"
OUTDIR="${2:-$SCRIPT_DIR/out}"

mkdir -p "$OUTDIR"

echo "== Stage 1: selecting questions =="
python3 "$SCRIPT_DIR/select_questions.py" \
  --db "$QUESTION_BANK_DIR/questions.db" \
  --config "$CONFIG" \
  --image-base "$QUESTION_BANK_DIR" \
  --out "$OUTDIR/paper_content.json"

echo
echo "== Stage 2: rendering docx files =="
cd "$SCRIPT_DIR"
node build_docx.js "$OUTDIR/paper_content.json" --outdir "$OUTDIR"

echo
echo "Done. Files in $OUTDIR"
