"""
Meta-tag computation for generated questions.

Normalization corpus: 153 JEE Advanced organic chemistry questions (2013–2025).
Stats file: meta_tag_norm_stats.json

Four deterministic meta-tags (computed from text):
  1. question_length_scope   — word count, z-scored within archetype
  2. semantic_obfuscation    — IUPAC token density, z-scored globally
  3. conceptual_fragility    — fragility_weight from JIC data, z-scored within archetype
                               (for generated questions: estimated from concept_book TX fragility)
  4. number_of_exceptions    — from strong solver reasoning trace (see extract_exception_count)

Two model-dependent meta-tags (computed from solver outputs):
  5. model_solution_length   — token count of strong solver reasoning trace, z-scored within archetype
  6. distractor_plausibility — count of explicitly-rejected paths in trace, z-scored within archetype
"""

import json
import math
import os
import re

_NORM_STATS = None
_NORM_STATS_PATH = os.path.join(os.path.dirname(__file__), "..", "calibration", "meta_tag_norm_stats.json")

def _load_norm_stats(norm_stats_path: str = None):
    global _NORM_STATS
    global _NORM_STATS_PATH
    path = norm_stats_path or _NORM_STATS_PATH
    if _NORM_STATS is None or (norm_stats_path and path != _NORM_STATS_PATH):
        with open(path, encoding="utf-8") as f:
            _NORM_STATS = json.load(f)
        _NORM_STATS_PATH = path
    return _NORM_STATS


# ── IUPAC token pattern ────────────────────────────────────────────────────
_IUPAC_PATTERN = re.compile(
    r'\b(meth|eth|prop|but|pent|hex|hept|oct|non|dec|'
    r'cyclo|benz|phenyl|naph|toluene|xylene|aniline|'
    r'vinyl|allyl|acetyl|formyl|acetate|formate|'
    r'chloro|bromo|iodo|fluoro|nitro|amino|hydroxy|oxo|'
    r'carboxyl|aldehyde|ketone|ester|amide|anhydride|'
    r'alkyl|aryl|acyl|alkene|alkyne|alkane|'
    r'enantiomer|diastereomer|stereoisomer|racemic|meso|'
    r'ortho|meta|para|cis|trans|[RSZEW]-)'
    r'[\w\-]*',
    re.IGNORECASE
)

# Exception/distractor keywords in solver traces
_EXCEPTION_PATTERN = re.compile(
    r'\b(however|but not|cannot|incorrect|wrong|not applicable|'
    r'anomalous|atypical|irregular|abnormal|unusual|special case|'
    r'exception|except|excluding|unless|would not|does not|'
    r'rejected|ruled out|discarded|eliminated|not the answer)\b',
    re.IGNORECASE
)


def _zscore_to_15(z: float) -> int:
    """Map z-score to 1–5 scale: mean→3, ±1σ→1.5 steps."""
    return max(1, min(5, round(z * 1.5 + 3)))


def _zscore(value: float, mean: float, std: float) -> float:
    return (value - mean) / max(std, 1e-9)


def _archetype_stats(norm_stats: dict, archetype_code: str, metric: str) -> tuple:
    pa = norm_stats["per_archetype"].get(archetype_code, {})
    entry = pa.get(metric, {}) or {}
    mean = entry.get("mean")
    std  = entry.get("std")
    return (mean if mean is not None else 0.0), (std if std is not None else 1.0)


# ── Public API ─────────────────────────────────────────────────────────────

def iupac_density(text: str) -> float:
    words = text.split()
    if not words:
        return 0.0
    return len(_IUPAC_PATTERN.findall(text)) / len(words)


def extract_exception_count(solver_trace: str) -> int:
    """Count exception/rejection signals in strong solver reasoning trace."""
    return len(_EXCEPTION_PATTERN.findall(solver_trace))


