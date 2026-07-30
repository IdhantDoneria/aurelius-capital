"""Tests for the operations monitor."""

import tempfile
from pathlib import Path

import pytest
from aurelius.operations.config import OperationsConfig
from aurelius.operations.monitor import OperationsMonitor


@pytest.fixture
def tmp_config(tmp_path):
    cfg = OperationsConfig(corpus_root=tmp_path / "corpus")
    cfg.ensure_dirs()
    return cfg


def test_health_returns_healthy_when_empty(tmp_config):
    monitor = OperationsMonitor(tmp_config)
    h = monitor.health()
    assert h.status == "healthy"
    assert h.incoming_queue_size == 0
    assert h.processed_total == 0


def test_health_shows_incoming_count(tmp_config):
    (tmp_config.incoming / "paper.txt").write_text("hello")
    monitor = OperationsMonitor(tmp_config)
    h = monitor.health()
    assert h.incoming_queue_size == 1


def test_health_components_ok(tmp_config):
    monitor = OperationsMonitor(tmp_config)
    h = monitor.health()
    for status in h.components.values():
        assert status == "ok"


def test_metrics_returns_dict(tmp_config):
    monitor = OperationsMonitor(tmp_config)
    m = monitor.metrics()
    assert "date" in m
    assert "papers_processed_today" in m
    assert "pipeline_success_rate" in m


def test_metrics_success_rate_default(tmp_config):
    monitor = OperationsMonitor(tmp_config)
    m = monitor.metrics()
    assert m["pipeline_success_rate"] == 1.0


def test_uptime_positive(tmp_config):
    monitor = OperationsMonitor(tmp_config)
    h = monitor.health()
    assert h.uptime_seconds >= 0.0
