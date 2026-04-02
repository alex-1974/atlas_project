# src/atlas/understanding/core/fuzzy.py
"""Fuzzy-logic primitives for the Atlas DU pipeline.

All values are floats in [0.0, 1.0].  Functions clamp inputs and outputs
to that range so callers never need to worry about overflow.

Operators
---------
fand(*args)        Fuzzy AND  — Mamdani minimum
for_(*args)        Fuzzy OR   — algebraic sum (bounded, never > 1)
fnot(a)            Fuzzy NOT  — standard complement
fimpl(a, b)        Fuzzy implication  — if a then b  (Mamdani: min(a, b))
fscale(a, w)       Scale membership by weight w ∈ [0, 1]
fboost(a, w)       Boost: a + w*(1-a)  — pull value toward 1
fdampen(a, w)      Dampen: a * (1-w)   — pull value toward 0
fthresh(a, t)      Hard threshold → 1.0 if a >= t else 0.0
flinear(x, lo, hi) Linear ramp: 0 below lo, 1 above hi, linear between
fguard(a, guard)   Returns a if guard > 0, else 0  — gating pattern
fmax(*args)        Alias for OR (max-based, clearer intent for "best of")

Design notes
------------
- fand uses minimum (Mamdani): the weakest signal limits the conjunction.
  This is deliberately strict — if any precondition is absent the whole
  expression collapses.  Use for_() when you want softer combination.
- for_ uses algebraic sum a + b - a*b: bounded, commutative, associative,
  strictly greater than max(a, b) for any two non-zero inputs.  Good for
  "at least one of these is evidence".
- fguard(signal, gate) is the primary tool for the author_like problem:
  a strong signal (e.g. is_short_line) is multiplied by a gate (e.g.
  has_name_signal) so the combination is 0 whenever the gate is 0.
"""
from __future__ import annotations


def _c(v) -> float:
    """Clamp to [0, 1]."""
    try:
        return max(0.0, min(1.0, float(v)))
    except (TypeError, ValueError):
        return 0.0


# ── Core operators ────────────────────────────────────────────────────────────

def fand(*args) -> float:
    """Fuzzy AND — minimum of all inputs."""
    if not args:
        return 0.0
    return min(_c(a) for a in args)


def for_(*args) -> float:
    """Fuzzy OR — algebraic (probabilistic) sum, bounded to [0, 1]."""
    result = 0.0
    for a in args:
        v = _c(a)
        result = result + v - result * v
    return result


def fnot(a) -> float:
    """Fuzzy NOT — standard complement."""
    return 1.0 - _c(a)


def fimpl(a, b) -> float:
    """Fuzzy implication: if a then b (Mamdani min)."""
    return fand(a, b)


# ── Modifiers ─────────────────────────────────────────────────────────────────

def fscale(a, w) -> float:
    """Scale membership by weight w ∈ [0, 1].

    fscale(0.8, 0.5) → 0.4  — "half as important"
    """
    return _c(a) * _c(w)


def fboost(a, w) -> float:
    """Boost: pull value toward 1 by strength w.

    fboost(0.4, 0.5) → 0.4 + 0.5*(1-0.4) = 0.70
    """
    a, w = _c(a), _c(w)
    return a + w * (1.0 - a)


def fdampen(a, w) -> float:
    """Dampen: pull value toward 0 by strength w.

    fdampen(0.8, 0.5) → 0.8 * 0.5 = 0.40
    """
    return _c(a) * (1.0 - _c(w))


# ── Gates and thresholds ──────────────────────────────────────────────────────

def fguard(a, gate) -> float:
    """Gate: returns a scaled by gate.

    The primary fix for the author_like / Ortsnamen problem:
        author_like = fguard(short_and_no_dot, has_name_signal)
    If has_name_signal == 0 the whole expression collapses to 0.
    """
    return _c(a) * _c(gate)


def fthresh(a, t: float) -> float:
    """Hard threshold: 1.0 if a >= t else 0.0."""
    return 1.0 if _c(a) >= t else 0.0


def flinear(x, lo: float, hi: float) -> float:
    """Linear ramp from 0 (at x=lo) to 1 (at x=hi).

    flinear(75, 0, 100) → 0.75
    flinear(-5, 0, 100) → 0.0
    flinear(120, 0, 100) → 1.0
    """
    if hi <= lo:
        return 1.0 if float(x) >= hi else 0.0
    v = (float(x) - lo) / (hi - lo)
    return max(0.0, min(1.0, v))


def fmax(*args) -> float:
    """Maximum of inputs — alias for max-based OR.

    Use when you want 'best of N signals' semantics more explicitly
    than algebraic or_.
    """
    if not args:
        return 0.0
    return max(_c(a) for a in args)
