"""American option pricing (AIDP M18).

Cox-Ross-Rubinstein binomial tree — a real early-exercise model, NOT a European
approximation. Deterministic (fixed step count), converges to Black-Scholes for European
payoffs. Greeks by finite difference on the tree.

Exercise assumption: exercise permitted at every tree node (discrete Bermudan approximation
to continuous American exercise); accuracy is governed by `steps` (see docs, limitations).
"""

from __future__ import annotations

import math


def crr_price(
    is_call: bool,
    s: float,
    k: float,
    r: float,
    q: float,
    vol: float,
    t: float,
    *,
    steps: int = 200,
    american: bool = True,
) -> float:
    if s <= 0 or k <= 0:
        raise ValueError("spot and strike must be > 0")
    if t <= 0 or vol <= 0:
        return max(0.0, (s - k) if is_call else (k - s))
    dt = t / steps
    u = math.exp(vol * math.sqrt(dt))
    d = 1.0 / u
    disc = math.exp(-r * dt)
    p = (math.exp((r - q) * dt) - d) / (u - d)
    if not 0.0 <= p <= 1.0:
        raise ValueError("risk-neutral probability out of [0,1]; check inputs/steps")
    # terminal payoffs
    values = []
    for i in range(steps + 1):
        st = s * (u ** (steps - i)) * (d**i)
        values.append(max(0.0, (st - k) if is_call else (k - st)))
    # backward induction with early-exercise test
    for step in range(steps - 1, -1, -1):
        for i in range(step + 1):
            cont = disc * (p * values[i] + (1.0 - p) * values[i + 1])
            if american:
                st = s * (u ** (step - i)) * (d**i)
                ex = max(0.0, (st - k) if is_call else (k - st))
                values[i] = max(cont, ex)
            else:
                values[i] = cont
    return values[0]


def crr_greeks(
    is_call: bool,
    s: float,
    k: float,
    r: float,
    q: float,
    vol: float,
    t: float,
    *,
    steps: int = 200,
    american: bool = True,
    bump: float = 1e-3,
) -> dict:
    """Finite-difference Greeks on the binomial tree (delta, gamma, vega, theta, rho)."""

    def px(ss=s, kk=k, rr=r, qq=q, vv=vol, tt=t):
        return crr_price(is_call, ss, kk, rr, qq, vv, tt, steps=steps, american=american)

    ds = s * bump
    p0 = px()
    pu, pd = px(ss=s + ds), px(ss=s - ds)
    delta = (pu - pd) / (2 * ds)
    gamma = (pu - 2 * p0 + pd) / (ds * ds)
    vega = (px(vv=vol + bump) - px(vv=vol - bump)) / (2 * bump)
    rho = (px(rr=r + bump) - px(rr=r - bump)) / (2 * bump)
    dt = min(bump, t * 0.5)
    theta = (px(tt=t - dt) - p0) / dt if t > dt else 0.0
    return {
        "delta": delta,
        "gamma": gamma,
        "vega": vega,
        "rho": rho,
        "theta": theta,
        "vanna": 0.0,
        "volga": 0.0,
    }
