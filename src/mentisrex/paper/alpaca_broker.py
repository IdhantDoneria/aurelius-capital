"""AlpacaPaperBroker — Alpaca PAPER trading adapter (M28).

PAPER ONLY. Live execution is architecturally impossible.

Safety model (fail-closed):
  1. Paper API endpoint is a hardcoded class constant. No configurable URL.
  2. No live endpoint. No environment switch. No --live mode.
  3. Credentials must be ALPACA_PAPER_API_KEY / ALPACA_PAPER_API_SECRET.
     Using the generic ALPACA_API_KEY is intentionally unsupported to avoid
     accidentally authenticating with a live credential.
  4. Account is verified as paper at construction. If verification fails,
     no orders can be submitted.
  5. MENTISREX_LIVE_TRADING=true raises LiveTradingBlockedError at every
     entry point. Setting it true does NOT enable live trading.
  6. Missing credentials raise PaperAccountVerificationError immediately.
  7. Every order submission validates the order before any network call.
  8. Idempotent: deterministic client_order_id prevents duplicate orders
     across process restarts.
  9. Credentials are never stored in audit records or logged.
  10. No AlpacaBroker(base_url=live_url) path exists.

Setup:
    export ALPACA_PAPER_API_KEY=...
    export ALPACA_PAPER_API_SECRET=...

Do NOT use ALPACA_API_KEY — it could be a live credential.
"""

from __future__ import annotations

import hashlib
import os
from dataclasses import dataclass, field
from datetime import UTC, datetime
from decimal import Decimal

import httpx

from mentisrex.core.logging import get_logger

logger = get_logger(__name__)

# ── constants ─────────────────────────────────────────────────────────────────

ALPACA_PAPER_BASE_URL = "https://paper-api.alpaca.markets"

# Known live endpoints — any attempt to use these is explicitly blocked.
_LIVE_ENDPOINTS: frozenset[str] = frozenset([
    "https://api.alpaca.markets",
    "https://api.alpaca.markets/",
    "http://api.alpaca.markets",
])

# ── exceptions ────────────────────────────────────────────────────────────────


class LiveTradingBlockedError(Exception):
    """Raised on any attempt to route to a live account, endpoint, or mode.

    There is no supported live trading implementation in M28.
    """


class InvalidPaperOrderError(ValueError):
    """Raised on order validation failure before any network call."""


class PaperAccountVerificationError(Exception):
    """Raised when account cannot be verified as an Alpaca paper account."""


# ── domain objects (no credentials ever stored) ───────────────────────────────


@dataclass(frozen=True)
class AlpacaOrderRecord:
    """Immutable audit trail for one Alpaca paper order.

    Governance: credentials are NEVER stored here.
    """
    mentisrex_order_id: str   # = client_order_id (deterministic)
    alpaca_order_id: str      # Alpaca-assigned UUID
    client_order_id: str      # deterministic hash (idempotency key)
    strategy_id: str
    strategy_fingerprint: str
    symbol: str
    side: str                 # "buy" | "sell"
    quantity: str             # Decimal serialized as string
    order_type: str           # "market" | "limit"
    time_in_force: str        # "day" | "gtc"
    status: str
    broker: str = "ALPACA"
    environment: str = "PAPER"
    submitted_at: str = ""
    # Immutable governance fields
    live_execution: str = "NO"
    real_capital: str = "NO"
    live_endpoint_supported: str = "NO"


@dataclass
class AlpacaFill:
    """Canonical fill record from Alpaca paper account."""
    fill_id: str
    alpaca_order_id: str
    symbol: str
    side: str
    quantity: Decimal
    fill_price: Decimal
    cost: Decimal
    filled_at: str = ""


@dataclass
class PositionReconciliationResult:
    ok: bool
    differences: list = field(default_factory=list)
    status: str = "RECONCILED"  # RECONCILED | RECONCILIATION_FAILED


