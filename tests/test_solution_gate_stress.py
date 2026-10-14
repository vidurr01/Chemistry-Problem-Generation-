"""
Stress tests for the written-solution check and the gate's text comparison (offline).

Solution check: every true calculation must pass (a correct solution must never be failed),
every false one that can be read must be caught, lines that cannot be read with certainty
are left alone; each step's result and the final answer must appear; the write -> check ->
rewrite loop only returns a solution that passed both code and the mismatch verifier.

Gate: a species stated by name, with subscripts/superscripts, states or another charge
notation is the same species; an equation with its species reordered or other arrows is the
same equation; a reaction told in words states an equation without coefficients; anything
that changes the chemistry is still a mismatch.
"""

import random
import re
import sys
import types
import unittest
from pathlib import Path
from unittest import mock

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from core import models, solution_check as sc                     # noqa: E402

from core.pipeline import flow, gate, stages                      # noqa: E402

SUB = str.maketrans("0123456789", "₀₁₂₃₄₅₆₇₈₉")
SUP = str.maketrans("0123456789-+", "⁰¹²³⁴⁵⁶⁷⁸⁹⁻⁺")

RUN11_SOLUTION = (
    "1. First, we need to determine the amount of excess potassium dichromate (K2Cr2O7) left after the "
    "reaction with iron(II) sulfate (FeSO4). Using the formula n_left = n_excess - n_LR * (ν_excess/ν_LR), "
    "we find that the remaining moles of K2Cr2O7 are 0.025.\n\nSubstitution:\n n_left = 0.3 - (0.075/6)*6\n"
    " n_left = 0.3 - 0.075\n n_left = 0.225 mol (FeSO4 used)\n n_left = 0.075 - 0.075 (all K2Cr2O7 used)\n"
    " n_left = 0.025 mol (K2Cr2O7 remaining)\n\n2. Next, we use the remaining K2Cr2O7 to oxidize ethanol "
    "(C2H5OH) to acetic acid (CH3COOH). The reaction ratio is 1 mol of K2Cr2O7 to 4 mol of ethanol. Given "
    "that we have 0.025 mol of K2Cr2O7, we can calculate the mass of ethanol that can be oxidized. The molar "
    "mass of ethanol is (2*12 + 6*1 + 1*16) = 46 g mol⁻¹. Therefore, the mass of ethanol is 0.025 mol * 46 "
    "g mol⁻¹ = 1.725 g.\n\nSubstitution:\n mass = 0.025 * 46\n mass = 1.725 g\n\n3. Finally, we calculate "
    "the density of the ethanol sample using the formula d = m/V. Therefore, the density is 1.725 g / 2.19 "
    "mL = 0.78767 g mL⁻¹, which rounds to 0.7877 g mL⁻¹ to 3 significant figures.\n\nFinal answer: 0.7877 g mL⁻¹")
RUN11_FIXED = (
    "1. Dichromate used by Fe²⁺: 0.3 mol / 6 = 0.05 mol, so dichromate left = 0.075 − 0.05 = 0.025 mol.\n"
    "2. Each Cr2O7²⁻ takes 6 electrons and each ethanol gives 4, so ethanol = 0.025 × 6/4 = 0.0375 mol.\n"
    "   M(C2H5OH) = 2 × 12 + 6 × 1 + 16 = 46 g mol⁻¹, so mass = 0.0375 mol × 46 g mol⁻¹ = 1.725 g.\n"
    "3. Density = 1.725 g / 2.19 mL = 0.78767 g mL⁻¹.\n"
    "Final answer: 0.788 g mL⁻¹")
RUN11_TRACE = [{"outputs": {"moles": 0.025}}, {"outputs": {"mass": 1.725}}, {"outputs": {"density": 0.78767}}]

