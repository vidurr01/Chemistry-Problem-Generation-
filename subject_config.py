"""
subject_config.py — single source of truth for subject-specific settings used by
run_groundup_final.py.

Add a new subject by adding one entry to SUBJECT_CONFIGS. No other file should
need subject-specific branching beyond reading fields off this config via --subject.

Generator / Verifier / Solver LOGIC and graph traversal (core/*.py) stay
subject-agnostic — what changes per subject is: which concept book and knowledge
graph are loaded, which coverage/output files are written to, and the wording
plugged into the (subject-agnostic) prompt templates.
"""

import os

_HERE = os.path.dirname(os.path.abspath(__file__))
# Runtime state written by the entrypoints (accepted questions, coverage, attempt logs).
OUTPUT_DIR = os.path.join(_HERE, "outputs")
os.makedirs(OUTPUT_DIR, exist_ok=True)

SUBJECT_CONFIGS = {
    "organic": {
        "display_name":     "Organic Chemistry",
        "chemist_role":     "organic chemist",
        "concept_book_path": os.path.join(_HERE, "knowledge", "concept_book.json"),
        "graph_path":        os.path.join(_HERE, "knowledge", "reaction_graph.json"),
        "norm_stats_path":   os.path.join(_HERE, "calibration", "meta_tag_norm_stats.json"),
        "coverage_state_file": os.path.join(OUTPUT_DIR, "coverage_state_organic.json"),
        "output_file":       os.path.join(OUTPUT_DIR, "generated_questions_organic.json"),
        # Verifier-passed questions whose council check failed (API error); rechecked first next run.
        "pending_file":      os.path.join(OUTPUT_DIR, "pending_questions_organic.json"),
        # Fallback label for prompt helpers called without one. Runs take chains from the
        # whole graph (any chapter) unless --chapter restricts them.
        "default_chapter":   "Hydrocarbons",
        "default_archetype": "Long Reaction Chains",
        "default_archetype_code": "I",
        "seed_id_prefix":    "HYDRO",

        # Where chains may start. Empty = every graph node marked can_be_start.
        "start_nodes": [],

        "mandatory_checks_block": """1. MOLECULAR FORMULA TRACKING: Write the molecular formula of the starting compound,
   then propagate it step by step, accounting for every atom added or removed by each
   reagent. The degree of unsaturation (DoU = (2C + 2 + N - H - X) / 2) must change
   by the correct amount at each step. If the arithmetic does not balance, redesign.
2. ALL FUNCTIONAL GROUPS PRESENT: After each step, list ALL active functional groups
   in the molecule — not just the one being transformed.
3. NON-CIRCULARITY: The final product must be chemically distinct from the starting
   material.
4. STEREODESCRIPTOR VALIDITY: Any E/Z label requires two distinct groups on each sp2
   carbon. Any R/S label requires four distinct substituents. Remove descriptors with
   no stereogenic element.
5. DIFFICULTY LEVER TEST: If a condition is a difficulty lever, changing it must give
   a different final product, or it's decorative — remove or replace it.""",

        "verifier_checks_block": """CHECK 1 — FORMULA CONSERVATION: atoms must balance at every step; DoU changes must
match the reaction type (dehydration +1, hydrogenation -1, substitution unchanged).
CHECK 2 — ALL FUNCTIONAL GROUPS TRACKED: no functional group silently disappears
between steps unless it genuinely reacted.
CHECK 3 — STEREODESCRIPTOR VALIDITY: every E/Z or R/S label requires a genuine
stereogenic element.
CHECK 4 — NON-CIRCULARITY: final product must differ from the starting material.
CHECK 5 — ANSWER AGREEMENT: candidate's final answer must match your independent answer.
CHECK 6 — DIFFICULTY LEVER VALIDITY: note (don't fail) any decorative condition.""",
    },

    "inorganic": {
        "display_name":     "Inorganic Chemistry",
        "chemist_role":     "inorganic chemist",
        "concept_book_path": os.path.join(_HERE, "knowledge", "concept_book_inorg.json"),
        # Species graph, built by `python tools/build_graph.py --subject inorganic`.
        "graph_path":        os.path.join(_HERE, "knowledge", "reaction_graph_inorg.json"),
        "norm_stats_path":   os.path.join(_HERE, "data", "seeds", "meta_tag_norm_stats_inorganic.json"),
        "coverage_state_file": os.path.join(OUTPUT_DIR, "coverage_state_inorganic.json"),
        "output_file":       os.path.join(OUTPUT_DIR, "generated_questions_inorganic.json"),
        # Verifier-passed questions whose council check failed (API error); rechecked first next run.
        "pending_file":      os.path.join(OUTPUT_DIR, "pending_questions_inorganic.json"),
        "default_chapter":   "hydrolysis",
        "default_archetype": "Reaction & Transformation Chains",
        "default_archetype_code": "I",
        "seed_id_prefix":    "INORG",

        # Where chains may start. Empty = every graph node marked can_be_start.
        "start_nodes": [],

        "mandatory_checks_block": """1. OXIDATION STATE / CHARGE BALANCE: Track oxidation states and overall charge
   at every step. Redox steps must show electrons gained/lost balancing exactly.
2. COORDINATION NUMBER / GEOMETRY TRACKING: For complexes, track coordination number,
   ligand identity, and geometry (e.g. octahedral, tetrahedral, square planar) at each step.
3. NON-CIRCULARITY: The final product must be chemically distinct from the starting
   material.
4. EXCEPTION VALIDITY: Any cited periodic-trend exception (e.g. inert pair effect,
   lanthanide contraction anomaly) must genuinely apply to the species involved —
   don't invoke an exception that doesn't fit the actual electron configuration.
5. DIFFICULTY LEVER TEST: If a condition (temperature, concentration, pH) is a
   difficulty lever, changing it must give a different product/observation, or it's
   decorative — remove or replace it.""",

        "verifier_checks_block": """CHECK 1 — CHARGE / OXIDATION STATE CONSERVATION: charges and oxidation states must
balance at every step; redox electron counts must be exact.
CHECK 2 — COORDINATION CHEMISTRY CONSISTENCY: coordination number, ligand set, and
geometry must be tracked and chemically valid at each step.
CHECK 3 — EXCEPTION VALIDITY: any periodic-trend exception invoked must genuinely
apply to the species in question.
CHECK 4 — NON-CIRCULARITY: final product must differ from the starting material.
CHECK 5 — ANSWER AGREEMENT: candidate's final answer must match your independent answer.
CHECK 6 — DIFFICULTY LEVER VALIDITY: note (don't fail) any decorative condition.""",
    },

    "physical": {
        "display_name":     "Physical Chemistry",
        "chemist_role":     "physical chemist",
        # Phase 0 — physical concept book (same schema as organic/inorganic's).
        "concept_book_path": os.path.join(_HERE, "knowledge", "concept_book_physical.json"),
        # Quantity graph, built by `python tools/build_graph.py --subject physical`.
        "graph_path":        os.path.join(_HERE, "knowledge", "reaction_graph_physical.json"),
        "norm_stats_path":   os.path.join(_HERE, "data", "seeds", "meta_tag_norm_stats_physical.json"),
        "coverage_state_file": os.path.join(OUTPUT_DIR, "coverage_state_physical.json"),
        "output_file":       os.path.join(OUTPUT_DIR, "generated_questions_physical.json"),
        # Verifier-passed questions whose council check failed (API error); rechecked first next run.
        "pending_file":      os.path.join(OUTPUT_DIR, "pending_questions_physical.json"),
        "default_chapter":   "Chemical Kinetics & Nuclear Chemistry",
        "default_archetype": "Multi-Formulae",
        "default_archetype_code": "I",
        "seed_id_prefix":    "PHYS",

        "start_nodes": [],  # every graph node marked can_be_start

        "mandatory_checks_block": """1. FORMULA / UNIT CONSISTENCY: Every quantity must carry correct units throughout;
   final answer's units must match what's asked (verify dimensionally).
2. DERIVATION VALIDITY: If the question relies on a derived formula, the derivation
   steps must be shown and must not skip a required approximation/assumption.
3. NON-TRIVIALITY: The final answer must not be obtainable by a shortcut that
   bypasses the concept being tested (e.g. all given numbers should be necessary).
4. GRAPH/TREND CONSISTENCY: If a graph or trend is described in words, verify the
   described shape/slope/intercept is physically correct for the underlying law.
5. DIFFICULTY LEVER TEST: If a given condition (temperature, pressure, catalyst) is
   a difficulty lever, changing it must change the final answer, or it's decorative.""",

        "verifier_checks_block": """CHECK 1 — UNIT / DIMENSIONAL CONSISTENCY: every quantity must carry correct units;
final answer units must match what's asked.
CHECK 2 — DERIVATION VALIDITY: any formula used must be derived/cited correctly for
the stated conditions (ideal vs real gas, reversible vs irreversible, etc.).
CHECK 3 — NON-TRIVIALITY: no given numeric value should be unused; no shortcut should
bypass the tested concept.
CHECK 4 — GRAPH/TREND CONSISTENCY: any described graph shape must match the underlying
physical law.
CHECK 5 — ANSWER AGREEMENT: candidate's final answer must match your independent answer.
CHECK 6 — DIFFICULTY LEVER VALIDITY: note (don't fail) any decorative condition.""",
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
