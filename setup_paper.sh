#!/usr/bin/env bash
#
# setup_paper.sh — one-time server setup for the question-paper engine.
# Run from the omr_project root on the Ubuntu server:  bash setup_paper.sh
#
set -euo pipefail
cd "$(dirname "$0")"

echo "==> [1/4] Node.js (for the docx builder)"
if ! command -v node >/dev/null 2>&1; then
  sudo apt-get update
  sudo apt-get install -y nodejs npm
fi
node --version

echo "==> [2/4] weasyprint system libs + Devanagari fonts (for the metadata PDF)"
# Core libs weasyprint needs at runtime (Pango does the text shaping).
sudo apt-get install -y libpango-1.0-0 libpangocairo-1.0-0 libcairo2 libffi-dev
# Fonts: Latin + Devanagari. Package names vary across Ubuntu releases, so try a
# few and skip any that aren't available (fonts-noto-core carries Noto Sans +
# Noto Sans Devanagari; fonts-deva is the Devanagari metapackage).
for pkg in fonts-noto-core fonts-deva fonts-indic; do
  sudo apt-get install -y "$pkg" || echo "   (skipped $pkg — not in this release's repos)"
done

echo "==> [3/4] Node deps for the docx builder"
( cd paper_docx && npm install --omit=dev )

echo "==> [4/4] Python deps in the omr venv (openpyxl + weasyprint)"
# The OMR venv already has these if the OMR pipeline runs; re-running is safe.
./venv/bin/pip install -r paper_engine/requirements.txt

echo
echo "Done. Verify:"
echo "  ./venv/bin/python -c 'import openpyxl, weasyprint; print(\"py deps OK\")'"
echo "  node paper_docx/build_docx.js  # should print usage"
echo "Then set the PAPER_* env vars in the sms .env (see DEPLOY_PAPER.md)."