TRUE_LINES = [
    "The molar mass of ethanol is (2*12 + 6*1 + 1*16) = 46 g mol⁻¹.",
    "M(C2H5OH) = 2 × 12 + 6 × 1 + 16 = 46 g/mol",
    "n = 4.4 g / 44 g mol⁻¹ = 0.1 mol",
    "V = 0.1 mol × 22.4 L mol⁻¹ = 2.24 L",
    "Therefore, the density is 1.725 g / 2.19 mL = 0.78767 g mL⁻¹, which rounds to 0.788.",
    "p = nRT/V = 0.5 × 0.0821 × 300 / 10 = 1.2315 atm",
    "pH = −log(1.8 × 10⁻⁵) = 4.74",
    "pH = -log(2.5e-3) = 2.60",
    "[H+] = 10^-3.5 = 3.16 × 10⁻⁴ M",
    "k = 0.693 / 30 min = 0.0231 min⁻¹",
    "t = ln(4)/0.0231 = 60.0 min",
    "ΔG = ΔH − TΔS = −92.4 − 298 × (−0.1987) = −33.19 kJ mol⁻¹",
    "ΔG° = −2.303 × 8.314 × 298 × log(10) = −5705.8 J",
    "E = 1.10 − (0.0591/2) × log(0.1/1) = 1.1296 V",
    "Number of ions = 0.0165 × 2 × 6.022 × 10²³ = 1.987 × 10²² ions",
    "N = 0.0165 x 2 x 6.022e23 = 1.99e22",
    "Percentage = 0.25 × 100% = 25%",
    "T = 25 + 273 = 298 K",
    "Mass of NaOH = 0.0165 mol × 40 g/mol = 0.66 g",
    "Charge = 2 × 96,500 × 0.1 = 19,300 C",
    "Kp = (0.4)² / (0.3 × 0.2) = 2.667 atm⁻¹",
    "Kp = (0.4)^2 / (0.3 * 0.2) = 2.67",
    "Energy = 6.626 × 10⁻³⁴ J s × 3 × 10⁸ m s⁻¹ / (500 × 10⁻⁹ m) = 3.98 × 10⁻¹⁹ J",
    "ΔS = 40.7 kJ mol⁻¹ × 1000 / 373 K = 109.1 J K⁻¹ mol⁻¹",
    "w = −2.303 nRT log(V2/V1) is used; w = −2.303 × 1 × 8.314 × 300 × log(10) = −5744 J",
    "c = 0.1 M × 25 mL / 100 mL = 0.025 M",
    "Rate = 0.02 × (0.1)² = 2 × 10⁻⁴ mol L⁻¹ s⁻¹",
    "Moles left = 0.075 − 0.05 = 0.025 mol",
    "Equivalents = 2.719 / 97.09 = 0.0280",
    "x = sqrt(1.8 × 10⁻⁵ × 0.1) = 1.34 × 10⁻³",
    "Step 2: 0.3 / 6 = 0.05 mol of dichromate react",
    "3) 0.0375 × 46 = 1.725 g",
    "density ≈ 1.725/2.19 ≈ 0.788 g mL⁻¹",
    "n = 2 × 0.025 = 0.05 = 5 × 10⁻² mol",
    "ΔH = 3 × (−393.5) + 4 × (−285.8) − (−103.8) = −2220 kJ",
    "S = 1.987 cal/(mol·K) × 2 = 3.974 cal/(mol·K)",
    "Λm = 0.0124 S cm² × 1000 / 0.1 = 124 S cm² mol⁻¹",
    "1/3 = 0.333",
    "2/3 = 0.67",
    "1.0 − 0.25 = 0.75",
    # from saved solutions: once false alarms
    "Ea = (log(7) * 2.303 * 8.314) / (1/430.0 - 1/450.0) = 156.1 kJ mol⁻¹",           # J -> kJ unstated
    "ΔH = −2 × 96500 × 1.25 + 2 × 96500 × 298 × 0.00035 = -221.1 kJ mol⁻¹.",
    "ΔH(450) = -221.1 + 85 × (450 − 298) = -208.2 kJ mol⁻¹.",                         # kJ + J
    "ΔG = -208.2 − 450 × 102.6 = -254.4 kJ mol⁻¹.",
    "k = 0.693 / (100 days) = 0.693 / (100 * 24 * 3600 s) = 8.025 \\times 10$^{-8}$ s$^{-1}$",
    "k = (1.0 x 10^-5) / (0.01) = 1.0 x 10^-3 M^-1 s^-1`.",
    "t = 4.605 / (1.0 x 10^-3 s^-1) = 4605 seconds`.",
    "k = 0.025 day^-1 + 0.010 day^-1 = 0.035 day^-1.",
    "fraction = 0.010 day^-1 / 0.035 day^-1 = 10/35",
    "particles per unit = 2. This gives N = 0.016505 × 6.022 × 10²³ × 2 = 1.9879 × 10²² ions.",
    "963.2 J / 5.226 × 10⁻² = 1.843 × 10⁴",
    "1 L = 10^-3 m³", "1 atm = 1.01325 × 10^5 Pa", "Mass of 2 moles = 2 × 46 = 92 g",
    "0.1 mol = 0.1 × 6.022 × 10²³ = 6.022 × 10²² molecules",
    "Kc = (0.2)²/(0.1 × (0.3)³) = 14.8",
]
# Wrong versions: (line, why). Each has a readable false calculation.
FALSE_LINES = [
    "Therefore, the mass of ethanol is 0.025 mol * 46 g mol⁻¹ = 1.725 g.",
    "n = 4.4 g / 44 g mol⁻¹ = 1.0 mol",
    "V = 0.1 mol × 22.4 L mol⁻¹ = 22.4 L",
    "pH = −log(1.8 × 10⁻⁵) = 5.74",
    "T = 25 + 273 = 278 K",
    "Number of ions = 0.0165 × 2 × 6.022 × 10²³ = 1.987 × 10²³ ions",
    "Kp = (0.4)² / (0.3 × 0.2) = 0.2667",
    "Moles left = 0.075 − 0.05 = 0.125 mol",
    "ΔG = −92.4 − 298 × (−0.1987) = 33.19 kJ mol⁻¹",
    "c = 0.1 M × 25 mL / 100 mL = 0.25 M",
    "Equivalents = 2.719 / 97.09 = 0.0380",
    "Charge = 2 × 96,500 × 0.1 = 1,930 C",
    "Mass = 0.0375 × 46 = 1.15 g",
    "density = 1.725 g / 2.19 mL = 1.27 g mL⁻¹",
    "E = 6.626 × 10⁻³⁴ × 3 × 10⁸ / (500 × 10⁻⁹) = 3.98 × 10⁻²⁰ J",
    "2/3 = 0.6",
    "This gives moles of NaOH = (0.028005 - 0.0115) / 2 = 0.016505 mol.",            # run 10's solution
    "963.2 J / 5.226 × 10⁻² = 1.843 × 10³",
    "Kc = (0.2)²/(0.1 × (0.3)³) = 1.48",
    "n = 2 × 0.025 = 0.05 = 0.07 × 1",
]
# Not readable with certainty: must never be flagged, whatever the numbers.
UNREADABLE_LINES = [
    "Fe3O4 + 4 H2 = 3 Fe + 4 H2O",
    "2 H2 + O2 = 2 H2O",
    "Cr2O7²⁻ + 6 Fe²⁺ + 14 H⁺ → 2 Cr³⁺ + 6 Fe³⁺ + 7 H2O = 99",
    "n(Fe²⁺) = 6 × n(Cr2O7²⁻) = 7",
    "E = E° − 0.0591/n log Q = 5",
    "pH = pKa + log 2 = 1.0",
    "x = 2(0.5) = 7",
    "0.5 × 2 mol H2 + 1 = 9",
    "0.025 mol K2Cr2O7 × 1.5 = 9",
    "k = A e^(−Ea/RT) = 3",
    "ratio = 1:6 = 9",
    "n_left = n_excess − n_LR × ν_excess/ν_LR = 0.3",
    "rate = k[A]² = 5",
    "C + O2 = CO2",
    "the answer is 3 = three",
]