def extract_distractor_count(solver_trace: str) -> int:
    """
    Count explicitly-rejected alternative paths in a solver trace.
    Look for 'not X because', 'X is wrong because', 'ruled out', etc.
    """
    reject_pattern = re.compile(
        r'(ruled out|not correct|incorrect because|wrong because|'
        r'eliminated|discarded|rejected|cannot be|would not work|'
        r'not applicable here|this is not)',
        re.IGNORECASE
    )
    return len(reject_pattern.findall(solver_trace))


def compute_meta_tags(
    question_text: str,
    archetype_code: str,
    solver_trace: str = None,
    fragility_weight: float = None,
    norm_stats_path: str = None,
) -> dict:
    """
    Compute all 6 meta-tags for a question.

    Args:
        question_text:   The generated question string.
        archetype_code:  One of "I", "II", "III", "IV".
        solver_trace:    Strong solver full reasoning trace (enables tags 4, 5, 6).
        fragility_weight: 1 - (pct_full_marks/100). For generated questions,
                          pass None to use archetype mean as estimate.
        norm_stats_path: Optional path to a subject-specific normalization stats
                          JSON file. Defaults to the organic chem calibration file.

    Returns:
        dict with keys: question_length_scope, semantic_obfuscation,
        conceptual_fragility, number_of_exceptions,
        model_solution_length, distractor_plausibility.
        Values are integers 1–5, or None if data unavailable.
    """
    ns = _load_norm_stats(norm_stats_path)

    # Solvers can return attempted_solution as a nested dict instead of a string.
    # Coerce so downstream word/exception/distractor counts operate on text.
    if solver_trace is not None and not isinstance(solver_trace, str):
        solver_trace = json.dumps(solver_trace)

    # 1. Question length/scope — word count, archetype-normalized
    wc = len(question_text.split())
    ql_mean, ql_std = _archetype_stats(ns, archetype_code, "question_length_scope")
    tag_ql = _zscore_to_15(_zscore(wc, ql_mean, ql_std))

    # 2. Semantic obfuscation — IUPAC density, globally normalized
    iu_dens = iupac_density(question_text)
    g = ns["global"]["semantic_obfuscation"]
    tag_so = _zscore_to_15(_zscore(iu_dens, g["mean"], g["std"]))

    # 3. Conceptual fragility — fragility_weight, archetype-normalized
    fr_mean, fr_std = _archetype_stats(ns, archetype_code, "conceptual_fragility")
    if fragility_weight is not None:
        tag_cf = _zscore_to_15(_zscore(fragility_weight, fr_mean, fr_std))
    else:
        tag_cf = 3  # default to archetype mean when no JIC data available

    # 4–6. Model-dependent — require solver trace
    if solver_trace:
        trace_words = len(solver_trace.split())
        sl_mean, sl_std = _archetype_stats(ns, archetype_code, "model_solution_length")
        tag_msl = _zscore_to_15(_zscore(trace_words, sl_mean, sl_std))

        ex_count = extract_exception_count(solver_trace)
        ex_mean, ex_std = _archetype_stats(ns, archetype_code, "number_of_exceptions")
        tag_ex = _zscore_to_15(_zscore(ex_count, ex_mean, ex_std))

        dist_count = extract_distractor_count(solver_trace)
        dp_mean, dp_std = _archetype_stats(ns, archetype_code, "distractor_plausibility")
        tag_dp = _zscore_to_15(_zscore(dist_count, dp_mean, dp_std))
    else:
        tag_msl = None
        tag_ex  = None
        tag_dp  = None

    return {
        "question_length_scope":   tag_ql,
        "semantic_obfuscation":    tag_so,
        "conceptual_fragility":    tag_cf,
        "number_of_exceptions":    tag_ex,
        "model_solution_length":   tag_msl,
        "distractor_plausibility": tag_dp,
    }


def archetype_code_from_label(label: str) -> str:
    """Convert full archetype label to code."""
    mapping = {
        "Long Reaction Chains": "I",
        "Counting/Enumeration": "II",
        "Deep Mechanistic Reasoning": "III",
        "Comparative Ranking (GOC)": "IV",
        "I": "I", "II": "II", "III": "III", "IV": "IV",
    }
    return mapping.get(label, "III")