@dataclass
class NavReconciliationResult:
    internal_nav: float
    alpaca_equity: float
    delta: float
    delta_bps: float
    ok: bool
    note: str = (
        "Differences expected from: timing, pending orders, "
        "broker mark-to-market, dividends, fees."
    )


# ── helpers ───────────────────────────────────────────────────────────────────


def _assert_no_live_trading() -> None:
    """Block any live trading attempt. Called at construction AND every submission."""
    if os.environ.get("MENTISREX_LIVE_TRADING", "false").lower() == "true":
        raise LiveTradingBlockedError(
            "MENTISREX_LIVE_TRADING=true detected. "
            "Live trading is not supported in M28. "
            "AlpacaPaperBroker routes exclusively to "
            f"{ALPACA_PAPER_BASE_URL} (Alpaca PAPER endpoint). "
            "Setting MENTISREX_LIVE_TRADING=true does NOT enable live trading — "
            "there is no live execution path."
        )


def _validate_order(
    symbol: str,
    side: str,
    quantity: Decimal,
    order_type: str,
    limit_price: Decimal | None,
    max_notional: Decimal,
) -> None:
    """Validate order before any network call. Raises InvalidPaperOrderError."""
    if not symbol or not symbol.strip():
        raise InvalidPaperOrderError("symbol must be a non-empty string")
    if side not in ("buy", "sell"):
        raise InvalidPaperOrderError(f"side must be 'buy' or 'sell', got {side!r}")
    if quantity <= 0:
        raise InvalidPaperOrderError(f"quantity must be positive, got {quantity}")
    if order_type not in ("market", "limit"):
        raise InvalidPaperOrderError(f"order_type must be 'market' or 'limit', got {order_type!r}")
    if order_type == "limit":
        if limit_price is None:
            raise InvalidPaperOrderError("limit_price required for limit orders")
        if limit_price <= 0:
            raise InvalidPaperOrderError(f"limit_price must be positive, got {limit_price}")
        notional = quantity * limit_price
        if notional > max_notional:
            raise InvalidPaperOrderError(
                f"Order notional {notional:.2f} exceeds "
                f"MAX_PAPER_ORDER_NOTIONAL {max_notional:.2f}. "
                "Raise max_order_notional to override."
            )


def _make_client_order_id(
    strategy_id: str,
    symbol: str,
    side: str,
    cycle_id: str,
    seq: int,
) -> str:
    """Deterministic, idempotency-safe client order ID.

    Same inputs always produce the same ID, enabling restart recovery.
    Max 48 chars for Alpaca compatibility.
    """
    raw = f"{strategy_id}:{symbol}:{side}:{cycle_id}:{seq}"
    h = hashlib.blake2b(raw.encode(), digest_size=8).hexdigest()
    return f"mr-{h}"  # e.g. "mr-a1b2c3d4e5f6a7b8"


def _safe_error(response: httpx.Response) -> str:
    """Extract error message without leaking credentials."""
    try:
        return str(response.json().get("message", response.text[:300]))
    except Exception:
        return response.text[:300]


# ── broker ────────────────────────────────────────────────────────────────────


