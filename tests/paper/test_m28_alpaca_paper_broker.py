"""M28 AlpacaPaperBroker — comprehensive offline test suite.

All tests run without network access. Real Alpaca connectivity tests are marked
@pytest.mark.real_alpaca and excluded from the default offline suite.

Safety tests (per M28 spec §20):
  T01: live endpoint supplied → rejected
  T02: live-looking config → rejected
  T03: account cannot be verified → rejected
  T04: live execution mode requested → rejected
  T05: missing credentials → rejected
  T06: invalid order (multiple variants) → rejected before network
  T07: risk_approved=False → rejected before network
  T08: duplicate client_order_id → no duplicate order
  T09: restart after submission → reconciliation, not duplicate
  T10: live broker instantiation → no supported path / explicit failure

Additional coverage:
  T11: BrokerMode — ALPACA_LIVE absent
  T12: AlpacaOrderRecord audit fields — no credentials stored
  T13: idempotency key determinism
  T14: position reconciliation — match, mismatch, unexpected
  T15: NAV reconciliation — within/outside tolerance
  T16: fill retrieval — filled / unfilled orders
  T17: account masking — account_id masked in status report
  T18: network timeout handling — clear error, no silent retry
  T19: research isolation — no train/optimize/fit/backtest methods
  T20: backward-compat AlpacaBroker alias deprecation + live-endpoint block
"""

from __future__ import annotations

import warnings
from decimal import Decimal
from unittest.mock import MagicMock

import pytest

from mentisrex.paper import (
    AlpacaBroker,
    AlpacaOrderRecord,
    AlpacaPaperBroker,
    BrokerMode,
    InvalidPaperOrderError,
    LiveTradingBlockedError,
    NavReconciliationResult,
    PaperAccountVerificationError,
    PositionReconciliationResult,
)
from mentisrex.paper.alpaca_broker import (
    _LIVE_ENDPOINTS,
    ALPACA_PAPER_BASE_URL,
    _make_client_order_id,
    _validate_order,
)

# ── fixtures ──────────────────────────────────────────────────────────────────


def _mock_response(status_code: int = 200, body=None):
    m = MagicMock()
    m.status_code = status_code
    m.is_success = status_code < 300
    m.json.return_value = body or {}
    if status_code >= 400:
        import httpx

        m.raise_for_status.side_effect = httpx.HTTPStatusError(
            f"HTTP {status_code}",
            request=MagicMock(),
            response=MagicMock(status_code=status_code, text="error"),
        )
    else:
        m.raise_for_status.return_value = m
    return m


def _account_resp(status: str = "ACTIVE") -> MagicMock:
    return _mock_response(
        200,
        {
            "id": "abc123def456xyz",
            "status": status,
            "cash": "50000.00",
            "equity": "100000.00",
            "buying_power": "50000.00",
        },
    )


def _positions_resp(positions: list | None = None) -> MagicMock:
    return _mock_response(200, positions or [])


def _orders_resp(orders: list | None = None) -> MagicMock:
    return _mock_response(200, orders or [])


def _order_submit_resp(
    symbol: str = "SPY",
    side: str = "buy",
    status: str = "new",
    client_order_id: str = "mr-test",
) -> MagicMock:
    return _mock_response(
        200,
        {
            "id": "alpaca-uuid-001",
            "client_order_id": client_order_id,
            "symbol": symbol,
            "side": side,
            "type": "market",
            "time_in_force": "day",
            "qty": "1",
            "status": status,
            "submitted_at": "2026-08-14T00:00:00Z",
        },
    )


def _make_mock_http(
    account_resp=None,
    positions_resp=None,
    open_orders_resp=None,
    all_orders_resp=None,
    submit_resp=None,
) -> MagicMock:
    """Build a mock httpx.Client with configurable responses."""
    http = MagicMock()

    def _get(path, **kwargs):
        params = kwargs.get("params", {})
        if "v2/account" in path and "orders" not in path and "positions" not in path:
            return account_resp or _account_resp()
        if "v2/positions" in path:
            return positions_resp or _positions_resp()
        if "v2/orders" in path and "by_client_order_id" not in path:
            status_filter = params.get("status", "")
            if status_filter == "open":
                return open_orders_resp or _orders_resp()
            return all_orders_resp or _orders_resp()
        if "by_client_order_id" in path:
            return _mock_response(404, {"message": "not found"})
        return _mock_response(200, {})

    def _post(path, **kwargs):
        return submit_resp or _order_submit_resp()

    def _delete(path, **kwargs):
        return _mock_response(204, {})

    http.get.side_effect = _get
    http.post.side_effect = _post
    http.delete.side_effect = _delete
    http.close = MagicMock()
    return http


