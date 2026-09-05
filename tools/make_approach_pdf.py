"""
Generate approach document PDF describing the actual question generation pipeline.
"""
import os
import sys
sys.stdout.reconfigure(encoding="utf-8")
sys.stderr.reconfigure(encoding="utf-8")
from reportlab.lib.pagesizes import A4
from reportlab.lib.styles import ParagraphStyle
from reportlab.lib.units import cm
from reportlab.lib import colors
from reportlab.platypus import (
    SimpleDocTemplate, Paragraph, Spacer, Table, TableStyle,
    HRFlowable, KeepTogether
)
from reportlab.lib.enums import TA_LEFT, TA_CENTER, TA_JUSTIFY

OUT = os.path.join(os.path.expanduser("~"), "Downloads", "QuestionGen_Approach.pdf")

NAVY  = colors.HexColor("#1A2B4A")
TEAL  = colors.HexColor("#0F7B8C")
LGRAY = colors.HexColor("#F4F6F9")
DGRAY = colors.HexColor("#5A6270")
WHITE = colors.white
BLACK = colors.black

# ── Shared paragraph styles ────────────────────────────────────────────────────
def mk(name, **kw):
    return ParagraphStyle(name, **kw)

HDR_TITLE    = mk("hdrtitle",  fontName="Helvetica-Bold", fontSize=22, leading=28,
                  textColor=WHITE, alignment=TA_CENTER, spaceAfter=4)
HDR_SUB      = mk("hdrsub",    fontName="Helvetica",      fontSize=11, leading=16,
                  textColor=colors.HexColor("#D0E8F2"), alignment=TA_CENTER, spaceAfter=2)
H1           = mk("h1",        fontName="Helvetica-Bold", fontSize=14, leading=18,
                  textColor=NAVY, spaceBefore=18, spaceAfter=6)
BODY         = mk("body",      fontName="Helvetica",      fontSize=9.5, leading=14,
                  textColor=BLACK, spaceAfter=4, alignment=TA_JUSTIFY)
CODE         = mk("code",      fontName="Courier",        fontSize=8.5, leading=13,
                  textColor=colors.HexColor("#222244"), backColor=LGRAY,
                  borderPad=4, leftIndent=10, spaceAfter=3)
BULL         = mk("bull",      fontName="Helvetica",      fontSize=9.5, leading=13,
                  textColor=BLACK, leftIndent=16, firstLineIndent=-10, spaceAfter=3)
CAPTION      = mk("caption",   fontName="Helvetica",      fontSize=8.5, leading=12,
                  textColor=DGRAY, alignment=TA_CENTER)
# Cell styles — used inside table cells so text wraps correctly
TH           = mk("th",        fontName="Helvetica-Bold", fontSize=8.5, leading=12,
                  textColor=WHITE)
TD           = mk("td",        fontName="Helvetica",      fontSize=8.5, leading=12,
                  textColor=BLACK)
TD_BOLD      = mk("tdbold",    fontName="Helvetica-Bold", fontSize=8.5, leading=12,
                  textColor=NAVY)
TD_TEAL      = mk("tdteal",    fontName="Helvetica-Bold", fontSize=8.5, leading=12,
                  textColor=TEAL)

def H(t):    return Paragraph(t, H1)
def B(t):    return Paragraph(t, BODY)
def BU(t):   return Paragraph(f"&bull;&nbsp;&nbsp;{t}", BULL)
def Code(t): return Paragraph(
    t.replace(" ", "&nbsp;").replace("<","&lt;").replace(">","&gt;"), CODE)
def Sp(n=6): return Spacer(1, n)
def HR():    return HRFlowable(width="100%", thickness=0.5,
                               color=colors.HexColor("#CCCCCC"), spaceAfter=6, spaceBefore=2)

