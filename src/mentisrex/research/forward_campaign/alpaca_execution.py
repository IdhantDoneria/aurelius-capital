"""Alpaca paper execution layer for forward evidence accumulation (M29).

Wires AlpacaPaperBroker into the forward campaign cycle:
  - Translates strategy portfolio weights → concrete Alpaca paper orders
  - Captures per-order execution quality (slippage, fill rate, latency)
  - Produces sealed AlpacaCycleExecutionRecord per cycle
  - Reconciles Alpaca positions and NAV vs internal book
  - Never modifies strategy logic, parameters, or sealed ForwardCycleRecords

Design constraints:
  - Sealed records are immutable: once written, never overwritten
  - Idempotent: repeat calls for same cycle_id return the existing record
  - Fail closed: reconciliation failure records FAIL, not SUCCESS
  - No fabrication: unavailable execution fields are explicitly labelled
  - ALPACA PAPER only: AlpacaPaperBroker enforces this structurally
  - Forward observations are evidence, NOT training data
"""

from __future__ import annotations

import dataclasses
import hashlib
import json
import time
from dataclasses import dataclass, field
from datetime import UTC, date, datetime
from decimal import Decimal
from pathlib import Path

# ── execution quality dataclass ───────────────────────────────────────────────


@dataclass(frozen=True)
class AlpacaOrderExecution:
    """Immutable per-order execution quality record.

    Captures everything observable about one Alpaca paper order.
    Fields that cannot be measured are labelled "UNAVAILABLE", not zero.
    Credentials are never stored here.
    """

    # identity
    mentisrex_order_id: str  # = client_order_id
    alpaca_order_id: str  # Alpaca-assigned UUID
    client_order_id: str  # deterministic idempotency key
    cycle_id: str

    # order specification
    symbol: str
    side: str  # "buy" | "sell"
    intended_quantity: str  # from strategy signal (Decimal as str)
    submitted_quantity: str  # actually sent to Alpaca
    filled_quantity: str  # Alpaca-reported filled_qty
    order_type: str  # "market" | "limit"
    time_in_force: str  # "day" | "gtc"

    # prices
    reference_price: str  # strategy reference (Decimal as str; "UNAVAILABLE" if unknown)
    avg_fill_price: str  # Alpaca filled_avg_price ("UNAVAILABLE" if not filled)

    # timing
    submission_timestamp: str  # ISO when submitted to Alpaca
    first_ack_timestamp: str  # Alpaca submitted_at (ISO; "UNAVAILABLE" if absent)
    fill_timestamp: str  # Alpaca filled_at (ISO; "UNAVAILABLE" if not filled)

    # status
    order_status: str  # "filled" | "canceled" | "rejected" | "accepted" | ...
    rejection_reason: str  # non-empty if rejected; "N/A" otherwise

    # quality metrics (UNAVAILABLE as sentinel when not computable)
    slippage_bps: str  # (fill - reference) / reference * 10000 as str, or "UNAVAILABLE"
    slippage_dollars: str  # as str, or "UNAVAILABLE"
    estimated_transaction_cost: str  # as str, or "UNAVAILABLE"
    execution_latency_ms: str  # submission→fill latency in ms, or "UNAVAILABLE"

    # governance (immutable)
    broker: str = "ALPACA"
    environment: str = "PAPER"
    live_execution: str = "NO"
    real_capital: str = "NO"


@dataclass
class CycleExecutionSummary:
    """Cycle-level aggregate execution quality metrics."""

    cycle_id: str = ""

    # counts
    orders_submitted: int = 0
    orders_filled: int = 0
    orders_partial: int = 0
    orders_rejected: int = 0
    orders_canceled: int = 0

    # rates
    fill_rate: float = 0.0  # orders_filled / orders_submitted (or UNAVAILABLE if 0)

    # slippage
    avg_slippage_bps: float = 0.0  # mean slippage across filled orders
    total_slippage_bps: float = 0.0  # sum
    total_slippage_dollars: float = 0.0

    # latency
    avg_execution_latency_ms: float = 0.0  # mean of available fill latencies

    # turnover
    total_notional_traded: float = 0.0
    turnover_vs_nav: float = 0.0  # total_notional / strategy_nav

    # bookkeeping
    unavailable_fields: list = field(default_factory=list)  # list of field names not available
    broker: str = "ALPACA"
    environment: str = "PAPER"
    cycle_start: str = ""
    cycle_end: str = ""


