"""
subject_config.py — single source of truth for subject-specific settings used by
run_groundup_final.py and run_graph_final.py.

Add a new subject by adding one entry to SUBJECT_CONFIGS. No other file should
need subject-specific branching beyond reading fields off this config via --subject.

Generator / Verifier / Solver LOGIC (core/*.py) stays subject-agnostic, as noted
in the Phase 2 plan — what changes per subject is: which knowledge files are
loaded, which coverage/output files are written to, and the wording plugged
into the (subject-agnostic) prompt templates.
"""

import os

_HERE = os.path.dirname(os.path.abspath(__file__))

SUBJECT_CONFIGS = {
    "organic": {
        "display_name":     "Organic Chemistry",
        "chemist_role":     "organic chemist",
        "concept_book_path": os.path.join(_HERE, "knowledge", "concept_book.json"),
        "graph_path":        os.path.join(_HERE, "knowledge", "reaction_graph.json"),
        "norm_stats_path":   os.path.join(_HERE, "calibration", "meta_tag_norm_stats.json"),
        "coverage_state_file": os.path.join(_HERE, "coverage_state_organic.json"),
        "output_file":       os.path.join(_HERE, "generated_questions_organic.json"),
        "default_chapter":   "Hydrocarbons",
        "default_archetype": "Long Reaction Chains",
        "default_archetype_code": "I",
        "seed_id_prefix":    "HYDRO",

        # graph-mode only: nodes with enough outgoing edges to seed synthesis chains
        "start_nodes": ["alkane", "alkene", "alkyne", "diene_conjugated",
                        "cycloalkane", "cycloalkene"],

        # groundup-mode only: concept_book.json isn't chapter-tagged per TX, so we
        # filter by keyword match against from/to/reagents instead
        "tx_filter_mode":  "regex",
        "tx_filter_regex": (
            r'\b(alkan|alken|alkyn|alkane|alkene|alkyne|cycloalk|cyclopent|cyclohex|cyclohept|'
            r'methane|ethane|propane|butane|pentane|hexane|heptane|octane|'
            r'methyl|ethyl|propyl|butyl|vinyl|allyl|propargyl|'
            r'hydrocarbon|radical halogen|ozonolysis|birch|lindlar|'
            r'hydrogenation|dehydrogen|dehydrat|markovnikov|hydroboration)\b'
        ),

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
        # Built by `python3 tools/build_graph.py --subject inorganic` (Phase 0 TODO —
        # may not exist yet; run_graph_final.py will error clearly if it's missing).
        "graph_path":        os.path.join(_HERE, "knowledge", "reaction_graph_inorg.json"),
        "norm_stats_path":   os.path.join(_HERE, "data", "seeds", "meta_tag_norm_stats_inorganic.json"),
        "coverage_state_file": os.path.join(_HERE, "coverage_state_inorganic.json"),
        "output_file":       os.path.join(_HERE, "generated_questions_inorganic.json"),
        "default_chapter":   "hydrolysis",
        "default_archetype": "Reaction & Transformation Chains",
        "default_archetype_code": "I",
        "seed_id_prefix":    "INORG",

        # graph-mode only: placeholder node ids — replace with real node ids once
        # reaction_graph_inorg.json exists (Phase 0 TODO). Keeping this list here
        # (rather than hardcoding in run_graph_final.py) is what makes --subject
        # work once that file lands.
        "start_nodes": ["coordination_complex", "metal_salt", "metal_oxide",
                        "metal_hydroxide", "metal_hydride"],

        # groundup-mode only: concept_book_inorg.json TXs carry an explicit
        # "source_chapter" field (added during the Phase 0 chapter merge), so we
        # filter by that field + archetype instead of a keyword regex.
        "tx_filter_mode": "chapter_field",
        "chapter_field_key": "source_chapter",

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
        "graph_path":        None,   # no reaction graph for Physical — ground-up only
        "norm_stats_path":   os.path.join(_HERE, "data", "seeds", "meta_tag_norm_stats_physical.json"),
        "coverage_state_file": os.path.join(_HERE, "coverage_state_physical.json"),
        "output_file":       os.path.join(_HERE, "generated_questions_physical.json"),
        "default_chapter":   "Chemical Kinetics & Nuclear Chemistry",
        "default_archetype": "Multi-Formulae",
        "default_archetype_code": "I",
        "seed_id_prefix":    "PHYS",

        "start_nodes": [],  # N/A — no graph

        "tx_filter_mode": "chapter_field",
        "chapter_field_key": "chapter",

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


# ── Coverage helpers ───────────────────────────────────────────────────────────
# Coverage's exact save/load signature isn't finalized across subjects yet, so
# these wrappers try the "accepts an explicit path" API first and fall back to
# monkeypatching the instance/module if Coverage only supports a single hardcoded
# filename. Once core/coverage.py officially supports a `state_file` argument,
# the fallback branches below become dead code (harmless to leave in place).

def load_coverage_for_subject(config: dict):
    from core.coverage import Coverage
    state_file = config["coverage_state_file"]
    try:
        return Coverage.load(state_file)
    except TypeError:
        pass
    try:
        return Coverage.load(path=state_file)
    except TypeError:
        pass
    # Last resort: load default, then retarget the instance's save path so
    # save_coverage() below writes to the right file.
    cov = Coverage.load()
    cov._subject_state_file_override = state_file
    return cov


def save_coverage(coverage, config: dict):
    state_file = config["coverage_state_file"]
    try:
        coverage.save(state_file)
        return
    except TypeError:
        pass
    try:
        coverage.save(path=state_file)
        return
    except TypeError:
        pass
    coverage.save()  # falls back to whatever default core/coverage.py uses


def compute_meta_tags_for_subject(config: dict, **kwargs):
    from core.meta_tags import compute_meta_tags
    try:
        return compute_meta_tags(norm_stats_path=config["norm_stats_path"], **kwargs)
    except TypeError:
        # Older signature without norm_stats_path — falls back to whatever file
        # core/meta_tags.py has hardcoded (will be organic's unless updated).
        return compute_meta_tags(**kwargs)
