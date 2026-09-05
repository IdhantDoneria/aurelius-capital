"""Lean (QuantConnect) compatibility exporter (AIDP M21).

Exports Mentisrex research outputs — universe, signals, portfolio targets, OHLCV — into
Lean-compatible directory/file structures. Does NOT depend on the Lean runtime or any
QuantConnect library.

Lean daily equity data format:
    data/equity/usa/daily/<ticker>.zip  containing  <ticker>.csv
    CSV columns (no header): date,open,high,low,close,volume  (values in 10000ths of a dollar)

Universe file format:
    date,<ticker1>,<ticker2>,...   (one row per day)

Signal/alpha model format:
    date,ticker,signal_name,value   (one row per ticker per signal per day)

Portfolio targets format:
    date,ticker,weight   (one row per ticker per day; weights sum to 1)
"""

from __future__ import annotations

import csv
import io
import zipfile
from collections import defaultdict
from dataclasses import dataclass
from datetime import date
from pathlib import Path


@dataclass(frozen=True)
class LeanOHLCV:
    date: date
    ticker: str
    open: float
    high: float
    low: float
    close: float
    volume: float


class LeanExporter:
    """Export Mentisrex research outputs to Lean-compatible structures.

    No Lean runtime dependency. Output is pure filesystem / in-memory CSV.
    """

    # ── OHLCV ────────────────────────────────────────────────────────────────

    def export_ohlcv(
        self,
        observations,
        output_dir: str | Path,
        *,
        market: str = "usa",
        resolution: str = "daily",
    ) -> dict[str, Path]:
        """Export CanonicalObservation sequences as Lean daily equity zip files.

        Values are stored in Lean's integer format: (price * 10000).
        Returns {ticker: path} for each written zip file.
        """
        root = Path(output_dir) / "data" / "equity" / market / resolution
        root.mkdir(parents=True, exist_ok=True)

        # group observations by security_id, pivot to OHLCV rows
        by_ticker: dict = defaultdict(dict)  # ticker → {date → {field: value}}
        for obs in observations:
            if obs.field not in ("open", "high", "low", "close", "volume"):
                continue
            by_ticker[obs.security_id].setdefault(obs.effective_date, {})[obs.field] = obs.value

        written = {}
        for ticker, date_rows in sorted(by_ticker.items()):
            safe_ticker = ticker.lower().replace("/", "_").replace(":", "_")
            rows = []
            for d in sorted(date_rows):
                row = date_rows[d]
                close = row.get("close", 0.0)
                # Lean uses 10000ths of a dollar for equity; volume is raw shares
                rows.append(
                    [
                        d.strftime("%Y%m%d 00:00"),
                        int(row.get("open", close) * 10000),
                        int(row.get("high", close) * 10000),
                        int(row.get("low", close) * 10000),
                        int(close * 10000),
                        int(row.get("volume", 0)),
                    ]
                )

            zip_path = root / f"{safe_ticker}.zip"
            buf = io.StringIO()
            writer = csv.writer(buf)
            writer.writerows(rows)
            with zipfile.ZipFile(zip_path, "w", zipfile.ZIP_DEFLATED) as zf:
                zf.writestr(f"{safe_ticker}.csv", buf.getvalue())
            written[ticker] = zip_path

        return written

    # ── Universe ─────────────────────────────────────────────────────────────

    def export_universe(
        self,
        universe_by_date: dict,
        output_path: str | Path,
    ) -> Path:
        """Export universe membership to a Lean-compatible universe CSV.

        universe_by_date: {date: [ticker, ...]}
        """
        out = Path(output_path)
        out.parent.mkdir(parents=True, exist_ok=True)
        rows = []
        for d in sorted(universe_by_date):
            tickers = sorted(universe_by_date[d])
            rows.append([d.isoformat(), *tickers])
        with open(out, "w", newline="") as f:
            csv.writer(f).writerows(rows)
        return out

    # ── Signals ──────────────────────────────────────────────────────────────

    def export_signals(
        self,
        signals: list[dict],
        output_path: str | Path,
    ) -> Path:
        """Export signals to Lean alpha model CSV format.

        signals: [{"date": date, "ticker": str, "signal_name": str, "value": float}]
        """
        out = Path(output_path)
        out.parent.mkdir(parents=True, exist_ok=True)
        sorted_signals = sorted(
            signals,
            key=lambda s: (str(s.get("date")), str(s.get("ticker")), str(s.get("signal_name"))),
        )
        with open(out, "w", newline="") as f:
            writer = csv.DictWriter(f, fieldnames=["date", "ticker", "signal_name", "value"])
            writer.writeheader()
            for s in sorted_signals:
                writer.writerow(
                    {
                        "date": s["date"].isoformat() if isinstance(s["date"], date) else s["date"],
                        "ticker": s["ticker"],
                        "signal_name": s["signal_name"],
                        "value": s["value"],
                    }
                )
        return out

    # ── Portfolio targets ─────────────────────────────────────────────────────

    def export_targets(
        self,
        targets: list[dict],
        output_path: str | Path,
    ) -> Path:
        """Export portfolio targets to Lean format.

        targets: [{"date": date, "ticker": str, "weight": float}]
        """
        out = Path(output_path)
        out.parent.mkdir(parents=True, exist_ok=True)
        sorted_targets = sorted(targets, key=lambda t: (str(t.get("date")), str(t.get("ticker"))))
        with open(out, "w", newline="") as f:
            writer = csv.DictWriter(f, fieldnames=["date", "ticker", "weight"])
            writer.writeheader()
            for t in sorted_targets:
                writer.writerow(
                    {
                        "date": t["date"].isoformat() if isinstance(t["date"], date) else t["date"],
                        "ticker": t["ticker"],
                        "weight": round(float(t["weight"]), 8),
                    }
                )
        return out