def _compute_execution_summary(
    orders: list[AlpacaOrderExecution],
    cycle_id: str,
    strategy_nav: float = 0.0,
    start: str = "",
    end: str = "",
) -> CycleExecutionSummary:
    """Compute cycle-level execution quality from a list of order executions."""
    s = CycleExecutionSummary(
        cycle_id=cycle_id,
        orders_submitted=len(orders),
        cycle_start=start,
        cycle_end=end,
    )
    if not orders:
        return s

    slippage_bps_vals: list[float] = []
    slippage_dollar_vals: list[float] = []
    latency_vals: list[float] = []
    notional_vals: list[float] = []
    unavail: set[str] = set()

    for o in orders:
        status = o.order_status
        if status == "filled":
            s.orders_filled += 1
        elif status in ("partially_filled",):
            s.orders_partial += 1
        elif status in ("rejected", "expired"):
            s.orders_rejected += 1
        elif status in ("canceled", "cancelled"):
            s.orders_canceled += 1

        # slippage
        if o.slippage_bps == "UNAVAILABLE":
            unavail.add("slippage_bps")
        else:
            try:
                slippage_bps_vals.append(float(o.slippage_bps))
            except (ValueError, TypeError):
                unavail.add("slippage_bps")

        if o.slippage_dollars == "UNAVAILABLE":
            unavail.add("slippage_dollars")
        else:
            try:
                slippage_dollar_vals.append(float(o.slippage_dollars))
            except (ValueError, TypeError):
                unavail.add("slippage_dollars")

        # latency
        if o.execution_latency_ms == "UNAVAILABLE":
            unavail.add("execution_latency_ms")
        else:
            try:
                latency_vals.append(float(o.execution_latency_ms))
            except (ValueError, TypeError):
                unavail.add("execution_latency_ms")

        # notional (from filled qty * fill price)
        try:
            qty = Decimal(o.filled_quantity) if o.filled_quantity != "UNAVAILABLE" else Decimal(0)
            price = Decimal(o.avg_fill_price) if o.avg_fill_price != "UNAVAILABLE" else Decimal(0)
            notional_vals.append(float(qty * price))
        except Exception:
            pass

    if s.orders_submitted > 0:
        filled_and_partial = s.orders_filled + s.orders_partial
        s.fill_rate = filled_and_partial / s.orders_submitted

    if slippage_bps_vals:
        s.avg_slippage_bps = sum(slippage_bps_vals) / len(slippage_bps_vals)
        s.total_slippage_bps = sum(slippage_bps_vals)
    if slippage_dollar_vals:
        s.total_slippage_dollars = sum(slippage_dollar_vals)
    if latency_vals:
        s.avg_execution_latency_ms = sum(latency_vals) / len(latency_vals)
    if notional_vals:
        s.total_notional_traded = sum(notional_vals)
        if strategy_nav > 0:
            s.turnover_vs_nav = s.total_notional_traded / strategy_nav

    s.unavailable_fields = sorted(unavail)
    return s


# ── sealed per-cycle execution record ────────────────────────────────────────