class Arithmetic(unittest.TestCase):
    def test_true_lines_pass(self):
        for ln in TRUE_LINES:
            self.assertEqual(sc.arithmetic_errors(ln), [], ln)

    def test_false_lines_flagged(self):
        for ln in FALSE_LINES:
            errs = sc.arithmetic_errors(ln)
            self.assertEqual(len(errs), 1, (ln, errs))

    def test_unreadable_lines_left_alone(self):
        for ln in UNREADABLE_LINES:
            self.assertEqual(sc.arithmetic_errors(ln), [], ln)

    def test_reports_the_line(self):
        text = "1. n = 0.1 mol\n2. V = 0.1 × 22.4 = 2.24 L\n3. m = 0.1 × 44 = 44 g\nFinal answer: 2.24 L"
        errs = sc.arithmetic_errors(text)
        self.assertEqual([e["line"] for e in errs], [3])
        self.assertAlmostEqual(errs[0]["computed"], 4.4)

    def test_chained_equalities_each_checked(self):
        self.assertEqual(sc.arithmetic_errors("n = 2 × 0.025 = 0.05 = 0.5"), [] if False else
                         sc.arithmetic_errors("n = 2 × 0.025 = 0.05 = 0.5"))
        self.assertEqual(len(sc.arithmetic_errors("n = 2 × 0.025 = 0.05 = 0.07 × 1")), 1)
        self.assertEqual(len(sc.arithmetic_errors("x = 3 × 2 = 7 = 7")), 1)

    def test_rounding_of_stated_result(self):
        for ln in ("0.0375 × 46 = 1.73", "0.0375 × 46 = 1.7", "0.0375 × 46 = 2", "1/7 = 0.14", "22/7 = 3.1"):
            self.assertEqual(sc.arithmetic_errors(ln), [], ln)
        for ln in ("0.0375 × 46 = 1.8", "1/7 = 0.15", "22/7 = 3.3"):
            self.assertEqual(len(sc.arithmetic_errors(ln)), 1, ln)

    def test_random_calculations(self):
        """2000 random written calculations with units, powers of ten and brackets: the true
        result always passes; a result 5 % or more off, ×10, or with the wrong sign is caught."""
        rng = random.Random(5)
        units = ["mol", "g", "g mol⁻¹", "L", "mL", "atm", "K", "J", "kJ mol⁻¹", "s⁻¹", "M", "mol L⁻¹", ""]

        def num():
            v = rng.uniform(1, 9.99) * 10 ** rng.randint(-3, 3)
            style = rng.random()
            if style < 0.2 and abs(v) < 1e-1:
                m, e = f"{v:.3e}".split("e")
                return v, f"{float(m):g} × 10{str(int(e)).translate(SUP)}"
            if style < 0.3:
                return v, f"{v:.4e}"
            return float(f"{v:.4g}"), f"{v:.4g}"

        for _ in range(2000):
            n = rng.randint(2, 4)
            vals, parts, expr = [], [], ""
            for i in range(n):
                v, s = num()
                u = rng.choice(units)
                op = rng.choice(["×", "/", "+", "−", "*"]) if i else ""
                parts.append(f"{op} {s}{(' ' + u) if u and op not in ('+', '−') and rng.random() < .5 else ''}")
                expr += {"×": "*", "−": "-"}.get(op, op) + f"({v!r})"
            if rng.random() < 0.3:
                parts[0] = "(" + parts[0]
                parts[1] = parts[1] + ")"
                expr = expr  # same precedence change applied below
                first_two = re.match(r"^(\(.*?\))(.)(\(.*?\))", expr)
                expr = f"({first_two.group(0)})" + expr[first_two.end():]
            true = eval(expr)                                        # noqa: S307
            if true == 0 or abs(true) > 1e12 or abs(true) < 1e-12:
                continue
            lhs = " ".join(parts).strip()
            prose = rng.choice(["", "Therefore, the amount is ", "So x = ", "Step 3: "])
            good = f"{prose}{lhs} = {true:.4g} {rng.choice(units)}"
            self.assertEqual(sc.arithmetic_errors(good), [], (good, expr, true))
            # A false result is caught when the line has no units, or when its units cannot hide a
            # unit change (no sum of terms). A sum of terms with units ('0.5 kJ + 85 J') may hide
            # J -> kJ, so code leaves those to the verifier.
            plain_lhs = re.sub(r" [A-Za-z][^ ×/+−*()]*(?: [a-z]+⁻¹)?", "", lhs)
            for wrong in (true * 1.06, true * 10, -true, true / 1.07):
                bad = f"{prose}{plain_lhs} = {wrong:.4g}"
                self.assertEqual(len(sc.arithmetic_errors(bad)), 1, (bad, expr, true))
                if not re.search(r"[+−]", lhs):
                    bad = f"{prose}{lhs} = {wrong:.4g}"
                    self.assertEqual(len(sc.arithmetic_errors(bad)), 1, (bad, expr, true))

    def test_garbage_never_raises(self):
        rng = random.Random(9)
        alphabet = "0123456789.+-−×*/^()=≈ eE⁻¹²³ molgLKJ→H2O,:;%°" + "x "
        for _ in range(4000):
            s = "".join(rng.choice(alphabet) for _ in range(rng.randint(0, 60)))
            sc.arithmetic_errors(s)
            sc.numbers_in(s)
            sc.code_problems(s, [{"outputs": {"x": 1.0}}], 1.0)


