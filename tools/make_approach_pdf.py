"""
Generate the approach document PDF (docs/QuestionGen_Approach.pdf).

The file table reflects the current code; the narrative sections (generation loop,
verifier) still describe the pipeline before the engine/council redesign of
2026-10-13 and need rewriting before the PDF is regenerated for the new pipeline.
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
    HRFlowable
)
from reportlab.lib.enums import TA_CENTER, TA_JUSTIFY

OUT = os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", "docs", "QuestionGen_Approach.pdf")

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
        [Paragraph("JEE Advanced Chemistry", HDR_TITLE)],
        [Paragraph("Automated Question Generation Pipeline — Architecture &amp; Design", HDR_SUB)],
        [Paragraph("Prahlada · organic · inorganic · physical · October 2026", HDR_SUB)],
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
        "The pipeline writes JEE Advanced chemistry questions from scratch for three subjects — "
        "organic, inorganic and physical — and validates each one before it enters the dataset. "
        "Every question is built on a <b>chain through the subject's knowledge graph</b>, so each "
        "step is a real transformation from the concept book. A candidate must pass a "
        "<b>two-tier verifier</b>, then be hard enough for a <b>council of three solvers</b> that "
        "work blind. No model grades its own output. Every attempt is recorded on a "
        "<b>Blackboard</b>, so a failing question is repaired in place rather than restarted."
    ))
    s += [Sp(4)]

    s.append(mktbl([
        ["File",                       "Role"],
        ["run_groundup_final.py",      "Entry point — one accepted question per run (OpenRouter)"],
        ["generate_questions.py",      "Batch driver — N questions per subject, each in a fresh process"],
        ["subject_config.py",          "Per-subject paths, prompts, default chapter and archetype"],
        ["core/graph_traversal.py",    "Knowledge-graph traversal and coverage-weighted chain sampling"],
        ["core/engine/",               "Deterministic engines: answer, trace and traps for each chain"],
        ["core/pipeline/",             "Pipeline stages: inputs, stem, gate, council, verifier, hints"],
        ["core/dedup.py",              "Tier 1 duplicate check on exact engine inputs"],
        ["core/blackboard.py",         "Per-question notebook every stage writes to"],
        ["core/coverage.py",           "Inverse-frequency counters that keep the question set diverse"],
        ["core/meta_tags.py",          "Six difficulty labels computed for each accepted question"],
        ["core/llm.py",                "Model-call helpers: retries on transient errors, JSON replies"],
        ["tools/build_graph.py",       "Concept book → knowledge graph, per subject"],
        ["tools/results.py",           "Review of results/: promote, pending, score, reject"],
    ], [0.30, 0.70], doc))
    s += [Sp(12)]

    # ── 2. Generation Loop ────────────────────────────────────────────────────
    s += [H("2. The Generation Loop"), HR()]
    s.append(B(
        "A run accepts at most one question. It tries up to <b>3 fresh ideas</b> (lineages) and "
        "<b>4 generate-and-check iterations</b> in total; within an idea the generator gets one "
        "refine pass against verifier feedback before a new idea is tried."
    ))
    s += [Sp(6)]

    s.append(mktbl([
        ["Step", "Component",                                   "What it does"],
        ["0",    "Pending recheck",
         "Questions parked by an earlier council failure are rechecked first (council only — the "
         "verifier already passed them): accepted, dropped, or parked again."],
        ["1",    "Graph traversal",
         "Breadth-first search over the subject's graph returns chains of two or more steps in the "
         "chapter, ranked by coverage weight; chains that start in the chapter top them up if needed. "
         "Each step's concept-book entry is chosen so steps join on the same compound where possible."],
        ["2",    "Concept reasoner (DeepSeek-V3)",
         "Picks the most promising of six offered chains: coherent, non-circular, with a decision or "
         "trap where difficulty comes from reasoning."],
        ["3",    "Generator (Gemini 3.7 Flash)",
         "Writes the question and a reference solution, applying each step to the actual product of "
         "the previous one. On a retry it fixes only what was flagged."],
        ["4",    "Verifier (Gemini 3 Flash, two tiers)",
         "Tier 1, no LLM: for numeric answers, fails a question whose inputs match an accepted question "
         "with a different answer. Tier 2: blind-solves with the candidate withheld, compares the answers, "
         "checks for structural flaws, rates difficulty. The verdict is assembled in code."],
        ["5",    "Council (Llama 3.3 70B, Mistral Large, Gemma 3 27B) + grader (GPT-4o)",
         "Three Mains-level solvers answer in parallel, blind and closed-book (only the chapter's "
         "concept-book entries). GPT-4o grades each answer against the construction steps. All three "
         "must answer; if one call fails the question is parked and the run stops."],
        ["6",    "Gate",
         "Verifier PASS, the answer key not flagged as wrong by two or more graders, and at most one "
         "of three council members solved it. Two or more solved → refine for reasoning difficulty."],
        ["7",    "Save",
         "The record is written atomically to outputs/generated_questions_[subject].json, then coverage, "
         "the duplicate-check store, results/ (with empty human-eval slots) and the attempt log."],
    ], [0.06, 0.26, 0.68], doc))
    s += [Sp(12)]

    # ── 3. Difficulty Signal ──────────────────────────────────────────────────
    s += [H("3. The Difficulty Signal"), HR()]
    s.append(B(
        "Difficulty is measured by how many of three Mains-level solvers, from different model "
        "families, can solve the question blind. Validity is the verifier's job; difficulty is the "
        "council's. The two are never combined into a single score."
    ))
    s += [Sp(4)]

    s.append(mktbl([
        ["Council result",           "Meaning",                                  "Action"],
        ["0 or 1 of 3 solved",       "Above the council's Mains-level ceiling",  "Accept (if the verifier passed)"],
        ["2 or 3 of 3 solved",       "Within Mains reach — too easy",             "Refine: add a decision, exception or constraint"],
        ["2+ graders flag the key",  "The reference answer itself is wrong",      "Refine the reference solution"],
        ["A member's call fails",    "No measurement — not the question's fault", "Park the question; stop the run (exit 3)"],
    ], [0.26, 0.37, 0.37], doc))
    s += [Sp(6)]
    s.append(B(
        "The yardstick comes from <b>calibration/anchor_calibration.py</b>: on 54 real JEE Advanced "
        "numeric questions (2021–2025), gpt-oss-120b solves 50% blind and qwen3-235b 37%, while "
        "llama-3.2-3b solves 6–7%."
    ))
    s += [Sp(12)]

    # ── 4. The Blackboard ─────────────────────────────────────────────────────
    s += [H("4. The Blackboard"), HR()]
    s.append(B(
        "The Blackboard is the shared working memory that makes refine-in-place possible. It keeps "
        "the full trace of every attempt so the concept reasoner and the generator always see what "
        "failed before."
    ))
    s += [Sp(4)]

    s.append(mktbl([
        ["Field recorded per attempt",             "Used by"],
        ["problem, solution",                      "Generator refine-in-place prompt"],
        ["operators_used",                         "Concept reasoner — avoids steps that caused failures"],
        ["verifier_verdict, verifier_feedback",    "Generator — fix only the flagged issue"],
        ["council_solved, council_size",           "Generator and concept reasoner — how far from the target difficulty"],
        ["difficulty_rating",                      "Attempt history in the saved record"],
    ], [0.42, 0.58], doc))
    s += [Sp(12)]

    # ── 5. Knowledge ──────────────────────────────────────────────────────────
    s += [H("5. Concept Books and Knowledge Graphs"), HR()]
    s.append(B(
        "Each subject has a concept book of transformations plus interpretive entries (fragile "
        "concepts, exceptions, distractors), and a knowledge graph built from it by "
        "<b>tools/build_graph.py</b>. All three graphs share one schema and one traversal."
    ))
    s += [Sp(4)]

    s.append(mktbl([
        ["Subject",    "Transformations", "Fragile / exceptions / distractors", "Graph nodes are",              "Graph size"],
        ["Organic",    "657",             "605 / 502 / 470",                    "functional-group classes",    "57 nodes · 199 edges"],
        ["Inorganic",  "904",             "123 / 134 / —",                      "chemical species",            "363 nodes · 415 edges"],
        ["Physical",   "348",             "116 / 70 / 81",                      "physical quantities",         "119 nodes · 147 edges"],
    ], [0.14, 0.17, 0.25, 0.22, 0.22], doc))
    s += [Sp(6)]
    for pt in [
        "An edge is one concept-book transformation — a reaction, or a formula step for physical. "
        "Entries that are facts rather than steps stay out of the graph.",
        "Inorganic edges take substrate and product from both sides of a reaction together, so the "
        "two always share an element; soluble salts are also linked to the ion they release.",
        "Organic graph edges are curated; organic and physical nodes are classes, so the generator "
        "carries the actual compound or quantity from one step to the next.",
    ]:
        s.append(BU(pt))
    s += [Sp(12)]

    # ── 6. Archetypes ─────────────────────────────────────────────────────────
    s += [H("6. Question Archetypes"), HR()]
    s.append(B(
        "Archetypes classify the kind of reasoning a question demands. Generation uses archetype I "
        "for every subject; the others organise the seed corpora and the meta-tag baselines."
    ))
    s += [Sp(4)]

    s.append(mktbl([
        ["Code", "Organic",                      "Inorganic",                                     "Physical"],
        ["I",    "Long Reaction Chains",         "Reaction & Transformation Chains",              "Multi-Formulae"],
        ["II",   "Counting / Enumeration",       "Property / Trend Ordering & Exception Reasoning", "Multi-Chapter Integration"],
        ["III",  "Deep Mechanistic Reasoning",   "Structure, Bonding & Electronic Configuration", "Graphical Interpretation"],
        ["IV",   "Comparative Ranking / GOC",    "Numerical / Computational",                     "Property / Trend Ordering"],
        ["V",    "—",                            "Qualitative Identification",                    "Conceptual / Postulate-Based"],
        ["VI",   "—",                            "Applied / Real-World Conceptual Reasoning",     "Applied / Real-World"],
    ], [0.08, 0.26, 0.38, 0.28], doc))
    s += [Sp(12)]

    # ── 7. Meta-tags ──────────────────────────────────────────────────────────
    s += [H("7. The Six Meta-tags (scored 1–5)"), HR()]
    s.append(B(
        "Every accepted question is labelled on six axes, each a z-score against real JEE Advanced "
        "questions of the same archetype, mapped to 1–5. They describe the question; they do not "
        "steer generation."
    ))
    s += [Sp(4)]

    s.append(mktbl([
        ["Dimension",               "Measured from"],
        ["Question length / scope", "Word count of the question"],
        ["Semantic obfuscation",    "Density of systematic-nomenclature tokens in the question"],
        ["Conceptual fragility",    "Share of students who miss full marks on comparable questions"],
        ["Number of exceptions",    "Exception and rejection cues in a council solver's working"],
        ["Model solution length",   "Length of a council solver's working"],
        ["Distractor plausibility", "Alternative paths explicitly ruled out in that working"],
    ], [0.32, 0.68], doc))
    s += [Sp(12)]

    # ── 8. Models ─────────────────────────────────────────────────────────────
    s += [H("8. Model Roster (OpenRouter)"), HR()]
    s.append(mktbl([
        ["Role",              "Model",                                    "Temperature"],
        ["Concept reasoner",  "deepseek/deepseek-chat-v3-0324",           "1.0"],
        ["Generator",         "google/gemini-2.5-flash",                  "0.7"],
        ["Verifier",          "google/gemini-3-flash-preview",            "0.0"],
        ["Council solver 1",  "meta-llama/llama-3.3-70b-instruct",        "0.0"],
        ["Council solver 2",  "mistralai/mistral-large-2407",             "0.0"],
        ["Council solver 3",  "google/gemma-3-27b-it",                    "0.0"],
        ["Grader",            "openai/gpt-4o",                            "0.0"],
    ], [0.26, 0.54, 0.20], doc))
    s += [Sp(6)]
    for pt in [
        "Calls retry transient failures (rate limits, 5xx, timeouts, dropped connections) with "
        "exponential backoff, and re-ask when a reply is empty or not valid JSON.",
        "A council call that still fails parks the question in outputs/pending_questions_[subject].json "
        "and stops the run; the batch driver stops too. The next run rechecks it first.",
    ]:
        s.append(BU(pt))
    s += [Sp(12)]

    # ── 9. Acceptance Logic ───────────────────────────────────────────────────
    s += [H("9. Acceptance Logic"), HR()]
    for line in [
        "if verifier['verdict'] == 'FAIL':           refine once, then try a new idea",
        "council = council_solve(question)           # all 3 must answer, else park + stop",
        "if council['n_reference_flags'] >= 2:      refine the reference solution",
        "elif council['n_solved'] >= 2:             refine: add reasoning difficulty",
        "else:                                       save_accepted(question)  # write record first",
    ]:
        s.append(Code(line))
    s += [Sp(12)]

    # ── Footer ────────────────────────────────────────────────────────────────
    s.append(HR())
    s.append(Paragraph("Prahlada · JEE Advanced chemistry question generation · October 2026", CAPTION))

    return s


def main():
    doc = SimpleDocTemplate(
        OUT, pagesize=A4,
        leftMargin=2*cm, rightMargin=2*cm,
        topMargin=2*cm,  bottomMargin=2.2*cm,
        title="JEE Advanced Chemistry — Question Generation Pipeline Architecture",
        author="Prahlada",
    )
    doc.build(build(doc))
    print(f"PDF written → {OUT}")

if __name__ == "__main__":
    main()