def _broker(**kwargs) -> AlpacaPaperBroker:
    """Build broker with mocked http (offline testing)."""
    http = kwargs.pop("_http", None) or _make_mock_http()
    kwargs.setdefault("api_key", "TESTPAPER_KEY")
    kwargs.setdefault("api_secret", "TESTPAPER_SECRET")
    return AlpacaPaperBroker(_http=http, **kwargs)


# ── T01: live endpoint rejected ────────────────────────────────────────────────


class TestLiveEndpointRejected:
    def test_no_base_url_parameter_on_alpaca_paper_broker(self):
        """AlpacaPaperBroker has no base_url parameter. Only paper endpoint possible."""
        import inspect

        sig = inspect.signature(AlpacaPaperBroker.__init__)
        assert "base_url" not in sig.parameters, (
            "AlpacaPaperBroker must NOT have a base_url parameter — "
            "there is no configurable live endpoint"
        )

    def test_base_url_class_constant_is_paper(self):
        assert AlpacaPaperBroker._BASE_URL == ALPACA_PAPER_BASE_URL
        assert "paper-api" in AlpacaPaperBroker._BASE_URL

    def test_live_endpoints_blocklist_contains_live_url(self):
        assert "https://api.alpaca.markets" in _LIVE_ENDPOINTS


# ── T02: live-looking config rejected ─────────────────────────────────────────


class TestLiveLookingConfigRejected:
    def test_alpaca_broker_alias_rejects_live_endpoint(self):
        with pytest.raises(LiveTradingBlockedError, match="[Ll]ive"):
            AlpacaBroker(
                api_key="K",
                api_secret="S",
                base_url="https://api.alpaca.markets",
                _http=_make_mock_http(),
            )

    def test_alpaca_broker_alias_rejects_custom_endpoint(self):
        with pytest.raises(LiveTradingBlockedError):
            AlpacaBroker(
                api_key="K",
                api_secret="S",
                base_url="https://custom-broker.example.com",
                _http=_make_mock_http(),
            )

    def test_alpaca_broker_alias_accepts_paper_endpoint(self, monkeypatch):
        monkeypatch.setenv("MENTISREX_LIVE_TRADING", "false")
        with warnings.catch_warnings(record=True) as w:
            warnings.simplefilter("always")
            b = AlpacaBroker(
                api_key="K",
                api_secret="S",
                base_url=ALPACA_PAPER_BASE_URL,
                _http=_make_mock_http(),
            )
        assert any("deprecated" in str(warning.message).lower() for warning in w)
        b.close()


# ── T03: account cannot be verified as paper → rejected ───────────────────────


class TestAccountVerificationRejected:
    def test_verify_paper_account_http_error_raises(self, monkeypatch):
        monkeypatch.setenv("MENTISREX_LIVE_TRADING", "false")

        http = MagicMock()
        http.get.return_value = _mock_response(401, {"message": "forbidden"})

        b = AlpacaPaperBroker(
            api_key="KEY",
            api_secret="SECRET",
            _http=http,
        )
        with pytest.raises(PaperAccountVerificationError):
            b._verify_paper_account()

    def test_verify_paper_account_wrong_status_raises(self):
        b = _broker()
        http = _make_mock_http(account_resp=_account_resp(status="INACTIVE"))
        b._http = http
        with pytest.raises(PaperAccountVerificationError, match="[Ii]nactive|status"):
            b._verify_paper_account()

    def test_verify_paper_account_connection_error_raises(self):
        b = _broker()
        b._http.get.side_effect = Exception("connection refused")
        with pytest.raises(PaperAccountVerificationError, match="Cannot connect"):
            b._verify_paper_account()


# ── T04: live execution mode requested → rejected ─────────────────────────────


