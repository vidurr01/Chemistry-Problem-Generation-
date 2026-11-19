"""
subject_config.py — single source of truth for subject-specific settings used by
run_groundup_final.py.

Add a new subject by adding one entry to SUBJECT_CONFIGS. No other file should
need subject-specific branching beyond reading fields off this config via --subject.

The pipeline (core/pipeline) and graph traversal stay subject-agnostic — what changes
per subject here is: which concept book and knowledge graph are loaded, which
coverage/output files are written to, and the labels put on a saved question. The
chemistry itself is the subject's engine (core/engine, wired in core/pipeline/adapters.py);
a subject listed here without an engine there cannot generate questions yet.
"""

import os

_HERE = os.path.dirname(os.path.abspath(__file__))
# Runtime state written by the entrypoints (accepted questions, coverage, attempt logs).
OUTPUT_DIR = os.path.join(_HERE, "outputs")
os.makedirs(OUTPUT_DIR, exist_ok=True)

SUBJECT_CONFIGS = {
    "organic": {
        "display_name":     "Organic Chemistry",
        "concept_book_path": os.path.join(_HERE, "knowledge", "concept_book.json"),
        "graph_path":        os.path.join(_HERE, "knowledge", "reaction_graph.json"),
        "norm_stats_path":   os.path.join(_HERE, "calibration", "meta_tag_norm_stats.json"),
        "coverage_state_file": os.path.join(OUTPUT_DIR, "coverage_state_organic.json"),
        "output_file":       os.path.join(OUTPUT_DIR, "generated_questions_organic.json"),
        # Verifier-passed questions whose council check failed (API error); rechecked first next run.
        "pending_file":      os.path.join(OUTPUT_DIR, "pending_questions_organic.json"),
        "default_archetype": "Long Reaction Chains",
        "default_archetype_code": "I",
    },

    "inorganic": {
        "display_name":     "Inorganic Chemistry",
        "concept_book_path": os.path.join(_HERE, "knowledge", "concept_book_inorg.json"),
        # Species graph, built by `python tools/build_graph.py --subject inorganic`.
        "graph_path":        os.path.join(_HERE, "knowledge", "reaction_graph_inorg.json"),
        "norm_stats_path":   os.path.join(_HERE, "data", "seeds", "meta_tag_norm_stats_inorganic.json"),
        "coverage_state_file": os.path.join(OUTPUT_DIR, "coverage_state_inorganic.json"),
        "output_file":       os.path.join(OUTPUT_DIR, "generated_questions_inorganic.json"),
        # Verifier-passed questions whose council check failed (API error); rechecked first next run.
        "pending_file":      os.path.join(OUTPUT_DIR, "pending_questions_inorganic.json"),
        "default_archetype": "Reaction & Transformation Chains",
        "default_archetype_code": "I",
    },

    "physical": {
        "display_name":     "Physical Chemistry",
        # Phase 0 — physical concept book (same schema as organic/inorganic's).
        "concept_book_path": os.path.join(_HERE, "knowledge", "concept_book_physical.json"),
        # Quantity graph, built by `python tools/build_graph.py --subject physical`.
        "graph_path":        os.path.join(_HERE, "knowledge", "reaction_graph_physical.json"),
        "norm_stats_path":   os.path.join(_HERE, "data", "seeds", "meta_tag_norm_stats_physical.json"),
        "coverage_state_file": os.path.join(OUTPUT_DIR, "coverage_state_physical.json"),
        "output_file":       os.path.join(OUTPUT_DIR, "generated_questions_physical.json"),
        # Verifier-passed questions whose council check failed (API error); rechecked first next run.
        "pending_file":      os.path.join(OUTPUT_DIR, "pending_questions_physical.json"),
        "default_archetype": "Multi-Formulae",
        "fact_share": 0.25,      # share of runs that make a fact (MCQ/MSQ) question instead of a chain
        "default_archetype_code": "I",
    },
}


def get_subject_config(subject: str) -> dict:
    if subject not in SUBJECT_CONFIGS:
        raise ValueError(f"Unknown subject '{subject}'. Choices: {list(SUBJECT_CONFIGS)}")
    return SUBJECT_CONFIGS[subject]


# ── Coverage and meta-tag helpers ─────────────────────────────────────────────
# Each subject has its own coverage state file and its own meta-tag norm stats.
# (Earlier versions caught TypeError here and fell back to a shared coverage file /
# the organic norm stats — which would also have swallowed real errors and silently
# used the wrong subject's data.)

def load_coverage_for_subject(config: dict):
    from core.coverage import Coverage
    return Coverage.load(config["coverage_state_file"])


def save_coverage(coverage, config: dict):
    coverage.save(config["coverage_state_file"])


def compute_meta_tags_for_subject(config: dict, **kwargs):
    from core.meta_tags import compute_meta_tags
    return compute_meta_tags(norm_stats_path=config["norm_stats_path"], **kwargs)