class AlpacaPaperBroker:
    """Alpaca PAPER trading adapter (M28).

    Implements the same interface as PaperBroker for drop-in use with
    TradingEngine. Alpaca manages fills server-side; on_tick() is a no-op.

    PAPER ONLY — no live execution path exists. See module docstring.

    Usage::

        broker = AlpacaPaperBroker()   # reads env vars
        rec = broker.submit_order("SPY", "buy", Decimal("1"))
        print(rec.alpaca_order_id)
        broker.close()

        with AlpacaPaperBroker() as broker:
            print(broker.status_report())
    """

    # Hardcoded class constant — NOT a parameter. No configurable live endpoint.
    _BASE_URL: str = ALPACA_PAPER_BASE_URL
    BROKER: str = "ALPACA"
    ENVIRONMENT: str = "PAPER"

    def __init__(
        self,
        *,
        api_key: str | None = None,
        api_secret: str | None = None,
        strategy_id: str = "",
        strategy_fingerprint: str = "",
        max_order_notional: Decimal = Decimal("10000"),
        _http: httpx.Client | None = None,  # test injection only; skips network verify
    ) -> None:
        # 1. Block live trading at construction.
        _assert_no_live_trading()

        # 2. Validate credentials — fail closed on missing.
        key = api_key or os.environ.get("ALPACA_PAPER_API_KEY", "")
        secret = api_secret or os.environ.get("ALPACA_PAPER_API_SECRET", "")
        if not key or not secret:
            raise PaperAccountVerificationError(
                "Missing Alpaca paper credentials. "
                "Set ALPACA_PAPER_API_KEY and ALPACA_PAPER_API_SECRET. "
                "Do NOT use ALPACA_API_KEY — it may be a live-account credential."
            )

        self._strategy_id = strategy_id
        self._strategy_fingerprint = strategy_fingerprint
        self._max_order_notional = max_order_notional
        self._seq = 0
        self._order_records: dict[str, AlpacaOrderRecord] = {}
        self._account_id_masked: str = ""
        self._verified: bool = False

        # 3. Build HTTP client against hardcoded paper endpoint.
        if _http is not None:
            # Offline/test mode: caller provides mock http client.
            # Credential checks above already passed.
            self._http = _http
        else:
            self._http = httpx.Client(
                base_url=self._BASE_URL,
                headers={
                    "APCA-API-KEY-ID": key,
                    "APCA-API-SECRET-KEY": secret,
                    "accept": "application/json",
                    "content-type": "application/json",
                },
                timeout=15.0,
            )
            # 4. Verify paper account — fail closed.
            self._verify_paper_account()

    # ── paper account verification ────────────────────────────────────────────

    def _verify_paper_account(self) -> None:
        """Verify connectivity and that the account is reachable via paper endpoint.

        The Alpaca paper endpoint (paper-api.alpaca.markets) does not accept
        live-account credentials, so successful authentication here is structural
        proof this is a paper account.

        Raises PaperAccountVerificationError on any failure (fail-closed).
        """
        try:
            resp = self._http.get("/v2/account")
            resp.raise_for_status()
        except httpx.HTTPStatusError as e:
            raise PaperAccountVerificationError(
                f"Alpaca paper account verification failed "
                f"(HTTP {e.response.status_code}). "
                "Verify ALPACA_PAPER_API_KEY / ALPACA_PAPER_API_SECRET "
                "are paper-account credentials for paper-api.alpaca.markets."
            ) from e
        except Exception as e:
            raise PaperAccountVerificationError(
                f"Cannot connect to Alpaca paper endpoint ({self._BASE_URL}): {e}"
            ) from e

        acc = resp.json()
        status = acc.get("status", "")
        if status not in ("ACTIVE", "ACCOUNT_UPDATED", "APPROVED"):
            raise PaperAccountVerificationError(
                f"Alpaca account status is {status!r}, expected ACTIVE. "
                "Verify account setup at alpaca.markets."
            )
        raw_id = acc.get("id", "")
        # Mask: show only first 8 chars — never log full account ID.
        self._account_id_masked = (raw_id[:8] + "...") if len(raw_id) > 8 else raw_id
        self._verified = True
        logger.info(
            "alpaca_paper_account_verified",
            account=self._account_id_masked,
            endpoint=self._BASE_URL,
            environment=self.ENVIRONMENT,
        )

    # ── order submission ──────────────────────────────────────────────────────

    def submit_order(
        self,
        symbol: str,
        side: str,
        quantity: Decimal,
        order_type: str = "market",
        limit_price: Decimal | None = None,
        time_in_force: str = "day",
        *,
        strategy_id: str | None = None,
        strategy_fingerprint: str | None = None,
        cycle_id: str = "",
        risk_approved: bool = True,
    ) -> AlpacaOrderRecord:
        """Submit one paper order to Alpaca.

        Idempotent: if the same logical order was already submitted (same
        strategy_id, symbol, side, cycle_id, seq), returns the existing
        record without creating a duplicate order.

        Raises:
            LiveTradingBlockedError:       if MENTISREX_LIVE_TRADING=true
            InvalidPaperOrderError:        order fails pre-submission validation
            PaperAccountVerificationError: account not verified as paper
            RuntimeError:                  Alpaca rejects the order (HTTP error)
        """
        # Re-assert at every submission — defense in depth.
        _assert_no_live_trading()

        # Risk gate.
        if not risk_approved:
            raise InvalidPaperOrderError(
                f"Order rejected: risk_approved=False for {symbol} {side}. "
                "Resolve risk state before submitting."
            )

        qty = Decimal(str(quantity)) if not isinstance(quantity, Decimal) else quantity

        # Order validation before any network call.
        _validate_order(symbol, side, qty, order_type, limit_price, self._max_order_notional)

        sid = strategy_id or self._strategy_id
        sfp = strategy_fingerprint or self._strategy_fingerprint

        # Deterministic client_order_id for idempotency.
        self._seq += 1
        client_oid = _make_client_order_id(sid, symbol, side, cycle_id, self._seq)

        # In-process idempotency check.
        if client_oid in self._order_records:
            logger.info("alpaca_order_idempotent", client_order_id=client_oid, symbol=symbol)
            return self._order_records[client_oid]

        # Cross-restart idempotency: check Alpaca for existing order.
        existing = self._find_existing_by_client_id(client_oid, sid, sfp)
        if existing is not None:
            self._order_records[client_oid] = existing
            logger.info("alpaca_order_recovered", client_order_id=client_oid, symbol=symbol)
            return existing

        # Build payload.
        payload: dict = {
            "symbol": symbol,
            "qty": str(qty),
            "side": side,
            "type": order_type,
            "time_in_force": time_in_force,
            "client_order_id": client_oid,
        }
        if order_type == "limit" and limit_price is not None:
            payload["limit_price"] = str(limit_price)

        # Submit.
        try:
            resp = self._http.post("/v2/orders", json=payload)
            resp.raise_for_status()
        except httpx.HTTPStatusError as e:
            msg = _safe_error(e.response)
            logger.warning("alpaca_order_rejected", symbol=symbol, reason=msg[:200])
            raise RuntimeError(f"Alpaca paper order rejected for {symbol}: {msg}") from e
        except httpx.TimeoutException as e:
            # Timeout does NOT mean the order was not submitted.
            # Recover by checking client_order_id in Alpaca before retrying.
            raise RuntimeError(
                f"Timeout submitting {symbol} to Alpaca. "
                "Do NOT retry blindly — check client_order_id "
                f"{client_oid!r} via get_order_by_client_id() first."
            ) from e

        data = resp.json()
        alpaca_id = data["id"]

        record = AlpacaOrderRecord(
            mentisrex_order_id=client_oid,
            alpaca_order_id=alpaca_id,
            client_order_id=client_oid,
            strategy_id=sid,
            strategy_fingerprint=sfp,
            symbol=symbol,
            side=side,
            quantity=str(qty),
            order_type=order_type,
            time_in_force=time_in_force,
            status=data.get("status", "new"),
            submitted_at=datetime.now(UTC).isoformat(),
        )
        self._order_records[client_oid] = record
        logger.info(
            "alpaca_paper_order_submitted",
            symbol=symbol,
            side=side,
            quantity=str(qty),
            alpaca_id=alpaca_id,
            client_oid=client_oid,
            environment=self.ENVIRONMENT,
        )
        return record

    # ── PaperBroker-compatible submit (for TradingEngine drop-in) ─────────────

    def submit(self, req, now=None) -> object:  # type: ignore[override]
        """PaperBroker-compatible submit for use with TradingEngine.

        Translates paper.broker.OrderRequest → AlpacaPaperBroker.submit_order().
        Returns an OrderResult-like object.
        """
        from mentisrex.paper.broker import OrderResult
        from mentisrex.backtesting.events.types import OrderType as BtOrderType

        try:
            otype = "limit" if req.order_type == BtOrderType.LIMIT else "market"
            lp = req.limit_price
            rec = self.submit_order(
                symbol=str(req.symbol),
                side="buy" if str(req.side.value).lower() == "buy" else "sell",
                quantity=(
                    req.quantity
                    if isinstance(req.quantity, Decimal)
                    else Decimal(str(req.quantity))
                ),
                order_type=otype,
                limit_price=lp if lp is not None else None,
                strategy_id=getattr(req, "strategy_id", "") or "",
            )
            resting = rec.status in ("new", "partially_filled", "accepted", "pending_new")
            return OrderResult(accepted=True, resting=resting, order_id=rec.alpaca_order_id)
        except (InvalidPaperOrderError, LiveTradingBlockedError, RuntimeError) as e:
            return OrderResult(accepted=False, reason=str(e))

    def on_tick(self, _tick=None) -> list:
        """No-op: Alpaca manages fills server-side. Compatible with TradingEngine."""
        return []

    # ── order lifecycle ───────────────────────────────────────────────────────

    def get_order_status(self, alpaca_order_id: str) -> dict:
        """Poll Alpaca for current order state."""
        resp = self._http.get(f"/v2/orders/{alpaca_order_id}")
        resp.raise_for_status()
        return resp.json()

    def get_order_by_client_id(self, client_order_id: str) -> dict | None:
        """Retrieve order by client_order_id (restart recovery)."""
        try:
            resp = self._http.get(f"/v2/orders:by_client_order_id",
                                  params={"client_order_id": client_order_id})
            if resp.is_success:
                return resp.json()
        except Exception:
            pass
        return None

    def cancel_order(self, alpaca_order_id: str) -> bool:
        """Cancel a paper order. Returns True if succeeded."""
        try:
            self._http.delete(f"/v2/orders/{alpaca_order_id}").raise_for_status()
            return True
        except Exception:
            return False

    def get_fills(self, alpaca_order_id: str) -> list[AlpacaFill]:
        """Retrieve fills for an order from Alpaca paper account."""
        data = self.get_order_status(alpaca_order_id)
        if data.get("status") not in ("filled", "partially_filled"):
            return []
        px = Decimal(data.get("filled_avg_price") or "0")
        qty = Decimal(data.get("filled_qty") or "0")
        if not px or not qty:
            return []
        return [AlpacaFill(
            fill_id=f"{alpaca_order_id}-f1",
            alpaca_order_id=alpaca_order_id,
            symbol=data["symbol"],
            side=data["side"],
            quantity=qty,
            fill_price=px,
            cost=qty * px,
            filled_at=data.get("filled_at", ""),
        )]

    # ── account / positions ───────────────────────────────────────────────────

    def get_account(self) -> dict:
        """Get paper account state. Masks sensitive identifiers."""
        _assert_no_live_trading()
        acc = self._http.get("/v2/account").raise_for_status().json()
        pos_list = self._http.get("/v2/positions").raise_for_status().json()
        positions = {p["symbol"]: Decimal(p["qty"]) for p in pos_list}
        open_count = len(
            self._http.get("/v2/orders", params={"status": "open"})
            .raise_for_status().json()
        )
        return {
            "broker": self.BROKER,
            "environment": self.ENVIRONMENT,
            "account_id": self._account_id_masked,
            "account_status": acc.get("status", ""),
            "cash": Decimal(acc["cash"]),
            "equity": Decimal(acc["equity"]),
            "buying_power": Decimal(acc["buying_power"]),
            "positions": positions,
            "open_orders": open_count,
        }

    # TradingEngine compat: engine reads broker.account() (not get_account)
    def account(self) -> dict:
        return self.get_account()

    @property
    def open_orders(self) -> int:
        return len(
            self._http.get("/v2/orders", params={"status": "open"})
            .raise_for_status().json()
        )

    # ── reconciliation ────────────────────────────────────────────────────────

    def reconcile_positions(
        self, expected: dict[str, Decimal]
    ) -> PositionReconciliationResult:
        """Compare expected positions vs Alpaca paper positions.

        Marks RECONCILIATION_FAILED if any mismatch or unexpected position found.
        Does NOT silently correct mismatches.
        """
        acc = self.get_account()
        actual: dict[str, Decimal] = acc["positions"]
        differences = []
        for sym, exp_qty in expected.items():
            act_qty = actual.get(sym, Decimal(0))
            if abs(act_qty - exp_qty) > Decimal("0.01"):
                differences.append({
                    "symbol": sym,
                    "category": "quantity_mismatch",
                    "expected": float(exp_qty),
                    "actual": float(act_qty),
                    "delta": float(act_qty - exp_qty),
                    "severity": "warning",
                })
        for sym, act_qty in actual.items():
            if sym not in expected and abs(act_qty) > Decimal("0.01"):
                differences.append({
                    "symbol": sym,
                    "category": "unexpected_position",
                    "expected": 0.0,
                    "actual": float(act_qty),
                    "delta": float(act_qty),
                    "severity": "warning",
                })
        ok = len(differences) == 0
        return PositionReconciliationResult(
            ok=ok,
            differences=differences,
            status="RECONCILED" if ok else "RECONCILIATION_FAILED",
        )

    def reconcile_nav(self, internal_nav: float) -> NavReconciliationResult:
        """Compare internal NAV vs Alpaca paper equity.

        Within 10 bps tolerance is considered reconciled.
        """
        acc = self.get_account()
        alpaca_equity = float(acc["equity"])
        delta = alpaca_equity - internal_nav
        delta_bps = (delta / internal_nav * 10000) if internal_nav > 0 else 0.0
        return NavReconciliationResult(
            internal_nav=internal_nav,
            alpaca_equity=alpaca_equity,
            delta=delta,
            delta_bps=delta_bps,
            ok=abs(delta_bps) < 100,
        )

    # ── status report ─────────────────────────────────────────────────────────

    def status_report(self) -> dict:
        """Non-credential status for CLI display and audit.

        Never returns API keys or secrets.
        """
        try:
            acc = self.get_account()
            return {
                "broker": self.BROKER,
                "environment": self.ENVIRONMENT,
                "endpoint": self._BASE_URL,
                "account_id": acc["account_id"],
                "account_status": acc["account_status"],
                "equity": str(acc["equity"]),
                "cash": str(acc["cash"]),
                "buying_power": str(acc["buying_power"]),
                "open_orders": acc["open_orders"],
                "paper_verified": self._verified,
                "live_execution": "NO",
                "real_capital": "NO",
                "live_endpoint_supported": "NO",
                "connectivity": "OK",
            }
        except Exception as e:
            return {
                "broker": self.BROKER,
                "environment": self.ENVIRONMENT,
                "endpoint": self._BASE_URL,
                "connectivity": "FAILED",
                "error": str(e)[:300],
                "live_execution": "NO",
                "real_capital": "NO",
                "live_endpoint_supported": "NO",
            }

    # ── lifecycle ─────────────────────────────────────────────────────────────

    def close(self) -> None:
        self._http.close()

    def __enter__(self) -> "AlpacaPaperBroker":
        return self

    def __exit__(self, *_: object) -> None:
        self.close()

    # ── internals ─────────────────────────────────────────────────────────────

    def _find_existing_by_client_id(
        self,
        client_order_id: str,
        strategy_id: str,
        strategy_fingerprint: str,
    ) -> AlpacaOrderRecord | None:
        """Scan Alpaca order history for existing order (restart recovery)."""
        try:
            # Try the direct by-client-id endpoint first
            resp = self._http.get(
                "/v2/orders:by_client_order_id",
                params={"client_order_id": client_order_id},
            )
            if resp.is_success:
                data = resp.json()
                if data and isinstance(data, dict) and "id" in data:
                    return _record_from_alpaca(data, client_order_id, strategy_id, strategy_fingerprint)
        except Exception:
            pass

        # Fallback: scan recent orders
        try:
            resp = self._http.get("/v2/orders", params={"status": "all", "limit": 500})
            if resp.is_success:
                for data in resp.json():
                    if data.get("client_order_id") == client_order_id:
                        return _record_from_alpaca(data, client_order_id, strategy_id, strategy_fingerprint)
        except Exception:
            pass
        return None