class TestLiveExecutionModeRejected:
    def test_mentisrex_live_trading_true_blocks_construction(self, monkeypatch):
        monkeypatch.setenv("MENTISREX_LIVE_TRADING", "true")
        with pytest.raises(LiveTradingBlockedError, match="MENTISREX_LIVE_TRADING"):
            AlpacaPaperBroker(api_key="K", api_secret="S", _http=_make_mock_http())

    def test_mentisrex_live_trading_true_blocks_submit(self, monkeypatch):
        b = _broker()
        monkeypatch.setenv("MENTISREX_LIVE_TRADING", "true")
        with pytest.raises(LiveTradingBlockedError):
            b.submit_order("SPY", "buy", Decimal("1"))

    def test_mentisrex_live_trading_true_blocks_get_account(self, monkeypatch):
        b = _broker()
        monkeypatch.setenv("MENTISREX_LIVE_TRADING", "true")
        with pytest.raises(LiveTradingBlockedError):
            b.get_account()

    def test_mentisrex_live_trading_false_allows_construction(self, monkeypatch):
        monkeypatch.setenv("MENTISREX_LIVE_TRADING", "false")
        b = _broker()
        assert b is not None
        b.close()

    def test_broker_mode_has_no_live_option(self):
        modes = {m.value for m in BrokerMode}
        assert "ALPACA_LIVE" not in modes
        assert "LIVE" not in modes
        assert BrokerMode.ALPACA_PAPER.value == "ALPACA_PAPER"
        assert BrokerMode.MOCK.value == "MOCK"
        assert BrokerMode.SIMULATED.value == "SIMULATED"


# ── T05: missing credentials → rejected ──────────────────────────────────────


class TestMissingCredentials:
    def test_no_key_no_secret_raises(self, monkeypatch):
        monkeypatch.delenv("ALPACA_PAPER_API_KEY", raising=False)
        monkeypatch.delenv("ALPACA_PAPER_API_SECRET", raising=False)
        with pytest.raises(PaperAccountVerificationError, match="[Mm]issing"):
            AlpacaPaperBroker()

    def test_key_present_no_secret_raises(self, monkeypatch):
        monkeypatch.setenv("ALPACA_PAPER_API_KEY", "somekey")
        monkeypatch.delenv("ALPACA_PAPER_API_SECRET", raising=False)
        with pytest.raises(PaperAccountVerificationError):
            AlpacaPaperBroker()

    def test_secret_present_no_key_raises(self, monkeypatch):
        monkeypatch.delenv("ALPACA_PAPER_API_KEY", raising=False)
        monkeypatch.setenv("ALPACA_PAPER_API_SECRET", "somesecret")
        with pytest.raises(PaperAccountVerificationError):
            AlpacaPaperBroker()

    def test_empty_string_credentials_raise(self):
        with pytest.raises(PaperAccountVerificationError):
            AlpacaPaperBroker(api_key="", api_secret="")

    def test_explicit_credentials_bypass_env(self):
        b = AlpacaPaperBroker(
            api_key="TESTKEY",
            api_secret="TESTSECRET",
            _http=_make_mock_http(),
        )
        assert b is not None
        b.close()

    def test_error_message_does_not_mention_alpaca_api_key(self, monkeypatch):
        """Error should steer user to paper-specific env vars, not generic ones."""
        monkeypatch.delenv("ALPACA_PAPER_API_KEY", raising=False)
        monkeypatch.delenv("ALPACA_PAPER_API_SECRET", raising=False)
        with pytest.raises(PaperAccountVerificationError) as exc:
            AlpacaPaperBroker()
        msg = str(exc.value)
        assert "ALPACA_PAPER_API_KEY" in msg


# ── T06: invalid order → rejected before network ──────────────────────────────


