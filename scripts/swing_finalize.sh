#!/usr/bin/env bash
# Post-download pipeline: panel -> features -> cone -> campaign -> documents.
# One entry point so the whole thing can be re-run from raw bars.
set -euo pipefail

ROOT=/Users/idhantdoneria/mentisrex-capital
WT="$ROOT/.claude/worktrees/swing-trading-strategy-d9b2f0"
PY="$ROOT/.venv/bin/python"
export PYTHONPATH="$WT/src"

START=${START:-2020-01-01}
END=${END:-2026-08-24}
DESIGN_END=${DESIGN_END:-2023-12-31}
AUM=${AUM:-50e6}

cd "$ROOT"

echo "== panel =="
# 6GB, not the default: this machine has 16GB of RAM and about 11GB of free
# disk, so a larger limit trades a swap storm for a spill that could fill the
# volume.
$PY "$WT/scripts/intraday_build_panel.py" \
    --glob 'data/intraday/bars_rth/*.parquet' --interval 15 \
    --memory 6GB --out data/intraday/panel.parquet

echo "== features =="
$PY - <<'PYEOF'
from mentisrex.swing.features import build
from pathlib import Path
D = Path("data/intraday")
build(panel=D / "panel.parquet", out=D / "features.parquet", threads=6, memory="6GB")
PYEOF

echo "== cone =="
$PY - <<'PYEOF'
from mentisrex.swing.cone import build
build(bars="data/intraday/bars_rth/*.parquet",
      panel="data/intraday/panel.parquet",
      out="data/intraday/cone.parquet", threads=6, memory="6GB")
PYEOF

echo "== campaign =="
$PY "$WT/scripts/swing_run_campaign.py" \
    --features data/intraday/features.parquet \
    --cone data/intraday/cone.parquet \
    --start "$START" --end "$END" --design-end "$DESIGN_END" --aum "$AUM"

echo "== documents =="
$PY "$WT/scripts/swing_write_reports.py" \
    --templates "$WT"/docs/SWING_PROGRAMME_COMPARISON.template.md \
                "$WT"/docs/SWING_STRATEGY_SELECTED.template.md

rm -rf data/intraday/duckdb_tmp
echo "== done =="