@dataclass
class AlpacaCycleExecutionRecord:
    """Sealed, immutable Alpaca execution record for one forward cycle.

    Stored in {campaign_dir}/alpaca_executions/{cycle_id}.json.
    Once sealed, never overwritten.
    """

    # identity
    cycle_id: str = ""
    campaign_id: str = ""
    strategy_id: str = ""
    strategy_fingerprint: str = ""
    evaluation_date: date | None = None
    knowledge_as_of: date | None = None

    # orders and fills
    orders: list = field(default_factory=list)  # list[dict] — AlpacaOrderExecution.to_dict()
    summary: dict = field(default_factory=dict)  # CycleExecutionSummary serialized

    # reconciliation
    positions_reconciled: bool = False
    nav_reconciled: bool = False
    reconciliation_status: str = ""  # "PASS" | "FAIL" | "NOT_VERIFIED"
    position_mismatches: list = field(default_factory=list)
    nav_delta_bps: float = 0.0
    alpaca_equity: float = 0.0
    internal_nav: float = 0.0
    alpaca_account_id_masked: str = ""  # first 8 chars + "..." only

    # governance
    broker: str = "ALPACA"
    environment: str = "PAPER"
    live_execution: str = "NO"
    real_capital: str = "NO"

    # status
    status: str = "PARTIAL"
    error_message: str = ""
    start_time: str = ""
    end_time: str = ""
    sealed_at: str = ""

    def seal(self, status: str = "SUCCESS") -> None:
        if not self.sealed_at:
            self.status = status
            self.sealed_at = datetime.now(UTC).replace(tzinfo=None).isoformat()

    @property
    def is_sealed(self) -> bool:
        return bool(self.sealed_at)

    def record_fingerprint(self) -> str:
        body = json.dumps(
            {
                "cycle_id": self.cycle_id,
                "orders_submitted": len(self.orders),
                "reconciliation_status": self.reconciliation_status,
                "status": self.status,
            },
            sort_keys=True,
        )
        return hashlib.blake2b(body.encode(), digest_size=16).hexdigest()

    def to_dict(self) -> dict:
        d: dict = {}
        for f in dataclasses.fields(self):
            v = getattr(self, f.name)
            if isinstance(v, date) and not isinstance(v, datetime):
                d[f.name] = v.isoformat()
            else:
                d[f.name] = v
        return d

    @classmethod
    def from_dict(cls, d: dict) -> AlpacaCycleExecutionRecord:
        kw = {k: v for k, v in d.items() if k in {f.name for f in dataclasses.fields(cls)}}
        for dk in ("evaluation_date", "knowledge_as_of"):
            raw = kw.get(dk)
            if isinstance(raw, str) and raw:
                kw[dk] = date.fromisoformat(raw)
        return cls(**kw)


# ── execution ledger (read-only) ──────────────────────────────────────────────


class AlpacaExecutionLedger:
    """Read-only view of sealed Alpaca execution records.

    Reads from {campaign_dir}/alpaca_executions/*.json.
    Never writes.
    """

    _EXEC_DIR = "alpaca_executions"

    def __init__(self, campaign_dir: Path) -> None:
        self._edir = Path(campaign_dir) / self._EXEC_DIR

    def list_cycles(self) -> list[AlpacaCycleExecutionRecord]:
        recs: list[AlpacaCycleExecutionRecord] = []
        if not self._edir.exists():
            return recs
        for p in sorted(self._edir.glob("*.json")):
            try:
                recs.append(AlpacaCycleExecutionRecord.from_dict(json.loads(p.read_text())))
            except Exception:
                continue
        recs.sort(key=lambda r: r.evaluation_date or date.min)
        return recs

    def get_cycle(self, cycle_id: str) -> AlpacaCycleExecutionRecord | None:
        p = self._edir / f"{cycle_id}.json"
        if not p.exists():
            return None
        try:
            return AlpacaCycleExecutionRecord.from_dict(json.loads(p.read_text()))
        except Exception:
            return None

    def latest_cycle(self) -> AlpacaCycleExecutionRecord | None:
        success = [c for c in self.list_cycles() if c.status == "SUCCESS"]
        return success[-1] if success else None

    def execution_quality_summary(self) -> dict:
        """Aggregate execution quality across all sealed cycles."""
        cycles = [c for c in self.list_cycles() if c.status == "SUCCESS"]
        if not cycles:
            return {
                "n_cycles": 0,
                "total_orders": 0,
                "total_filled": 0,
                "overall_fill_rate": "UNAVAILABLE",
                "avg_slippage_bps": "UNAVAILABLE",
                "avg_latency_ms": "UNAVAILABLE",
                "reconciliation_pass_rate": "UNAVAILABLE",
            }

        total_submitted = 0
        total_filled = 0
        slippage_vals: list[float] = []
        latency_vals: list[float] = []
        recon_pass = 0

        for c in cycles:
            s = c.summary
            if isinstance(s, dict):
                total_submitted += s.get("orders_submitted", 0)
                total_filled += s.get("orders_filled", 0)
                bps = s.get("avg_slippage_bps", 0.0)
                if bps and bps != 0:
                    slippage_vals.append(float(bps))
                lat = s.get("avg_execution_latency_ms", 0.0)
                if lat and lat != 0:
                    latency_vals.append(float(lat))
            if c.reconciliation_status == "PASS":
                recon_pass += 1

        return {
            "n_cycles": len(cycles),
            "total_orders_submitted": total_submitted,
            "total_orders_filled": total_filled,
            "overall_fill_rate": (
                total_filled / total_submitted if total_submitted > 0 else "UNAVAILABLE"
            ),
            "avg_slippage_bps": (
                sum(slippage_vals) / len(slippage_vals) if slippage_vals else "UNAVAILABLE"
            ),
            "avg_latency_ms": (
                sum(latency_vals) / len(latency_vals) if latency_vals else "UNAVAILABLE"
            ),
            "reconciliation_pass_rate": (recon_pass / len(cycles) if cycles else "UNAVAILABLE"),
        }