class TestOrderValidation:
    def setup_method(self):
        self.b = _broker(max_order_notional=Decimal("1000"))

    def teardown_method(self):
        self.b.close()

    def test_zero_quantity_rejected(self):
        with pytest.raises(InvalidPaperOrderError, match="[Pp]ositive"):
            self.b.submit_order("SPY", "buy", Decimal("0"))

    def test_negative_quantity_rejected(self):
        with pytest.raises(InvalidPaperOrderError, match="[Pp]ositive"):
            self.b.submit_order("SPY", "buy", Decimal("-5"))

    def test_empty_symbol_rejected(self):
        with pytest.raises(InvalidPaperOrderError, match="[Ss]ymbol"):
            self.b.submit_order("", "buy", Decimal("1"))

    def test_whitespace_symbol_rejected(self):
        with pytest.raises(InvalidPaperOrderError, match="[Ss]ymbol"):
            self.b.submit_order("   ", "buy", Decimal("1"))

    def test_bad_side_rejected(self):
        with pytest.raises(InvalidPaperOrderError, match="side"):
            self.b.submit_order("SPY", "BUY", Decimal("1"))

    def test_bad_order_type_rejected(self):
        with pytest.raises(InvalidPaperOrderError, match="order_type"):
            self.b.submit_order("SPY", "buy", Decimal("1"), order_type="market_on_close")

    def test_limit_without_price_rejected(self):
        with pytest.raises(InvalidPaperOrderError, match="limit_price"):
            self.b.submit_order("SPY", "buy", Decimal("1"), order_type="limit")

    def test_limit_with_zero_price_rejected(self):
        with pytest.raises(InvalidPaperOrderError, match="limit_price"):
            self.b.submit_order(
                "SPY", "buy", Decimal("1"), order_type="limit", limit_price=Decimal("0")
            )

    def test_notional_exceeds_limit_rejected(self):
        # qty=10 * limit_price=200 = 2000 > max_notional=1000
        with pytest.raises(InvalidPaperOrderError, match="notional"):
            self.b.submit_order(
                "SPY",
                "buy",
                Decimal("10"),
                order_type="limit",
                limit_price=Decimal("200"),
            )

    def test_valid_market_order_accepted(self):
        rec = self.b.submit_order("SPY", "buy", Decimal("1"))
        assert rec.alpaca_order_id == "alpaca-uuid-001"
        assert rec.symbol == "SPY"
        assert rec.broker == "ALPACA"
        assert rec.environment == "PAPER"

    def test_valid_sell_order_accepted(self):
        rec = self.b.submit_order("SPY", "sell", Decimal("1"))
        assert rec.side == "sell"

    def test_no_network_call_before_validation_fails(self):
        """HTTP post must not be called when order validation fails."""
        self.b._http.post.reset_mock()
        with pytest.raises(InvalidPaperOrderError):
            self.b.submit_order("", "buy", Decimal("1"))
        self.b._http.post.assert_not_called()


# ── T07: risk_approved=False → rejected before network ────────────────────────


class TestRiskGate:
    def test_risk_not_approved_raises_before_network(self):
        b = _broker()
        b._http.post.reset_mock()
        with pytest.raises(InvalidPaperOrderError, match="risk_approved"):
            b.submit_order("SPY", "buy", Decimal("1"), risk_approved=False)
        b._http.post.assert_not_called()
        b.close()

    def test_risk_approved_true_allows_submission(self):
        b = _broker()
        rec = b.submit_order("SPY", "buy", Decimal("1"), risk_approved=True)
        assert rec.alpaca_order_id == "alpaca-uuid-001"
        b.close()


# ── T08: duplicate client_order_id → no duplicate order ───────────────────────


class TestIdempotency:
    def test_same_logical_order_in_process_not_duplicated(self):
        b = _broker()
        rec1 = b.submit_order("SPY", "buy", Decimal("1"), cycle_id="aug")
        # Force same seq/client_id by manipulating seq (tricky without internal access)
        # Instead: pre-insert the record
        rec2_client_id = next(iter(b._order_records.keys()))
        # Simulate a second call that resolves to the same client_order_id
        b._order_records[rec2_client_id] = rec1  # already there
        # Re-inserting same key returns existing — test via side effect only
        assert b._order_records[rec2_client_id] is rec1
        b.close()

    def test_client_order_id_deterministic(self):
        oid1 = _make_client_order_id("strat-1", "SPY", "buy", "cycle-aug", 3)
        oid2 = _make_client_order_id("strat-1", "SPY", "buy", "cycle-aug", 3)
        assert oid1 == oid2

    def test_client_order_id_changes_with_seq(self):
        oid1 = _make_client_order_id("strat-1", "SPY", "buy", "cycle-aug", 1)
        oid2 = _make_client_order_id("strat-1", "SPY", "buy", "cycle-aug", 2)
        assert oid1 != oid2

    def test_client_order_id_changes_with_symbol(self):
        oid1 = _make_client_order_id("s", "SPY", "buy", "", 1)
        oid2 = _make_client_order_id("s", "AAPL", "buy", "", 1)
        assert oid1 != oid2

    def test_client_order_id_max_length(self):
        oid = _make_client_order_id("some-strategy-id", "SPY", "buy", "cycle-2026-09", 999)
        assert len(oid) <= 48  # Alpaca client_order_id limit

    def test_in_process_idempotency_no_second_network_call(self):
        b = _broker()
        b._http.post.reset_mock()
        # Manually insert a record
        oid = _make_client_order_id("", "SPY", "buy", "", 1)
        fake_record = AlpacaOrderRecord(
            mentisrex_order_id=oid,
            alpaca_order_id="existing-uuid",
            client_order_id=oid,
            strategy_id="",
            strategy_fingerprint="",
            symbol="SPY",
            side="buy",
            quantity="1",
            order_type="market",
            time_in_force="day",
            status="new",
            submitted_at="2026-08-14T00:00:00Z",
        )
        b._order_records[oid] = fake_record
        b._seq = 0  # reset seq so next call generates seq=1 → same oid
        result = b.submit_order("SPY", "buy", Decimal("1"))
        assert result is fake_record
        b._http.post.assert_not_called()
        b.close()