# ── Table helper — every cell is a Paragraph so text wraps ────────────────────
def mktbl(rows_raw, col_fracs, doc, header_bg=NAVY, stripe=True):
    """
    rows_raw: list of lists of strings (or Paragraphs).
    First row = header (white bold text on header_bg background).
    Subsequent rows = body (alternating LGRAY/WHITE if stripe=True).
    col_fracs: list of width fractions summing to ~1.0
    """
    col_w = [doc.width * f for f in col_fracs]

    def cell(text, style):
        if isinstance(text, Paragraph):
            return text
        return Paragraph(str(text), style)

    rows = []
    for i, row in enumerate(rows_raw):
        sty = TH if i == 0 else TD
        rows.append([cell(c, sty) for c in row])

    t = Table(rows, colWidths=col_w, repeatRows=1)
    style_cmds = [
        ("BACKGROUND",    (0, 0), (-1, 0),  header_bg),
        ("FONTNAME",      (0, 0), (-1, 0),  "Helvetica-Bold"),
        ("TOPPADDING",    (0, 0), (-1, -1), 5),
        ("BOTTOMPADDING", (0, 0), (-1, -1), 5),
        ("LEFTPADDING",   (0, 0), (-1, -1), 6),
        ("RIGHTPADDING",  (0, 0), (-1, -1), 6),
        ("VALIGN",        (0, 0), (-1, -1), "TOP"),
        ("GRID",          (0, 0), (-1, -1), 0.4, colors.HexColor("#BBBBBB")),
    ]
    if stripe:
        style_cmds.append(("ROWBACKGROUNDS", (0, 1), (-1, -1), [LGRAY, WHITE]))
    t.setStyle(TableStyle(style_cmds))
    return t

def header_box(doc):
    rows = [
        [Paragraph("JEE Advanced Organic Chemistry", HDR_TITLE)],
        [Paragraph("Automated Question Generation Pipeline — Architecture & Design", HDR_SUB)],
        [Paragraph("Prahlada · JEEGen v1.0 · June 2026", HDR_SUB)],
    ]
    t = Table(rows, colWidths=[doc.width])
    t.setStyle(TableStyle([
        ("BACKGROUND",    (0, 0), (-1, -1), NAVY),
        ("TOPPADDING",    (0, 0), (-1, -1), 14),
        ("BOTTOMPADDING", (0, 0), (-1, -1), 10),
        ("LEFTPADDING",   (0, 0), (-1, -1), 20),
        ("RIGHTPADDING",  (0, 0), (-1, -1), 20),
    ]))
    return t

