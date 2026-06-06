"""Coupling-coordination model: C, T, D + level classification."""
from __future__ import annotations

import math
from typing import Any, Dict, List

from .config import ALPHA, BETA, classify_level


def _clip(x: float, lo: float = 0.0, hi: float = 1.0) -> float:
    if x is None or (isinstance(x, float) and math.isnan(x)):
        return 0.0
    return max(lo, min(hi, x))


def compute_ctd(u1: float, u2: float, alpha: float = ALPHA, beta: float = BETA):
    """Return (C, T, D) clipped to [0, 1].  Safe against zero / NaN."""
    u1 = _clip(u1)
    u2 = _clip(u2)
    s = u1 + u2
    if s <= 0:
        C = 0.0
    else:
        prod = u1 * u2
        C = 2.0 * math.sqrt(prod) / s if prod >= 0 else 0.0
    T = alpha * u1 + beta * u2
    C = _clip(C)
    T = _clip(T)
    D = _clip(math.sqrt(C * T))
    return C, T, D


def apply_coupling(rows: List[Dict[str, Any]], alpha: float = ALPHA, beta: float = BETA) -> List[Dict[str, Any]]:
    out = []
    for r in rows:
        u1 = r.get("U1", 0.0) or 0.0
        u2 = r.get("U2", 0.0) or 0.0
        C, T, D = compute_ctd(u1, u2, alpha, beta)
        new_r = dict(r)
        new_r["U1"] = _clip(u1)
        new_r["U2"] = _clip(u2)
        new_r["C"] = C
        new_r["T"] = T
        new_r["D"] = D
        new_r["level"] = classify_level(D)
        out.append(new_r)
    return out