# ── executor ──────────────────────────────────────────────────────────────────


class AlpacaCycleExecutor:
    """Translate a ForwardCycleRecord's portfolio weights into Alpaca paper orders.

    Usage:
        executor = AlpacaCycleExecutor(campaign_dir, broker)
        exec_rec = executor.execute_cycle(cycle_record, spy_prices={...})

    The executor:
      1. Reads portfolio_weights from the sealed ForwardCycleRecord
      2. Fetches current Alpaca positions (from prior execution if any)
      3. Computes required trades (target shares - current shares)
      4. Submits orders to AlpacaPaperBroker
      5. Polls for fill status
      6. Reconciles positions and NAV
      7. Produces and seals AlpacaCycleExecutionRecord

    Never modifies the ForwardCycleRecord.
    Idempotent: if an execution record for the cycle already exists, returns it.
    """

    _EXEC_DIR = "alpaca_executions"
    _POLL_INTERVAL_S = 2.0
    _POLL_TIMEOUT_S = 30.0

    def __init__(
        self,
        campaign_dir: Path,
        broker,  # AlpacaPaperBroker
        *,
        max_order_shares: Decimal = Decimal("10000"),
    ) -> None:
        self._campaign_dir = Path(campaign_dir)
        self._broker = broker
        self._exec_dir = self._campaign_dir / self._EXEC_DIR
        self._exec_dir.mkdir(parents=True, exist_ok=True)
        self._ledger = AlpacaExecutionLedger(self._campaign_dir)
        self._max_order_shares = max_order_shares

    def execute_cycle(
        self,
        cycle_record,  # ForwardCycleRecord
        *,
        spot_prices: dict[str, float] | None = None,
    ) -> AlpacaCycleExecutionRecord:
        """Execute Alpaca paper orders for a sealed ForwardCycleRecord.

        Args:
            cycle_record: Sealed ForwardCycleRecord with portfolio_weights.
            spot_prices: Map of symbol → reference price. Used to compute
                         target shares and measure slippage. If None,
                         slippage is labelled UNAVAILABLE.

        Returns:
            Sealed AlpacaCycleExecutionRecord.
        """
        cycle_id = cycle_record.cycle_id

        # idempotency — return existing if sealed
        existing = self._load_sealed(cycle_id)
        if existing is not None:
            return existing

        start_time = datetime.now(UTC).replace(tzinfo=None).isoformat()
        rec = AlpacaCycleExecutionRecord(
            cycle_id=cycle_id,
            campaign_id=cycle_record.campaign_id,
            strategy_id=cycle_record.strategy_id,
            strategy_fingerprint=cycle_record.strategy_fingerprint,
            evaluation_date=cycle_record.evaluation_date,
            knowledge_as_of=cycle_record.knowledge_as_of,
            start_time=start_time,
        )

        try:
            order_executions = self._submit_portfolio(cycle_record, spot_prices or {})
            rec.orders = [dataclasses.asdict(o) for o in order_executions]

            summary = _compute_execution_summary(
                order_executions,
                cycle_id=cycle_id,
                strategy_nav=float(cycle_record.ending_nav),
                start=start_time,
                end=datetime.now(UTC).replace(tzinfo=None).isoformat(),
            )
            rec.summary = dataclasses.asdict(summary)

            # reconcile positions
            expected = {s: float(q) for s, q in cycle_record.positions.items() if float(q) != 0}
            pos_result = self._broker.reconcile_positions(expected)
            rec.positions_reconciled = pos_result.ok
            rec.position_mismatches = [
                {"expected": str(e), "actual": str(a), "symbol": sym}
                for sym, e, a in (pos_result.differences or [])
            ]

            # reconcile NAV
            nav_result = self._broker.reconcile_nav(float(cycle_record.ending_nav))
            rec.nav_reconciled = nav_result.ok
            rec.nav_delta_bps = nav_result.delta_bps
            rec.alpaca_equity = nav_result.alpaca_equity
            rec.internal_nav = nav_result.internal_nav

            # get masked account ID
            try:
                acc = self._broker.get_account()
                rec.alpaca_account_id_masked = acc.get("account_id_masked", "")
            except Exception:
                rec.alpaca_account_id_masked = "UNAVAILABLE"

            # reconciliation status
            if pos_result.ok and nav_result.ok:
                rec.reconciliation_status = "PASS"
            else:
                rec.reconciliation_status = "FAIL"

            rec.end_time = datetime.now(UTC).replace(tzinfo=None).isoformat()
            rec.seal("SUCCESS")

        except Exception as exc:
            rec.error_message = str(exc)
            rec.reconciliation_status = "FAIL"
            rec.end_time = datetime.now(UTC).replace(tzinfo=None).isoformat()
            rec.seal("FAILED")

        self._persist(rec)
        return rec

    def _submit_portfolio(
        self,
        cycle_record,
        spot_prices: dict[str, float],
    ) -> list[AlpacaOrderExecution]:
        """Compute required trades from portfolio weights and submit to Alpaca."""
        weights: dict[str, float] = dict(cycle_record.portfolio_weights or {})
        nav = float(cycle_record.ending_nav or 0.0)

        # get current Alpaca positions
        try:
            acc = self._broker.get_account()
            alpaca_positions: dict[str, float] = {
                k: float(v) for k, v in acc.get("positions", {}).items()
            }
        except Exception:
            alpaca_positions = {}

        executions: list[AlpacaOrderExecution] = []
        seq = 0

        for symbol, weight in weights.items():
            ref_price = spot_prices.get(symbol)
            if ref_price is None or ref_price <= 0:
                continue

            target_shares = (nav * weight) / ref_price
            current_shares = alpaca_positions.get(symbol, 0.0)
            delta = target_shares - current_shares

            if abs(delta) < 0.01:
                continue

            side = "buy" if delta > 0 else "sell"
            qty = Decimal(str(abs(round(delta, 6))))
            if qty <= 0:
                continue
            if qty > self._max_order_shares:
                qty = self._max_order_shares

            seq += 1
            exec_rec = self._submit_one(
                symbol=symbol,
                side=side,
                qty=qty,
                ref_price=Decimal(str(ref_price)),
                cycle_id=cycle_record.cycle_id,
                seq=seq,
            )
            executions.append(exec_rec)

        return executions

    def _submit_one(
        self,
        symbol: str,
        side: str,
        qty: Decimal,
        ref_price: Decimal,
        cycle_id: str,
        seq: int,
    ) -> AlpacaOrderExecution:
        """Submit one order and return an execution quality record."""
        submission_ts = datetime.now(UTC).replace(tzinfo=None).isoformat()
        try:
            order_rec = self._broker.submit_order(
                symbol=symbol,
                side=side,
                quantity=qty,
                order_type="market",
                cycle_id=cycle_id,
                risk_approved=True,
                seq=seq,
            )
        except Exception as exc:
            return AlpacaOrderExecution(
                mentisrex_order_id="UNAVAILABLE",
                alpaca_order_id="UNAVAILABLE",
                client_order_id="UNAVAILABLE",
                cycle_id=cycle_id,
                symbol=symbol,
                side=side,
                intended_quantity=str(qty),
                submitted_quantity="0",
                filled_quantity="0",
                order_type="market",
                time_in_force="day",
                reference_price=str(ref_price),
                avg_fill_price="UNAVAILABLE",
                submission_timestamp=submission_ts,
                first_ack_timestamp="UNAVAILABLE",
                fill_timestamp="UNAVAILABLE",
                order_status="rejected",
                rejection_reason=str(exc)[:200],
                slippage_bps="UNAVAILABLE",
                slippage_dollars="UNAVAILABLE",
                estimated_transaction_cost="UNAVAILABLE",
                execution_latency_ms="UNAVAILABLE",
            )

        ack_ts = order_rec.submitted_at or "UNAVAILABLE"
        alpaca_id = order_rec.alpaca_order_id
        client_id = order_rec.client_order_id

        # poll for fill (best-effort within timeout)
        fill_ts = "UNAVAILABLE"
        fill_qty = "0"
        fill_price = "UNAVAILABLE"
        final_status = order_rec.status
        t0 = time.monotonic()
        while time.monotonic() - t0 < self._POLL_TIMEOUT_S:
            try:
                status_data = self._broker.get_order_status(alpaca_id)
                final_status = status_data.get("status", final_status)
                if final_status in ("filled", "partially_filled"):
                    fill_qty = str(status_data.get("filled_qty", "0"))
                    fill_price = str(status_data.get("filled_avg_price", "UNAVAILABLE"))
                    fill_ts = str(status_data.get("filled_at", "UNAVAILABLE"))
                    break
                if final_status in ("canceled", "cancelled", "rejected", "expired"):
                    break
            except Exception:
                break
            time.sleep(self._POLL_INTERVAL_S)

        # compute slippage
        slippage_bps = "UNAVAILABLE"
        slippage_dollars = "UNAVAILABLE"
        if fill_price != "UNAVAILABLE" and ref_price > 0:
            try:
                fp = Decimal(fill_price)
                rp = ref_price
                slip_per_share = fp - rp if side == "buy" else rp - fp
                slip_bps = float(slip_per_share / rp * 10000)
                fq = Decimal(fill_qty) if fill_qty != "UNAVAILABLE" else Decimal("0")
                slip_dollars = float(slip_per_share * fq)
                slippage_bps = str(round(slip_bps, 4))
                slippage_dollars = str(round(slip_dollars, 6))
            except Exception:
                pass

        # execution latency
        latency_ms = "UNAVAILABLE"
        if ack_ts != "UNAVAILABLE" and fill_ts != "UNAVAILABLE":
            try:
                t_sub = datetime.fromisoformat(ack_ts.replace("Z", "+00:00"))
                t_fill = datetime.fromisoformat(fill_ts.replace("Z", "+00:00"))
                latency_ms = str(round((t_fill - t_sub).total_seconds() * 1000, 1))
            except Exception:
                pass

        return AlpacaOrderExecution(
            mentisrex_order_id=client_id,
            alpaca_order_id=alpaca_id,
            client_order_id=client_id,
            cycle_id=cycle_id,
            symbol=symbol,
            side=side,
            intended_quantity=str(qty),
            submitted_quantity=str(qty),
            filled_quantity=fill_qty,
            order_type="market",
            time_in_force="day",
            reference_price=str(ref_price),
            avg_fill_price=fill_price,
            submission_timestamp=submission_ts,
            first_ack_timestamp=ack_ts,
            fill_timestamp=fill_ts,
            order_status=final_status,
            rejection_reason="N/A",
            slippage_bps=slippage_bps,
            slippage_dollars=slippage_dollars,
            estimated_transaction_cost="UNAVAILABLE",  # ponytail: no fee data from paper API
            execution_latency_ms=latency_ms,
        )

    def _load_sealed(self, cycle_id: str) -> AlpacaCycleExecutionRecord | None:
        p = self._exec_dir / f"{cycle_id}.json"
        if not p.exists():
            return None
        try:
            r = AlpacaCycleExecutionRecord.from_dict(json.loads(p.read_text()))
            return r if r.is_sealed else None
        except Exception:
            return None

    def _persist(self, rec: AlpacaCycleExecutionRecord) -> None:
        target = self._exec_dir / f"{rec.cycle_id}.json"
        if target.exists():
            return  # never overwrite sealed record
        tmp = target.with_suffix(".tmp")
        tmp.write_text(json.dumps(rec.to_dict(), indent=2, default=str))
        tmp.rename(target)


