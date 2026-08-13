"""Prometheus metrics endpoint — /metrics, scrapeable, dependency-free.

Health probes (/health/*) answer "is it up?"; metrics answer "how is it doing
over time?" and drive alerting. We hand-roll the tiny Prometheus text format
instead of adding prometheus_client — three gauges is not worth a dependency.

ponytail: exposes up / build_info / uptime only. Add request-rate + latency
histograms here (or drop in prometheus_client) when a dashboard actually needs
them; the RequestLoggingMiddleware already has the data to feed them.
"""

import time

from fastapi import APIRouter, Response

from mentisrex.presentation.api.dependencies import SettingsDep

router = APIRouter(tags=["monitoring"])

_START = time.time()
_VERSION = "0.1.0"


@router.get("/metrics", summary="Prometheus metrics", response_class=Response)
async def metrics(settings: SettingsDep) -> Response:
    uptime = time.time() - _START
    body = (
        "# HELP mentisrex_up 1 if the process is serving.\n"
        "# TYPE mentisrex_up gauge\n"
        "mentisrex_up 1\n"
        "# HELP mentisrex_uptime_seconds Seconds since process start.\n"
        "# TYPE mentisrex_uptime_seconds gauge\n"
        f"mentisrex_uptime_seconds {uptime:.0f}\n"
        "# HELP mentisrex_build_info Build/version labels (value always 1).\n"
        "# TYPE mentisrex_build_info gauge\n"
        f'mentisrex_build_info{{version="{_VERSION}",'
        f'environment="{settings.environment}"}} 1\n'
    )
    return Response(content=body, media_type="text/plain; version=0.0.4")
