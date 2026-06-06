"""Entropy-weight method + U1/U2 aggregation.

Implementation favors numpy when available but falls back to pure Python so
the module can run in stripped environments.
"""
from __future__ import annotations

import logging
import math
import statistics
from typing import Any, Dict, List, Tuple

from .config import EPS, U1_FIELDS, U2_FIELDS

logger = logging.getLogger(__name__)


def _isnan(x) -> bool:
    try:
        return x is None or (isinstance(x, float) and math.isnan(x))
    except Exception:
        return False


def _safe_median(values: List[float]) -> float:
    clean = [v for v in values if not _isnan(v)]
    if not clean:
        return 0.0
    return statistics.median(clean)


def _normalize_column(values: List[float], positive: bool = True) -> List[float]:
    """Min-max normalization with NaN -> median fill and constant-column -> 0.5."""
    if not values:
        return []
    if all(_isnan(v) for v in values):
        return [0.0] * len(values)
    med = _safe_median(values)
    cleaned = [med if _isnan(v) else float(v) for v in values]
    lo, hi = min(cleaned), max(cleaned)
    if hi - lo < 1e-12:
        return [0.5] * len(cleaned)
    if positive:
        norm = [(v - lo) / (hi - lo) for v in cleaned]
    else:
        norm = [(hi - v) / (hi - lo) for v in cleaned]
    return [max(0.0, min(1.0, v)) for v in norm]


def _entropy_weights(matrix: List[List[float]]) -> List[float]:
    """`matrix` shape: n_samples x m_indicators.  Each column already in [0,1]."""
    n = len(matrix)
    if n == 0:
        return []
    m = len(matrix[0])
    if m == 0:
        return []
    # Shift slightly to keep > 0 for log
    cols = [[matrix[i][j] + EPS for i in range(n)] for j in range(m)]
    col_sums = [sum(c) for c in cols]
    ln_n = math.log(n) if n > 1 else 1.0
    e = []
    for j in range(m):
        s = col_sums[j]
        if s <= 0:
            e.append(1.0)
            continue
        e_j = 0.0
        for i in range(n):
            p = cols[j][i] / s
            if p > 0:
                e_j += p * math.log(p)
        e.append(-e_j / ln_n if ln_n > 0 else 1.0)
    g = [max(0.0, 1.0 - ej) for ej in e]
    gs = sum(g)
    if gs <= 0:
        return [1.0 / m] * m
    return [gj / gs for gj in g]


def compute_subsystem(
    rows: List[Dict[str, Any]],
    fields: List[str],
    name: str,
) -> Tuple[Dict[str, float], Dict[str, List[float]]]:
    """Returns (weights_dict, normalized_columns_dict)."""
    # Drop fields that are entirely missing
    available = []
    for f in fields:
        if f not in rows[0]:
            logger.warning("[entropy] %s: field %s not present, skipping", name, f)
            continue
        col = [r.get(f) for r in rows]
        if all(_isnan(v) for v in col):
            logger.warning("[entropy] %s: field %s is all NaN, skipping", name, f)
            continue
        available.append(f)
    if len(available) < 2:
        logger.warning("[entropy] %s: fewer than 2 valid fields (%s) — proceeding with equal weights", name, available)

    norm_cols: Dict[str, List[float]] = {}
    for f in available:
        norm_cols[f] = _normalize_column([r.get(f) for r in rows], positive=True)

    if not norm_cols:
        return {}, {}

    # Build matrix
    n = len(rows)
    matrix = [[norm_cols[f][i] for f in available] for i in range(n)]
    weights_list = _entropy_weights(matrix)
    weights = {f: w for f, w in zip(available, weights_list)}
    return weights, norm_cols


def aggregate_U(rows: List[Dict[str, Any]], weights: Dict[str, float], norm_cols: Dict[str, List[float]]) -> List[float]:
    if not weights:
        return [0.0] * len(rows)
    n = len(rows)
    out = []
    for i in range(n):
        s = 0.0
        for f, w in weights.items():
            s += w * norm_cols[f][i]
        out.append(max(0.0, min(1.0, s)))
    return out


def run_entropy(rows: List[Dict[str, Any]]) -> Tuple[List[Dict[str, Any]], Dict[str, Any]]:
    """Compute U1, U2 and attach them to each row.

    Returns (rows_with_U, weights_dict_with_subsystems).
    """
    if not rows:
        return rows, {"U1_weights": {}, "U2_weights": {}}

    w1, n1 = compute_subsystem(rows, U1_FIELDS, "U1")
    w2, n2 = compute_subsystem(rows, U2_FIELDS, "U2")

    u1 = aggregate_U(rows, w1, n1)
    u2 = aggregate_U(rows, w2, n2)

    out_rows = []
    for i, r in enumerate(rows):
        new_r = dict(r)
        for f, col in n1.items():
            new_r[f + "_norm"] = col[i]
        for f, col in n2.items():
            new_r[f + "_norm"] = col[i]
        new_r["U1"] = u1[i]
        new_r["U2"] = u2[i]
        out_rows.append(new_r)

    return out_rows, {"U1_weights": w1, "U2_weights": w2}