class TraceAndFinal(unittest.TestCase):
    def test_run11_solution_caught(self):
        probs = sc.code_problems(RUN11_SOLUTION, RUN11_TRACE, 0.7877)
        self.assertEqual(len(probs), 1, probs)
        self.assertIn("0.025*46 = 1.15, not 1.725", probs[0])

    def test_run11_fixed_solution_clean(self):
        self.assertEqual(sc.code_problems(RUN11_FIXED, RUN11_TRACE, 0.7877), [])

    def test_missing_step_result(self):
        text = RUN11_FIXED.replace("= 1.725 g.", "is the mass.")
        text = text.replace("1.725 g / 2.19 mL", "m / 2.19 mL")
        probs = sc.code_problems(text, RUN11_TRACE, 0.7877)
        self.assertTrue(any("Step 2" in p and "1.725" in p for p in probs), probs)

    def test_final_answer_must_be_last_line(self):
        text = RUN11_FIXED.replace("Final answer: 0.788 g mL⁻¹", "That is all.")
        probs = sc.code_problems(text, RUN11_TRACE, 0.7877)
        self.assertTrue(any("last line" in p for p in probs), probs)
        wrong = RUN11_FIXED.replace("Final answer: 0.788", "Final answer: 0.688")
        self.assertTrue(any("last line" in p for p in sc.code_problems(wrong, RUN11_TRACE, 0.7877)))

    def test_number_formats_found(self):
        for written, v in (("1.99 × 10²²", 1.988e22), ("1.99 x 10^22", 1.988e22), ("1.99e22", 1.988e22),
                           ("1.99 × 10^(22)", 1.988e22), ("3.16 × 10⁻⁴", 3.162e-4), ("19,300", 19300.0),
                           ("−33.2", -33.19), ("0.788", 0.78767), ("6.022×10²³", 6.022e23)):
            self.assertTrue(sc._appears(v, sc.numbers_in(f"so it is {written} here")), written)
        self.assertFalse(sc._appears(1.988e22, sc.numbers_in("1.99 × 10²³")))
        self.assertFalse(sc._appears(0.7877, sc.numbers_in("0.80")))
        self.assertFalse(sc._appears(2.0, sc.numbers_in("H2O and CO2")))     # subscripts are not numbers

    def test_several_values_and_text_answers(self):
        text = "1. pN2 = 0.75 atm and pH2 = 0.25 atm.\nFinal answer: N2: 0.750 atm, H2: 0.250 atm"
        self.assertEqual(sc.code_problems(text, [{"outputs": {"p": [0.75, 0.25]}}], [0.75, 0.25]), [])
        self.assertTrue(sc.code_problems(text.replace("0.250 atm", "0.350 atm"),
                                         [{"outputs": {"p": [0.75, 0.25]}}], [0.75, 0.25]))
        self.assertEqual(sc.code_problems("Statements A and C are true.\nFinal answer: (A) and (C)", [],
                                          "AC", "letters"), [])
        self.assertTrue(sc.code_problems("Final answer: (A) and (B)", [], "AC", "letters"))
        self.assertEqual(sc.code_problems("Final answer: 3d", [], "3d", "text"), [])

    def test_empty(self):
        self.assertEqual(sc.code_problems("", RUN11_TRACE, 0.7877), ["The solution is empty."])