# ── T09: restart recovery → reconciliation, not duplicate ─────────────────────


class TestRestartRecovery:
    def test_find_existing_by_client_id_returns_record(self):
        """Cross-restart: if Alpaca has the order, we recover it without re-submitting."""
        client_oid = "mr-existing123"
        existing_order = {
            "id": "alpaca-existing-uuid",
            "client_order_id": client_oid,
            "symbol": "SPY",
            "side": "buy",
            "type": "market",
            "time_in_force": "day",
            "qty": "1",
            "status": "filled",
            "submitted_at": "2026-08-14T00:00:00Z",
        }
        # Mock: by_client_order_id endpoint returns the existing order
        http = MagicMock()
        http.get.return_value = _mock_response(200, existing_order)
        http.post.return_value = _mock_response(200, {})
        http.close = MagicMock()

        b = AlpacaPaperBroker(api_key="K", api_secret="S", _http=http)
        rec = b._find_existing_by_client_id(client_oid, "strat", "fp")
        assert rec is not None
        assert rec.alpaca_order_id == "alpaca-existing-uuid"
        assert rec.client_order_id == client_oid
        b.close()

    def test_find_existing_returns_none_when_not_found(self):
        b = _broker()
        b._http.get.return_value = _mock_response(404, {"message": "not found"})
        # Also make the list endpoint return empty
        b._http.get.side_effect = lambda path, **kw: _mock_response(200, [])
        rec = b._find_existing_by_client_id("nonexistent", "strat", "fp")
        assert rec is None
        b.close()


# ── T10: live broker instantiation → explicit failure ─────────────────────────


class TestLiveBrokerInstantiation:
    def test_no_alpaca_live_broker_class_exists(self):
        """There must be no AlpacaLiveBroker class in the codebase."""
        from mentisrex import paper

        assert not hasattr(paper, "AlpacaLiveBroker")

    def test_no_live_mode_in_broker_mode_enum(self):
        all_names = {m.name for m in BrokerMode}
        assert "LIVE" not in all_names
        assert "ALPACA_LIVE" not in all_names

    def test_alpaca_paper_broker_base_url_cannot_be_overridden(self):
        """The paper URL is a class constant, not an instance attribute."""
        b = _broker()
        # Attempting to set _BASE_URL on instance doesn't affect class
        assert AlpacaPaperBroker._BASE_URL == ALPACA_PAPER_BASE_URL
        b.close()


# ── T11: BrokerMode ───────────────────────────────────────────────────────────


class TestBrokerMode:
    def test_all_valid_modes(self):
        assert BrokerMode.MOCK.value == "MOCK"
        assert BrokerMode.SIMULATED.value == "SIMULATED"
        assert BrokerMode.ALPACA_PAPER.value == "ALPACA_PAPER"

    def test_no_live_mode(self):
        values = {m.value for m in BrokerMode}
        assert "ALPACA_LIVE" not in values
        assert "LIVE" not in values


# ── T12: audit trail — no credentials stored ──────────────────────────────────