# ── Document body ──────────────────────────────────────────────────────────────
def build(doc):
    s = []
    s += [header_box(doc), Sp(20)]

    # ── 1. Overview ───────────────────────────────────────────────────────────
    s += [H("1. Overview"), HR()]
    s.append(B(
        "This pipeline takes real JEE Advanced questions (<b>seeds</b>), augments them into "
        "harder variants using a structured knowledge base (<b>concept_book.json</b>), and "
        "validates each generated question through three independent gates before accepting it. "
        "The process is stateful — every attempt is recorded on a <b>Blackboard</b> so the "
        "generator refines in place rather than restarting from scratch."
    ))
    s += [Sp(4)]

    s.append(mktbl([
        ["File",                  "Role"],
        ["pipeline.py",           "Top-level orchestrator — runs the full loop for each seed"],
        ["run_live.py",           "Live runner — wires real models (SambaNova + Ollama) instead of mocks"],
        ["blackboard.py",         "Stateful context object — records every attempt, verdict, and score"],
        ["concept_reasoner.py",   "RLM — reads blackboard + concept_book, selects operators to apply"],
        ["generator.py",          "LLM — writes the augmented problem and solution from RLM-selected operators"],
        ["verifier.py",           "Blind solver — independently solves the problem, checks chemistry"],
        ["strong_solver.py",      "Strong RLM — attempts the problem; score ≥ threshold confirms it is solvable"],
        ["weak_solver.py",        "Weak model — attempts the problem; score ≤ threshold confirms it is hard enough"],
        ["classifier.py",         "Classifies seed questions into archetypes (I / II / III / IV)"],
        ["concept_book.json",     "Knowledge base — 2,234 operators across TX / FRAG / EXC / DIST arrays"],
        ["classified_seeds.json", "Seed pool — JEE questions labelled with archetype"],
    ], [0.28, 0.72], doc))
    s += [Sp(12)]

    # ── 2. Pipeline Loop ──────────────────────────────────────────────────────
    s += [H("2. The Generation Loop"), HR()]
    s.append(B(
        "For each seed the pipeline runs up to <b>4 attempts</b> (1 initial + 3 retries). "
        "All attempts share one Blackboard so later passes have full context on what failed and why."
    ))
    s += [Sp(6)]

    s.append(mktbl([
        ["Step", "Component",                    "What it does"],
        ["1",    "Concept Reasoner (RLM / o3)",
         "Reads full blackboard history + concept_book.json. Selects 1–3 operators and their "
         "exact parameters. Avoids operators that failed on previous attempts. If weak score "
         "was too high, pushes harder on interpretive operators. If strong score was too low, "
         "backs off difficulty to restore feasibility."],
        ["2",    "Generator (LLM / GPT-4o)",
         "Takes seed + RLM-selected operators + blackboard history. On attempt 1: generates "
         "augmented problem from scratch. On retries: receives previous problem, verifier "
         "feedback, and scores — fixes only the flagged issue; everything else stays intact."],
        ["3",    "Verifier (Strong LLM)",
         "Blind-solves the generated problem independently (does not read the candidate "
         "solution). Compares to candidate solution, checks for functional-group "
         "incompatibilities, infeasible mechanisms, wrong stereochemistry. Returns PASS/FAIL "
         "plus actionable feedback."],
        ["4",    "Weak Solver (llama3.2 / Ollama)",
         "Undergraduate-level model attempts the problem without extended reasoning. "
         "Score ≤ ceiling required — ensures the question is genuinely hard for a weaker solver."],
        ["5",    "Strong Solver (DeepSeek-V3.2 / SambaNova)",
         "Expert-level model with full chain-of-thought attempts the problem. "
         "Score ≥ floor required — ensures the question is valid and mechanistically solvable. "
         "A score below the floor means the problem is broken or ambiguous."],
        ["6",    "Acceptance check",
         "All three gates must pass simultaneously. If any fails, the failure reason is written "
         "to the Blackboard and the loop retries. After max retries the best attempt is "
         "saved with status FAILED."],
    ], [0.06, 0.22, 0.72], doc))
    s += [Sp(12)]

    # ── 3. Two Independent Difficulty Metrics ─────────────────────────────────
    s += [H("3. Two Independent Difficulty Metrics"), HR()]
    s.append(B(
        "The acceptance gate uses <b>two separate thresholds</b>, not a single difficulty score "
        "and not a gap between them. They measure orthogonal properties of the question."
    ))
    s += [Sp(4)]

    s.append(mktbl([
        ["Metric",             "Threshold",   "What it measures",
         "Failure means"],
        ["Strong solver score","≥ floor",
         "Problem validity — can an expert solve it correctly?",
         "STRONG_TOO_LOW: the generated problem is broken, ambiguous, or chemically infeasible"],
        ["Weak solver score",  "≤ ceiling",
         "Problem difficulty — is it actually hard for a non-expert?",
         "WEAK_TOO_HIGH: the problem is trivial; any student can answer it"],
    ], [0.20, 0.12, 0.33, 0.35], doc))
    s += [Sp(6)]
    s.append(B(
        "A question with strong=85%, weak=40% is accepted: solvable by an expert, hard for a "
        "weak model. A question with strong=85%, weak=80% is rejected (too easy). A question "
        "with strong=45%, weak=30% is also rejected (problem is broken). <b>Never collapse "
        "these into a gap metric.</b> The exact floor and ceiling values are calibrated by "
        "running real JEE Advanced organic chemistry questions through both solvers."
    ))
    s += [Sp(12)]

    # ── 4. The Blackboard ─────────────────────────────────────────────────────
    s += [H("4. The Blackboard"), HR()]
    s.append(B(
        "The Blackboard is the stateful context object that makes iterative refinement "
        "possible. It accumulates the complete trace of every attempt so that both the "
        "Concept Reasoner and the Generator always work with full history."
    ))
    s += [Sp(4)]

    s.append(mktbl([
        ["Field recorded per attempt",       "Used by"],
        ["problem (generated question text)", "Generator refine-in-place prompt"],
        ["solution (candidate solution)",     "Generator refine-in-place prompt"],
        ["operators_used",                    "Concept Reasoner — avoids re-using operators that caused failures"],
        ["verifier_verdict (PASS / FAIL)",    "Acceptance check + Generator feedback"],
        ["verifier_feedback (actionable)",    "Generator refine-in-place prompt — fix only the flagged issue"],
        ["weak_score (0–100)",                "Acceptance check + Concept Reasoner difficulty adjustment"],
        ["strong_score (0–100)",              "Acceptance check + Concept Reasoner validity adjustment"],
    ], [0.48, 0.52], doc))
    s += [Sp(6)]
    s.append(B(
        "The <b>context_summary()</b> method formats the full attempt history into a readable "
        "block injected into the Concept Reasoner and Generator prompts on every pass. This is "
        "what enables targeted refinement — the generator knows exactly what failed and why "
        "without any information being lost between attempts."
    ))
    s += [Sp(12)]

    # ── 5. The Concept Book ───────────────────────────────────────────────────
    s += [H("5. concept_book.json — The Operator Library"), HR()]
    s.append(B(
        "The concept book is the structured knowledge base the RLM reasons over. "
        "It encodes organic chemistry at four levels of abstraction, each providing a different "
        "type of operator the generator can apply to a seed problem. All 2,234 entries are fully "
        "populated and use IUPAC systematic nomenclature throughout."
    ))
    s += [Sp(4)]

    s.append(mktbl([
        ["Array",                                 "Count", "Key fields",
         "Operator function"],
        ["TX — valid_transformations",            "657",
         "from, to, reagents, conditions, archetype, meta_tags",
         "Add or modify a reaction step; change substrate or reagent; extend the "
         "synthetic chain. Primary operator for Archetype I."],
        ["FRAG — conceptual_fragility.concepts", "605",
         "name, definition, why_fragile, common_error, archetype_relevance",
         "Inject a conceptual pitfall; raise the fragility score; inform distractor "
         "design via the common_error field."],
        ["EXC — number_of_exceptions.exceptions","502",
         "standard_case, exception, why_exception, exam_relevance, archetype",
         "Add an exception trap; create rule–exception pair questions; increase "
         "the number_of_exceptions meta-tag score."],
        ["DIST — distractor_plausibility.distractors","470",
         "type, description, why_attractive, correct_resolution, archetype",
         "Select a distractor blueprint; raise the distractor_plausibility score; "
         "guide construction of plausible wrong options."],
    ], [0.28, 0.06, 0.28, 0.38], doc))
    s += [Sp(12)]

    # ── 6. The Four Archetypes ────────────────────────────────────────────────
    s += [H("6. The Four Question Archetypes"), HR()]
    s.append(B(
        "Every seed, TX, EXC, and DIST entry is tagged with one or more archetypes. "
        "The archetype constrains which operators the Concept Reasoner may select and which "
        "question template the generator uses."
    ))
    s += [Sp(4)]

    s.append(mktbl([
        ["Archetype", "Name",                      "Core challenge",
         "Primary operators"],
        ["I",         "Long Reaction Chains",
         "Track intermediates through 3–6 sequential steps",
         "add_reaction_step (TX); semantic_obfuscation"],
        ["II",        "Counting / Enumeration",
         "Systematically enumerate all products, isomers, or structures",
         "conceptual_fragility (filtering criterion); distractor_plausibility"],
        ["III",       "Deep Mechanistic Reasoning",
         "Explain regiochemistry or selectivity from mechanism",
         "conceptual_fragility (rearrangement or exception); number_of_exceptions"],
        ["IV",        "Comparative Ranking / GOC",
         "Rank acidity, basicity, or reactivity via electronic effects",
         "expand_comparison_set; distractor_plausibility"],
    ], [0.08, 0.22, 0.32, 0.38], doc))
    s += [Sp(12)]

    # ── 7. The Six Meta-tags ──────────────────────────────────────────────────
    s += [H("7. The Six Meta-tag Dimensions (scored 1–5)"), HR()]
    s.append(B(
        "Each TX entry carries a <b>meta_tags</b> dict with six integer scores. They calibrate "
        "the target difficulty profile the pipeline aims for, grouped into two independent "
        "axes matching the two-threshold acceptance rule."
    ))
    s += [Sp(4)]

    s.append(mktbl([
        ["Dimension",                "Axis",         "Score 1 → Score 5",
         "How generator uses it"],
        ["Question Length / Scope",  "Q-difficulty", "Single step → Multi-step chain",
         "High score triggers add_reaction_step operator"],
        ["Model Solution Length",    "Q-difficulty", "Direct recall → Full mechanism writeup",
         "Controls expected solution depth and generator verbosity"],
        ["Conceptual Fragility",     "Q-difficulty", "Well-known rule → Counterintuitive edge case",
         "High score → RLM injects FRAG entry with matching why_fragile"],
        ["Number of Exceptions",     "Q-difficulty", "0–1 exceptions → 4+ exceptions",
         "High score → RLM injects EXC entry with exception trap"],
        ["Semantic Obfuscation",     "Q-difficulty", "Common name → Full IUPAC chain name",
         "Score ≥ 4 → generator uses IUPAC names for all substrates in options"],
        ["Distractor Plausibility",  "D-difficulty", "Obvious wrong → Mechanistically seductive",
         "High score → RLM selects DIST entry with high why_attractive score"],
    ], [0.22, 0.12, 0.28, 0.38], doc))
    s += [Sp(12)]

    # ── 8. Live Setup ─────────────────────────────────────────────────────────
    s += [H("8. Live Model Setup (run_live.py)"), HR()]
    s.append(B(
        "The mock clients in the individual module files are replaced by real API calls in "
        "<b>run_live.py</b>, which is the actual entry point for generation runs."
    ))
    s += [Sp(4)]

    s.append(mktbl([
        ["Role",              "Model",           "API endpoint",
         "Temperature"],
        ["Concept Reasoner",  "DeepSeek-V3.2",   "SambaNova (api.sambanova.ai/v1)", "0.7"],
        ["Generator",         "DeepSeek-V3.2",   "SambaNova",                       "0.7"],
        ["Verifier",          "DeepSeek-V3.2",   "SambaNova",                       "0.0 (deterministic)"],
        ["Strong Solver",     "DeepSeek-V3.2",   "SambaNova",                       "0.0"],
        ["Weak Solver",       "llama3.2",         "Ollama (localhost:11434/v1)",      "0.7"],
    ], [0.20, 0.20, 0.40, 0.20], doc))
    s += [Sp(6)]

    for pt in [
        "SambaNova calls include exponential-backoff retry (5 attempts, 15 s base wait) on HTTP 429.",
        "Strong model (DeepSeek-V3.2) acts as Concept Reasoner, Generator, Verifier, and Strong "
        "Solver — four separate prompt roles via the same SambaNova client.",
        "Weak model (llama3.2) runs locally via Ollama. No retry needed — local calls do not rate-limit.",
    ]:
        s.append(BU(pt))
    s += [Sp(12)]

    # ── 9. Acceptance Logic ───────────────────────────────────────────────────
    s += [H("9. Acceptance Logic"), HR()]
    s.append(B(
        "All three gates must pass simultaneously. Thresholds (STRONG_SCORE_FLOOR and "
        "WEAK_SCORE_CEILING) are calibrated empirically by running real JEE Advanced "
        "organic chemistry questions through both solvers before any generation run."
    ))
    s += [Sp(4)]

    for line in [
        "def check_acceptance(verifier_result, weak_result, strong_result):",
        "    # Gate 1: chemistry must be semantically valid",
        "    if verifier_result['verdict'] == 'FAIL':",
        "        return False, f\"VERIFIER_FAIL: {verifier_result['feedback_for_generator']}\"",
        "    # Gate 2: strong solver must score >= STRONG_SCORE_FLOOR",
        "    if strong_result['score'] < STRONG_SCORE_FLOOR:",
        "        return False, f\"STRONG_TOO_LOW: {strong_result['score']}%\"",
        "    # Gate 3: weak solver must score <= WEAK_SCORE_CEILING",
        "    if weak_result['score'] > WEAK_SCORE_CEILING:",
        "        return False, f\"WEAK_TOO_HIGH: {weak_result['score']}%\"",
        "    return True, 'PASS'",
    ]:
        s.append(Code(line))
    s += [Sp(12)]

    # ── Footer ────────────────────────────────────────────────────────────────
    s.append(HR())
    s.append(Paragraph("JEEGen v1.0 · Prahlada · June 2026 · Internal Document", CAPTION))

    return s


def main():
    doc = SimpleDocTemplate(
        OUT, pagesize=A4,
        leftMargin=2*cm, rightMargin=2*cm,
        topMargin=2*cm,  bottomMargin=2.2*cm,
        title="JEE Advanced — Question Generation Pipeline Architecture",
        author="Prahlada",
    )
    doc.build(build(doc))
    print(f"PDF written → {OUT}")

if __name__ == "__main__":
    main()