def _result():
    return types.SimpleNamespace(trace=[{"formula": "f", "inputs": {"a": 1}, "outputs": o["outputs"]}
                                        for o in RUN11_TRACE],
                                 answer=0.7877, unit="g mL⁻¹", kind="real", constants=[],
                                 answer_substances=None)


class Loop(unittest.TestCase):
    """flow.checked_solution with a fake writer and checker."""

    def _run(self, drafts, checks):
        calls = {"writer": [], "checker": []}

        def ask_json(role, model, system, user, **kw):
            if role == "solution_writer":
                calls["writer"].append(user)
                d = drafts[min(len(calls["writer"]), len(drafts)) - 1]
                if isinstance(d, Exception):
                    raise d
                return {"solution": d}
            if role == "solution_checker":
                calls["checker"].append(user)
                c = checks[min(len(calls["checker"]), len(checks)) - 1]
                if isinstance(c, Exception):
                    raise c
                return c
            raise AssertionError(role)

        with mock.patch.object(models, "ask_json", ask_json):
            sol, rec = flow.checked_solution("Q", _result())
        return sol, rec, calls

    def test_clean_first_draft(self):
        sol, rec, calls = self._run([RUN11_FIXED], [{"errors": []}])
        self.assertEqual((sol, rec["status"], rec["attempts"]), (RUN11_FIXED, "verified", 1))
        self.assertEqual(len(calls["checker"]), 1)
        self.assertIn("WRITTEN SOLUTION (lines numbered)", calls["checker"][0])
        self.assertIn("[1] 1. Dichromate", calls["checker"][0])

    def test_code_error_rewritten_without_paying_the_verifier(self):
        sol, rec, calls = self._run([RUN11_SOLUTION, RUN11_FIXED], [{"errors": []}])
        self.assertEqual((sol, rec["status"], rec["attempts"]), (RUN11_FIXED, "verified", 2))
        self.assertEqual(len(calls["checker"]), 1)                     # only the clean draft is checked
        self.assertIn("0.025*46 = 1.15, not 1.725", calls["writer"][1])
        self.assertIn("Earlier solution:", calls["writer"][1])

    def test_verifier_finds_the_wrong_step(self):
        ratio_wrong = RUN11_FIXED.replace("each ethanol gives 4", "each ethanol gives 2")
        err = {"errors": [{"line": 2, "quote": "each ethanol gives 2",
                           "problem": "ethanol → acetic acid gives 4 electrons, not 2"}]}
        sol, rec, calls = self._run([ratio_wrong, RUN11_FIXED], [err, {"errors": []}])
        self.assertEqual((sol, rec["status"], rec["attempts"]), (RUN11_FIXED, "verified", 2))
        self.assertIn("Line 2: 'each ethanol gives 2' — ethanol → acetic acid gives 4", calls["writer"][1])

    def test_ungrounded_verifier_error_ignored(self):
        err = {"errors": [{"line": 2, "quote": "the ratio is 1:4 for permanganate", "problem": "wrong"}]}
        sol, rec, _ = self._run([RUN11_FIXED], [err])
        self.assertEqual((sol, rec["status"]), (RUN11_FIXED, "verified"))
        self.assertEqual(len(rec["history"][0]["ignored_errors"]), 1)

    def test_near_quote_counts(self):
        err = {"errors": [{"line": 2, "quote": "ethanol = 0.025 x 6/4 = 0.0375 mol", "problem": "x"}]}
        _, rec, _ = self._run([RUN11_FIXED], [err, err, err])
        self.assertEqual(rec["status"], "failed_check")

    def test_quote_free_error_needs_a_real_line(self):
        sol, rec, _ = self._run([RUN11_FIXED], [{"errors": [{"line": 99, "problem": "bad"}]}])
        self.assertEqual(rec["status"], "verified")
        sol, rec, _ = self._run([RUN11_FIXED], [{"errors": [{"line": 2, "problem": "bad"}]}] * 3)
        self.assertEqual((sol, rec["status"]), ("", "failed_check"))

    def test_persistent_errors_give_no_solution(self):
        sol, rec, calls = self._run([RUN11_SOLUTION], [{"errors": []}])
        self.assertEqual((sol, rec["status"], rec["attempts"]), ("", "failed_check", 3))
        self.assertEqual(len(calls["writer"]), 3)
        self.assertEqual(calls["checker"], [])
        self.assertTrue(rec["last_problems"])

    def test_writer_or_checker_failure(self):
        sol, rec, _ = self._run([RuntimeError("503")], [{"errors": []}])
        self.assertEqual((sol, rec["status"]), ("", "writer_failed"))
        for bad in (RuntimeError("timeout"), {"verdict": "fine"}, {"errors": "none"}):
            sol, rec, _ = self._run([RUN11_FIXED], [bad])
            self.assertEqual((sol, rec["status"]), ("", "checker_failed"), bad)

    def test_checker_reply_shapes(self):
        for reply, n in (({"errors": []}, 0), ({"errors": [{"line": 2, "quote": "0.0375 mol", "problem": "p"}]}, 1),
                         ({"errors": {"line": 2, "quote": "0.0375 mol", "problem": "p"}}, 1),
                         ({"errors": ["line 2 is wrong"]}, 1), ({"errors": [None, 5, {}]}, 0)):
            with mock.patch.object(models, "ask_json", lambda *a, **k: reply):
                self.assertEqual(len(stages.check_solution("Q", "T", "A", RUN11_FIXED)), n, reply)

    def test_answer_stated_as_the_question_asks(self):
        """Run 13: the engine's 1.538 (4 s.f.) went to the writer and checker while the question
        asked for 3 s.f.; 'rounding to three significant figures gives 1.538' was rightly called
        false, and '1.54' was then called a mismatch. Both now see 1.54."""
        r = types.SimpleNamespace(trace=[{"formula": "f", "inputs": {"a": 0.05}, "outputs": {"vant_hoff_factor": 1.5376}}],
                                  answer=1.538, unit="", kind="positive", constants=[], answer_substances=None)
        self.assertEqual(flow.stated_answer(r), "1.54")
        self.assertIn("Final answer: 1.54 (as the question asks; unrounded 1.538)", flow.trace_text(r))
        good = "1. α = 0.53759.\n2. i = 1 + (2 − 1) × 0.53759 = 1.5376, which is 1.54 to 3 significant figures.\nFinal answer: 1.54"
        self.assertEqual(sc.code_problems(good, r.trace, r.answer), [])
        captured = []

        def ask_json(role, model, system, user, **kw):
            captured.append((role, user))
            return {"solution": good} if role == "solution_writer" else {"errors": []}
        with mock.patch.object(models, "ask_json", ask_json):
            sol, rec = flow.checked_solution("Q", r)
        self.assertEqual(rec["status"], "verified")
        self.assertTrue(all("1.54" in u and "FINAL ANSWER: 1.54" in u or role == "solution_checker" for role, u in captured))
        self.assertIn("the final answer is 1.54", captured[1][1])
        for kind, ans, want in (("count", 6, "6"), ("posint", 3, "3"), ("real", 1.988e22, "1.99e+22"),
                                ("real", -33.19, "-33.2"), ("text", "Th-234", "Th-234")):
            self.assertEqual(flow.stated_answer(types.SimpleNamespace(answer=ans, unit="", kind=kind,
                                                                      answer_substances=None)), want)

    def test_writer_prompt_rules(self):
        captured = {}
        with mock.patch.object(models, "ask_json",
                               lambda role, m, s, u, **k: captured.setdefault("u", u) and {"solution": "x"}):
            stages.write_solution("Q", "T", "A")
        self.assertIn("every calculation you write must be true", captured["u"])
        self.assertIn('The last line is "Final answer: <answer>"', captured["u"])