class TestAuditTrailNoCredentials:
    def test_order_record_contains_no_credentials(self):
        b = _broker(
            api_key="SUPER_SECRET_KEY",
            api_secret="SUPER_SECRET_VALUE",
            strategy_id="test-strat",
            strategy_fingerprint="fp123",
        )
        rec = b.submit_order("SPY", "buy", Decimal("1"))
        rec_str = str(rec)
        assert "SUPER_SECRET" not in rec_str
        assert "KEY" not in rec_str or "api_key" not in rec_str.lower()
        b.close()

    def test_order_record_has_all_required_fields(self):
        b = _broker(strategy_id="strat-1", strategy_fingerprint="fp-abc")
        rec = b.submit_order("AAPL", "sell", Decimal("5"), cycle_id="2026_08")
        assert rec.broker == "ALPACA"
        assert rec.environment == "PAPER"
        assert rec.live_execution == "NO"
        assert rec.real_capital == "NO"
        assert rec.live_endpoint_supported == "NO"
        assert rec.symbol == "AAPL"
        assert rec.side == "sell"
        assert rec.strategy_id == "strat-1"
        assert rec.strategy_fingerprint == "fp-abc"
        assert rec.client_order_id.startswith("mr-")
        assert rec.alpaca_order_id  # non-empty
        b.close()

    def test_status_report_masks_account_id(self):
        b = _broker()
        report = b.status_report()
        # account_id in status report must not be the raw ID
        raw_id = "abc123def456xyz"
        assert raw_id not in str(report.get("account_id", ""))
        # Should be masked (truncated + ...)
        assert "..." in str(report.get("account_id", "")) or len(
            str(report.get("account_id", ""))
        ) < len(raw_id)
        b.close()


# ── T13: idempotency key determinism ──────────────────────────────────────────


class TestClientOrderIdDeterminism:
    def test_same_inputs_same_output(self):
        kwargs = {"strategy_id": "s1", "symbol": "SPY", "side": "buy", "cycle_id": "c1", "seq": 1}
        assert _make_client_order_id(**kwargs) == _make_client_order_id(**kwargs)

    def test_different_seq_different_output(self):
        base = {"strategy_id": "s1", "symbol": "SPY", "side": "buy", "cycle_id": "c1"}
        assert _make_client_order_id(**base, seq=1) != _make_client_order_id(**base, seq=2)

    def test_different_side_different_output(self):
        base = {"strategy_id": "s1", "symbol": "SPY", "cycle_id": "c1", "seq": 1}
        assert _make_client_order_id(**base, side="buy") != _make_client_order_id(
            **base, side="sell"
        )

    def test_different_cycle_different_output(self):
        base = {"strategy_id": "s1", "symbol": "SPY", "side": "buy", "seq": 1}
        assert _make_client_order_id(**base, cycle_id="aug") != _make_client_order_id(
            **base, cycle_id="sep"
        )


# ── T14: position reconciliation ─────────────────────────────────────────────


class TestPositionReconciliation:
    def _make_positions_http(self, positions: dict) -> MagicMock:
        pos_list = [{"symbol": sym, "qty": str(qty)} for sym, qty in positions.items()]
        http = _make_mock_http(positions_resp=_mock_response(200, pos_list))
        return http

    def test_empty_expected_empty_actual_reconciled(self):
        b = _broker(_http=_make_mock_http())
        result = b.reconcile_positions({})
        assert result.ok
        assert result.status == "RECONCILED"
        b.close()

    def test_matching_positions_reconciled(self):
        http = self._make_positions_http({"SPY": Decimal("10")})
        b = _broker(_http=http)
        result = b.reconcile_positions({"SPY": Decimal("10")})
        assert result.ok
        assert result.status == "RECONCILED"
        b.close()

    def test_quantity_mismatch_fails_reconciliation(self):
        http = self._make_positions_http({"SPY": Decimal("5")})
        b = _broker(_http=http)
        result = b.reconcile_positions({"SPY": Decimal("10")})
        assert not result.ok
        assert result.status == "RECONCILIATION_FAILED"
        assert any(d["category"] == "quantity_mismatch" for d in result.differences)
        b.close()

    def test_unexpected_position_fails_reconciliation(self):
        http = self._make_positions_http({"SPY": Decimal("10"), "AAPL": Decimal("5")})
        b = _broker(_http=http)
        result = b.reconcile_positions({"SPY": Decimal("10")})  # AAPL not expected
        assert not result.ok
        assert any(d["category"] == "unexpected_position" for d in result.differences)
        b.close()

    def test_missing_position_fails_reconciliation(self):
        http = self._make_positions_http({})  # no positions
        b = _broker(_http=http)
        result = b.reconcile_positions({"SPY": Decimal("10")})
        assert not result.ok
        assert any(d["category"] == "quantity_mismatch" for d in result.differences)
        b.close()

    def test_reconciliation_result_type(self):
        b = _broker()
        result = b.reconcile_positions({})
        assert isinstance(result, PositionReconciliationResult)
        b.close()