# ── structured forward vs backtest comparison ─────────────────────────────────


@dataclass(frozen=True)
class ForwardVsBacktestComparison:
    """Structured BACKTEST / FORWARD / DIFFERENCE comparison table.

    Fields are None when sample is insufficient or metric not available.
    Labels explicitly state INSUFFICIENT_SAMPLE.
    """

    n_forward_observations: int
    n_backtest_observations: int
    comparison_validity: str  # "INSUFFICIENT_SAMPLE" | "PRELIMINARY"

    # returns
    backtest_annualized_return: float | None
    forward_annualized_return: float | None
    annualized_return_diff: float | None
    annualized_return_label: str

    # Sharpe
    backtest_sharpe: float | None
    forward_sharpe: float | None
    sharpe_diff: float | None
    sharpe_label: str

    # volatility
    backtest_volatility: float | None
    forward_volatility: float | None
    volatility_diff: float | None
    volatility_label: str

    # drawdown
    backtest_max_drawdown: float | None
    forward_max_drawdown: float | None
    drawdown_diff: float | None

    # governance
    note: str = (
        "Forward data must NOT be used to recalibrate backtest parameters. "
        "Comparison is observational only."
    )
    strategy_modified: str = "NO"

    def print_table(self) -> None:
        """Print a BACKTEST / FORWARD / DIFFERENCE table."""
        print()
        print("G. FORWARD VS BACKTEST COMPARISON")
        print(f"  n_forward_obs : {self.n_forward_observations}")
        print(f"  n_backtest_obs: {self.n_backtest_observations} (daily)")
        print(f"  validity      : {self.comparison_validity}")
        print()
        print(f"  {'Metric':<28} {'Backtest':>12} {'Forward':>12} {'Diff':>12}  Label")
        print(f"  {'-' * 70}")

        def _fmt(v):
            if v is None:
                return "N/A"
            if isinstance(v, float):
                return f"{v:.4%}" if abs(v) < 100 else f"{v:.3f}"
            return str(v)

        rows = [
            (
                "annualized_return",
                self.backtest_annualized_return,
                self.forward_annualized_return,
                self.annualized_return_diff,
                self.annualized_return_label,
            ),
            (
                "sharpe",
                self.backtest_sharpe,
                self.forward_sharpe,
                self.sharpe_diff,
                self.sharpe_label,
            ),
            (
                "volatility",
                self.backtest_volatility,
                self.forward_volatility,
                self.volatility_diff,
                self.volatility_label,
            ),
            (
                "max_drawdown",
                self.backtest_max_drawdown,
                self.forward_max_drawdown,
                self.drawdown_diff,
                "",
            ),
        ]
        for label, bt, fwd, diff, lbl in rows:
            print(f"  {label:<28} {_fmt(bt):>12} {_fmt(fwd):>12} {_fmt(diff):>12}  {lbl}")
        print()
        print(f"  NOTE: {self.note}")