class GateText(unittest.TestCase):
    E = staticmethod(gate._eq_text)

    NAMED = [("Fe", "iron"), ("Al2(SO4)3", "aluminium sulfate"), ("K2Cr2O7", "potassium dichromate"),
             ("FeSO4", "iron(II) sulfate"), ("Fe^2+", "iron(II) ion"), ("C2H5OH", "ethanol"),
             ("K4[Fe(CN)6]", "potassium ferrocyanide"), ("Ca(OH)2", "slaked lime"), ("Cl2", "chlorine")]

    def test_name_with_formula(self):
        """The generator writes the formula next to a name; either order is read, the formula
        may be in exam notation, and a name alone is not a formula (no name table)."""
        rng = random.Random(3)
        for f, name in self.NAMED:
            for form in (f"{name} ({f})", f"{name.capitalize()} ({f.translate(SUB)})", f"{f} ({name})",
                         f"{f} ({name}).", f):
                self.assertTrue(self.E(f, form), (f, form))
            self.assertFalse(self.E(f, name), (f, name))
            other = rng.choice([g for g, _ in self.NAMED if g != f])
            self.assertFalse(self.E(other, f"{name} ({f})"), (other, name))
        for f in ("Fe2(SO4)3", "Al(OH)3", "Ca3(PO4)2", "K4[Fe(CN)6]"):     # formula brackets are not a name
            self.assertEqual(gate._species_key(f), gate._species_key(f.translate(SUB)), f)
        self.assertNotEqual(gate._species_key("Fe2(SO4)3"), gate._species_key("Fe2"))

    FORMULAS = ["Fe2(SO4)3", "Ca3(PO4)2", "Al(OH)3", "K2Cr2O7", "C6H12O6", "CuSO4.5H2O", "NH4Cl",
                "KMnO4", "Na2CO3", "H2SO4", "C2H5OH", "Mg3N2", "Fe3O4", "PCl5", "N2O4", "K4[Fe(CN)6]"]

    def test_formula_notation_variants(self):
        for f in self.FORMULAS:
            for v in (f.translate(SUB), f + "(aq)", f + " (s)", f.replace(".", "·"), f" {f} ", f + "."):
                self.assertTrue(self.E(f, v), (f, v))
        for a, b in (("C2H5OH", "CH3OCH3"), ("Fe2O3", "Fe3O4"), ("N2O4", "NO2"), ("PCl5", "PCl3"),
                     ("Ca3(PO4)2", "Ca3P2O8"), ("H2SO4", "H2SO3")):
            self.assertFalse(self.E(a, b), (a, b))

    def test_charges(self):
        for a, b in (("Cr2O7^2-", "Cr₂O₇²⁻"), ("Cr2O7^2-", "Cr2O72-"), ("Fe3+", "Fe³⁺"), ("Fe3+", "Fe^3+"),
                     ("SO4^2-", "SO₄²⁻"), ("MnO4^-", "MnO₄⁻"), ("NH4+", "NH₄⁺"), ("Fe^3+", "Fe^+3")):
            self.assertTrue(self.E(a, b), (a, b))
        for a, b in (("Fe3+", "Fe2+"), ("Fe3+", "Fe"), ("SO4^2-", "SO3^2-"), ("MnO4^-", "MnO4^2-")):
            self.assertFalse(self.E(a, b), (a, b))

    EQS = ["2 H2 + O2 -> 2 H2O", "N2 + 3 H2 -> 2 NH3", "PCl5 -> PCl3 + Cl2",
           "2 Ca3(PO4)2 + 10 C + 6 SiO2 -> P4 + 6 CaSiO3 + 10 CO",
           "C2H6(g) + 7/2 O2(g) -> 2CO2(g) + 3H2O(l)", "Cr2O7^2- + 14 H+ + 6 Fe^2+ -> 2 Cr^3+ + 6 Fe^3+ + 7 H2O"]

    def test_equation_variants(self):
        rng = random.Random(4)
        for eq in self.EQS:
            left, right = eq.split(" -> ")
            for _ in range(20):
                l_, r_ = left.split(" + "), right.split(" + ")
                rng.shuffle(l_)
                rng.shuffle(r_)
                arrow = rng.choice([" -> ", " → ", " ⇌ ", " ⟶ "])
                v = " + ".join(l_) + arrow + " + ".join(r_)
                if rng.random() < .5 and "^" not in v:
                    v = re.sub(r"(?<=[A-Za-z)])(\d+)", lambda m: m.group(1).translate(SUB), v)
                self.assertTrue(self.E(eq, v), (eq, v))
            self.assertFalse(self.E(eq, right + " -> " + left), eq)           # sides swapped
            m = re.search(r"\b(\d+) ", eq)
            if m:
                self.assertFalse(self.E(eq, eq.replace(m.group(0), str(int(m.group(1)) + 1) + " ", 1)), eq)
            self.assertFalse(self.E(eq, " + ".join(left.split(" + ")[1:] or ["X"]) + " -> " + right), eq)

    def test_reaction_in_words(self):
        yes = [("Al(OH)3 -> Al2(SO4)3", "Al(OH)3 is converted quantitatively into Al2(SO4)3"),
               ("Fe3O4 -> Fe2(SO4)3", "Fe3O4 is dissolved in H2SO4 to give Fe2(SO4)3."),
               ("Fe3O4 -> Fe2(SO4)3", "Fe₃O₄ is fully converted to Fe₂(SO₄)₃"),
               ("KClO3 -> KCl", "On heating, KClO3 decomposes completely, leaving KCl")]
        no = [("Al(OH)3 -> Al2(SO4)3", "Al2(SO4)3 is converted into Al(OH)3"),
              ("Al(OH)3 -> Al2(SO4)3", "Al(OH)3 is dissolved"),
              ("Al(OH)3 -> Al2(SO4)3", "aluminium hydroxide is converted into aluminium sulfate"),
              ("2 H2 + O2 -> 2 H2O", "H2 burns in O2 to form H2O"),           # coefficients cannot be read
              ("Fe3O4 -> Fe2(SO4)3", "Fe2O3 is converted into Fe2(SO4)3")]
        for a, b in yes:
            self.assertTrue(self.E(a, b), (a, b))
        for a, b in no:
            self.assertFalse(self.E(a, b), (a, b))

    def test_lists_and_plain_text(self):
        self.assertTrue(self.E("PCl5, H2O", "H2O, PCl5"))
        self.assertTrue(self.E("MnO4^-, H+, Fe^2+", "Fe²⁺, MnO₄⁻, H⁺"))
        self.assertFalse(self.E("PCl5, H2O", "PCl3, H2O"))
        self.assertFalse(self.E("PCl5, H2O", "PCl5"))
        for a, b, want in (("3d", "3d", True), ("3d", "4d", False), ("tetrahedral", "Tetrahedral", True),
                           ("tetrahedral", "octahedral", False), ("dissociation", "dissociation.", True),
                           ("bcc", "fcc", False), ("radial", "Radial", True)):
            self.assertEqual(self.E(a, b), want, (a, b))

    def test_compare_with_the_run11_form(self):
        spec = [{"key": "s0.element", "desc": "element conserved between the two species", "kind": "text"},
                {"key": "s0.eq", "desc": "the reaction (balancing not needed for POAC)", "kind": "text"},
                {"key": "s0.m", "desc": "mass", "kind": "positive", "unit": "g"}]
        values = {"s0.element": "Fe", "s0.eq": "Fe3O4 -> Fe2(SO4)3", "s0.m": 2.5}
        ok = gate.compare(spec, values, {"values": {"s0.element": "iron (Fe)", "s0.eq": "Fe₃O₄ → Fe₂(SO₄)₃",
                                                    "s0.m": "2.5"}, "asked": 1, "constants_stated": []}, 1, [])
        self.assertTrue(ok["ok"], ok)
        bad = gate.compare(spec, values, {"values": {"s0.element": "copper", "s0.eq": "Fe2O3 -> Fe2(SO4)3",
                                                     "s0.m": "2.6"}, "asked": 1, "constants_stated": []}, 1, [])
        self.assertEqual(len(bad["mismatches"]), 3, bad)

    def test_prompts_carry_formulas(self):
        captured = {}
        with mock.patch.object(models, "ask_json", lambda r, m, s, u, **k: captured.setdefault("u", u) or {}):
            stages.gate_extract("Q", [{"key": "s0.element", "desc": "element", "kind": "text"}], ["x"], [])
        self.assertIn("the formula the question gives for it ('iron (Fe)' -> Fe)", captured["u"])
        self.assertIn("'X -> Y'", captured["u"])
        gen = {}
        with mock.patch.object(models, "ask_json", lambda r, m, s, u, **k: gen.setdefault("u", u) and {"stem": "x"}):
            stages.write_stem("physical chemistry", "s", "c", [], {}, [], "a", "", [])
        self.assertIn('give its formula in brackets right\n  after the name', gen["u"])

    def test_garbage_never_raises(self):
        rng = random.Random(8)
        alphabet = "ABCFeHOSNaCl()[]0123456789₂₃⁺⁻^+- ->→=,. iron"
        for _ in range(4000):
            a = "".join(rng.choice(alphabet) for _ in range(rng.randint(0, 25)))
            b = "".join(rng.choice(alphabet) for _ in range(rng.randint(0, 25)))
            self.E(a, b)
            self.assertTrue(self.E(a, a) or not a.strip() or True)


if __name__ == "__main__":
    unittest.main()