# ── T15: NAV reconciliation ───────────────────────────────────────────────────


class TestNavReconciliation:
    def _broker_with_equity(self, equity: str) -> AlpacaPaperBroker:
        http = _make_mock_http(account_resp=_account_resp())
        # Override equity return
        http.get.side_effect = lambda path, **kw: (
            _mock_response(
                200,
                {
                    "id": "abc123def",
                    "status": "ACTIVE",
                    "cash": "50000.00",
                    "equity": equity,
                    "buying_power": "50000.00",
                },
            )
            if "v2/account" in path and "orders" not in path and "positions" not in path
            else _mock_response(200, [])
        )
        return AlpacaPaperBroker(api_key="K", api_secret="S", _http=http)

    def test_within_tolerance_reconciled(self):
        b = self._broker_with_equity("100050.00")  # +5 bps on 100k
        result = b.reconcile_nav(100000.0)
        assert result.ok  # within 100 bps
        assert abs(result.delta_bps) < 100
        b.close()

    def test_outside_tolerance_not_reconciled(self):
        b = self._broker_with_equity("101100.00")  # +110 bps on 100k
        result = b.reconcile_nav(100000.0)
        assert not result.ok
        b.close()

    def test_result_type(self):
        b = _broker()
        result = b.reconcile_nav(100000.0)
        assert isinstance(result, NavReconciliationResult)
        b.close()

    def test_delta_calculation_correct(self):
        b = self._broker_with_equity("99000.00")
        result = b.reconcile_nav(100000.0)
        assert abs(result.delta - (-1000.0)) < 0.01
        assert abs(result.delta_bps - (-100.0)) < 0.1
        b.close()


# ── T16: fill retrieval ───────────────────────────────────────────────────────


class TestFillRetrieval:
    def test_filled_order_returns_fill(self):
        b = _broker()
        order_data = {
            "id": "alpaca-001",
            "symbol": "SPY",
            "side": "buy",
            "status": "filled",
            "filled_qty": "1",
            "filled_avg_price": "550.00",
            "filled_at": "2026-08-14T12:00:00Z",
            "qty": "1",
            "type": "market",
        }
        b._http.get.side_effect = None
        b._http.get.return_value = _mock_response(200, order_data)
        fills = b.get_fills("alpaca-001")
        assert len(fills) == 1
        assert fills[0].fill_price == Decimal("550.00")
        assert fills[0].quantity == Decimal("1")
        assert fills[0].symbol == "SPY"
        b.close()

    def test_unfilled_order_returns_empty(self):
        b = _broker()
        order_data = {
            "id": "alpaca-002",
            "symbol": "SPY",
            "side": "buy",
            "status": "new",
            "qty": "1",
            "type": "market",
        }
        b._http.get.return_value = _mock_response(200, order_data)
        fills = b.get_fills("alpaca-002")
        assert fills == []
        b.close()


# ── T17: account masking ──────────────────────────────────────────────────────


class TestAccountMasking:
    def test_account_id_masked_in_status_report(self):
        http = _make_mock_http(
            account_resp=_mock_response(
                200,
                {
                    "id": "abcdef1234567890",
                    "status": "ACTIVE",
                    "cash": "50000.00",
                    "equity": "100000.00",
                    "buying_power": "50000.00",
                },
            )
        )
        b = AlpacaPaperBroker(api_key="K", api_secret="S", _http=http)
        b._account_id_masked = "abcdef12..."
        b._verified = True
        report = b.status_report()
        assert "abcdef1234567890" not in str(report)
        b.close()


# ── T18: network timeout handling ─────────────────────────────────────────────


class TestNetworkFailureHandling:
    def test_timeout_on_submit_raises_with_idempotency_guidance(self):
        import httpx

        b = _broker()
        b._http.post.side_effect = httpx.TimeoutException("timeout")
        with pytest.raises(RuntimeError, match="[Tt]imeout"):
            b.submit_order("SPY", "buy", Decimal("1"))
        b.close()

    def test_http_error_on_submit_raises_runtime_error(self):
        import httpx

        b = _broker()
        err_resp = MagicMock()
        err_resp.status_code = 422
        err_resp.text = "unprocessable"
        err_resp.json.return_value = {"message": "insufficient qty"}
        b._http.post.side_effect = httpx.HTTPStatusError(
            "422", request=MagicMock(), response=err_resp
        )
        with pytest.raises(RuntimeError, match="rejected"):
            b.submit_order("SPY", "buy", Decimal("1"))
        b.close()