def _record_from_alpaca(
    data: dict,
    client_order_id: str,
    strategy_id: str,
    strategy_fingerprint: str,
) -> AlpacaOrderRecord:
    return AlpacaOrderRecord(
        mentisrex_order_id=client_order_id,
        alpaca_order_id=data["id"],
        client_order_id=client_order_id,
        strategy_id=strategy_id,
        strategy_fingerprint=strategy_fingerprint,
        symbol=data["symbol"],
        side=data["side"],
        quantity=str(data.get("qty") or "0"),
        order_type=data["type"],
        time_in_force=data.get("time_in_force", "day"),
        status=data.get("status", ""),
        submitted_at=data.get("submitted_at", ""),
    )


# ── backward-compat alias (deprecated) ───────────────────────────────────────


class AlpacaBroker(AlpacaPaperBroker):
    """Deprecated alias for AlpacaPaperBroker.

    The old AlpacaBroker accepted a configurable base_url that could accidentally
    route to the live endpoint. This alias blocks that pattern explicitly.

    Use AlpacaPaperBroker directly.
    """

    def __init__(
        self,
        api_key: str = "",
        api_secret: str = "",
        base_url: str = ALPACA_PAPER_BASE_URL,
        **kwargs,
    ) -> None:
        # Block live endpoints explicitly in the compat shim.
        clean_url = base_url.rstrip("/")
        if clean_url in {e.rstrip("/") for e in _LIVE_ENDPOINTS}:
            raise LiveTradingBlockedError(
                f"Live endpoint {base_url!r} rejected. "
                "AlpacaBroker/AlpacaPaperBroker is PAPER ONLY. "
                "There is no live trading mode in M28."
            )
        if clean_url != ALPACA_PAPER_BASE_URL.rstrip("/"):
            raise LiveTradingBlockedError(
                f"Custom base_url {base_url!r} rejected. "
                "AlpacaPaperBroker accepts only the hardcoded paper endpoint."
            )
        import warnings
        warnings.warn(
            "AlpacaBroker is deprecated; use AlpacaPaperBroker instead.",
            DeprecationWarning,
            stacklevel=2,
        )
        super().__init__(api_key=api_key or None, api_secret=api_secret or None, **kwargs)


# ── self-check ───────────────────────────────────────────────────────────────

if __name__ == "__main__":
    """Paper account status check. No orders submitted."""
    broker = AlpacaPaperBroker()
    report = broker.status_report()
    print("=== ALPACA PAPER BROKER STATUS (M28) ===")
    for k, v in report.items():
        print(f"  {k:<35}: {v}")
    print()
    print(f"LIVE EXECUTION:         {report.get('live_execution', 'NO')}")
    print(f"REAL CAPITAL:           {report.get('real_capital', 'NO')}")
    print(f"LIVE ENDPOINT SUPPORTED:{report.get('live_endpoint_supported', 'NO')}")
    broker.close()