def build_forward_vs_backtest_comparison(
    backtest,  # BacktestSnapshot
    fwd_summary,  # ForwardPerformanceSummary
) -> ForwardVsBacktestComparison:
    """Build a structured comparison from existing summaries.

    Never recalibrates the backtest. Uses forward values only when sample allows.
    """
    n_fwd = fwd_summary.n_successful_cycles
    n_bt = backtest.n_observations

    # validity
    if n_fwd < 12:
        validity = "INSUFFICIENT_SAMPLE"
    else:
        validity = "PRELIMINARY"

    # annualized return
    fwd_ann = fwd_summary.annualized_return  # None if insufficient
    bt_ann = backtest.annualized_return
    ann_diff = (fwd_ann - bt_ann) if (fwd_ann is not None) else None
    ann_label = fwd_summary.annualized_return_label

    # Sharpe
    fwd_sharpe = fwd_summary.sharpe  # None if insufficient
    bt_sharpe = backtest.sharpe_annualized
    sharpe_diff = (fwd_sharpe - bt_sharpe) if (fwd_sharpe is not None) else None
    sharpe_label = fwd_summary.sharpe_label

    # volatility
    fwd_vol = fwd_summary.volatility
    bt_vol = backtest.annualized_volatility
    vol_diff = (fwd_vol - bt_vol) if (fwd_vol is not None) else None
    vol_label = fwd_summary.volatility_label

    # drawdown — backtest doesn't report MDD; leave None
    fwd_mdd = fwd_summary.max_drawdown if fwd_summary.max_drawdown > 0 else None

    return ForwardVsBacktestComparison(
        n_forward_observations=n_fwd,
        n_backtest_observations=n_bt,
        comparison_validity=validity,
        backtest_annualized_return=bt_ann,
        forward_annualized_return=fwd_ann,
        annualized_return_diff=ann_diff,
        annualized_return_label=ann_label,
        backtest_sharpe=bt_sharpe,
        forward_sharpe=fwd_sharpe,
        sharpe_diff=sharpe_diff,
        sharpe_label=sharpe_label,
        backtest_volatility=bt_vol,
        forward_volatility=fwd_vol,
        volatility_diff=vol_diff,
        volatility_label=vol_label,
        backtest_max_drawdown=None,  # not in BacktestSnapshot
        forward_max_drawdown=fwd_mdd,
        drawdown_diff=None,
    )