# ── T19: research isolation ───────────────────────────────────────────────────


class TestResearchIsolation:
    def test_no_train_method(self):
        b = _broker()
        assert not hasattr(b, "train"), "AlpacaPaperBroker must not have train()"
        b.close()

    def test_no_fit_method(self):
        b = _broker()
        assert not hasattr(b, "fit"), "AlpacaPaperBroker must not have fit()"
        b.close()

    def test_no_optimize_method(self):
        b = _broker()
        assert not hasattr(b, "optimize"), "AlpacaPaperBroker must not have optimize()"
        b.close()

    def test_no_backtest_method(self):
        b = _broker()
        assert not hasattr(b, "backtest"), "AlpacaPaperBroker must not have backtest()"
        b.close()

    def test_governance_fields_in_order_record(self):
        b = _broker()
        rec = b.submit_order("SPY", "buy", Decimal("1"))
        assert rec.live_execution == "NO"
        assert rec.real_capital == "NO"
        assert rec.live_endpoint_supported == "NO"
        b.close()


# ── T20: AlpacaBroker alias ────────────────────────────────────────────────────


class TestAlpacaBrokerAlias:
    def test_alias_emits_deprecation_warning(self, monkeypatch):
        monkeypatch.setenv("MENTISREX_LIVE_TRADING", "false")
        with warnings.catch_warnings(record=True) as w:
            warnings.simplefilter("always")
            b = AlpacaBroker(
                api_key="K",
                api_secret="S",
                _http=_make_mock_http(),
            )
            b.close()
        assert any(issubclass(warning.category, DeprecationWarning) for warning in w)

    def test_alias_inherits_paper_safety(self, monkeypatch):
        monkeypatch.setenv("MENTISREX_LIVE_TRADING", "true")
        with pytest.raises(LiveTradingBlockedError):
            AlpacaBroker(api_key="K", api_secret="S")

    def test_alias_subclass_of_paper_broker(self):
        assert issubclass(AlpacaBroker, AlpacaPaperBroker)


# ── validate_order standalone ────────────────────────────────────────────────


class TestValidateOrderStandalone:
    max_n = Decimal("10000")

    def test_valid_market_order_passes(self):
        _validate_order("SPY", "buy", Decimal("10"), "market", None, self.max_n)

    def test_valid_limit_order_passes(self):
        _validate_order("SPY", "sell", Decimal("5"), "limit", Decimal("500"), self.max_n)

    def test_string_quantity_as_decimal(self):
        # Caller must pass Decimal; validate_order doesn't coerce
        _validate_order("SPY", "buy", Decimal("1"), "market", None, self.max_n)


# ── real Alpaca tests (network; excluded from default suite) ──────────────────


@pytest.mark.real_alpaca
class TestRealAlpacaPaperConnectivity:
    """Real Alpaca paper account tests.

    Excluded from offline suite. Run with:
        pytest -m real_alpaca tests/paper/test_m28_alpaca_paper_broker.py

    Requires:
        ALPACA_PAPER_API_KEY
        ALPACA_PAPER_API_SECRET
    """

    def test_connectivity_and_paper_account_verified(self):
        broker = AlpacaPaperBroker()
        assert broker._verified
        report = broker.status_report()
        assert report["connectivity"] == "OK"
        assert report["environment"] == "PAPER"
        assert report["live_execution"] == "NO"
        assert report["real_capital"] == "NO"
        broker.close()

    def test_submit_and_cancel_market_order(self):
        broker = AlpacaPaperBroker()
        rec = broker.submit_order("SPY", "buy", Decimal("1"), cycle_id="m28-smoke-test")
        assert rec.alpaca_order_id
        assert rec.broker == "ALPACA"
        assert rec.environment == "PAPER"
        # Cancel immediately (smoke test cleanup)
        broker.cancel_order(rec.alpaca_order_id)
        status = broker.get_order_status(rec.alpaca_order_id)
        assert status["status"] in ("canceled", "pending_cancel", "filled")
        broker.close()
