"""
Stress tests for answer grading — offline, no model calls.

Layers attacked, each on its own:
  units         every unit the engine uses, many writings of each, known conversion factors
  answer line   every reasonable way a model may format [TYPE][CALC_VALUE][CALC_UNIT][SUBSTANCE]
  numbers       thousands of random values across 60 orders of magnitude, correct answers in
                other units must match, unit-factor / sign / 3 %-off answers must not
  options       choice, letters and text answers in their usual variants
  decision      every row of the solved? table, including malformed verifier replies
  fuzz          random garbage through the whole path must never raise
"""

import random
import unittest
from types import SimpleNamespace
from unittest import mock

from core import answers, models, units
from core.engine.physical import STEPS
from core.pipeline import flow, stages


def _res(answer, unit="", kind="real", tol=0.01, fmt=None):
    return SimpleNamespace(answer=answer, unit=unit, kind=kind, tolerance=tol, fmt=fmt)


def _member(result, line, working="w"):
    """A member record exactly as stages._solve builds it from an answer line."""
    spec = answers.answer_spec(result.answer, result.kind, result.unit, getattr(result, "fmt", None))
    done = answers.complete_answer(answers.parse_answer_line(line), spec)
    m = {"working": working, "answer_line": line, "final_answer": line, "unit": ""}
    if done.get("ok"):
        m.update(final_answer=done["render"], final_value=done["final_value"])
    return m, done


ENGINE_UNITS = sorted({u for s in STEPS.values()
                       for u in [s.unit] + [p.unit for p in s.needs] + ([s.final[1]] if s.final else [])})


def _writings(u):
    """Plain-text writings of an exam-notation unit: 'kJ mol⁻¹' -> kJ/mol, kJ mol^-1, kJ*mol**-1 ..."""
    sup = str.maketrans("⁰¹²³⁴⁵⁶⁷⁸⁹⁻", "0123456789-")
    toks = []
    for t in u.replace("mm Hg", "mmHg").split():
        m = __import__("re").fullmatch(r"([^⁰¹²³⁴⁵⁶⁷⁸⁹⁻]+)([⁰¹²³⁴⁵⁶⁷⁸⁹⁻]*)", t)
        if not m:
            return []
        toks.append((m.group(1), int(m.group(2).translate(sup)) if m.group(2) else 1))
    if not toks or any(not sym.replace("_", "").isalpha() for sym, _ in toks):
        return []
    caret = " ".join(s if e == 1 else f"{s}^{e}" for s, e in toks)
    star = "*".join(s if e == 1 else f"{s}**{e}" for s, e in toks)
    plain = " ".join(s if e == 1 else f"{s}{e}" for s, e in toks)
    dot = "·".join(s if e == 1 else f"{s}^{e}" for s, e in toks)
    pos = [(s, e) for s, e in toks if e > 0]
    neg = [(s, -e) for s, e in toks if e < 0]
    out = [caret, star, plain, dot]
    if pos and neg:
        num = " ".join(s if e == 1 else f"{s}^{e}" for s, e in pos)
        den = " ".join(s if e == 1 else f"{s}^{e}" for s, e in neg)
        out += [f"{num}/{den}" if len(neg) == 1 else f"{num}/({den})"]
    return out


class Units(unittest.TestCase):
    def test_every_engine_unit_parses_and_round_trips(self):
        for u in ENGINE_UNITS:
            self.assertIsNotNone(units.parse(u), u)
            self.assertAlmostEqual(units.convert(3.7, u, u), 3.7, places=12, msg=u)

    def test_every_writing_of_every_engine_unit(self):
        checked = 0
        for u in ENGINE_UNITS:
            for w in _writings(u):
                f = units.convert(1.0, w, u)
                self.assertIsNotNone(f, (u, w))
                self.assertAlmostEqual(f, 1.0, places=9, msg=(u, w))
                checked += 1
        self.assertGreater(checked, 100)

    def test_known_factors(self):
        cases = [(1, "kJ", "J", 1000), (1, "kcal", "kJ", 4.184), (1, "cal mol^-1", "J/mol", 4.184),
                 (1, "atm", "torr", 760), (1, "atm", "mmHg", 760.0), (1, "atm", "kPa", 101.325),
                 (1, "bar", "Pa", 1e5), (1, "atm", "bar", 1.01325), (1, "L", "mL", 1000), (1, "L", "dm³", 1),
                 (1, "m³", "L", 1000), (1, "cm³", "mL", 1), (1, "M", "mol/L", 1), (1, "mol/dm^3", "M", 1),
                 (1, "mmol/L", "M", 1e-3), (1, "g/mL", "kg/L", 1), (1, "g/cm^3", "g mL⁻¹", 1),
                 (1, "min⁻¹", "s⁻¹", 1 / 60), (1, "h^-1", "s^-1", 1 / 3600), (1, "kJ mol⁻¹", "J/mol", 1000),
                 (1, "J K⁻¹ mol⁻¹", "J/(mol K)", 1), (1, "cal/(mol K)", "J K⁻¹ mol⁻¹", 4.184),
                 (1, "L atm", "J", 101.325), (1, "nm", "m", 1e-9), (1, "Å", "pm", 100), (1, "pm", "m", 1e-12),
                 (1, "kg", "g", 1000), (1, "mg", "g", 1e-3), (1, "u", "g/mol", None), (1, "S cm² mol⁻¹", "S m² mol⁻¹", 1e-4),
                 (1, "mS", "S", 1e-3), (1, "C", "A s", 1), (1, "kJ", "kJ", 1), (25, "°C", "K", 298.15),
                 (0, "°C", "K", 273.15), (300, "K", "°C", 26.85), (1, "ppm", "%", 1e-4), (50, "%", "", 0.5)]
        for v, a, b, want in cases:
            got = units.convert(v, a, b)
            if want is None:
                self.assertIsNone(got, (a, b))
            else:
                self.assertIsNotNone(got, (a, b))
                self.assertAlmostEqual(got / want, 1.0, places=6, msg=(v, a, b, got))

    def test_different_kinds_are_refused(self):
        for a, b in [("L", "kg"), ("J", "K"), ("eV", "kJ mol⁻¹"), ("mol", "g"), ("atm", "L"), ("s", "s⁻¹"),
                     ("J/mol", "J"), ("M", "mol"), ("BM", "J")]:
            self.assertIsNone(units.convert(1.0, a, b), (a, b))

    def test_nonsense_units_are_unreadable(self):
        for u in ("blorps", "kJ per mole-ish", "???", "kJ//mol", "L L L L L ^^"):
            if units.parse(u) is not None:
                # readable nonsense must still not convert to an unrelated unit
                self.assertIsNone(units.convert(1, u, "kJ mol⁻¹"), u)


class AnswerLine(unittest.TestCase):
    BASE = {"type": "thermo", "calc_value": ["-45200"], "calc_unit": ["J"], "substance": []}

    def _same(self, text):
        p = answers.parse_answer_line(text)
        self.assertIsNotNone(p, text)
        self.assertEqual((p["calc_value"], p["calc_unit"]), (self.BASE["calc_value"], self.BASE["calc_unit"]), text)

    def test_formatting_variants(self):
        for t in ["[TYPE: thermo] [CALC_VALUE: -45200] [CALC_UNIT: J] [SUBSTANCE: null]",
                  "[type: thermo] [calc_value: -45200] [calc_unit: J] [substance: null]",
                  "[TYPE:thermo][CALC_VALUE:-45200][CALC_UNIT:J][SUBSTANCE:null]",
                  "[ TYPE : thermo ]  [ CALC_VALUE : -45200 ]  [ CALC_UNIT : J ]",
                  "[CALC VALUE: -45200] [CALC UNIT: J]",
                  "[CALC_VALUES: -45200] [CALC_UNITS: J]",
                  "[SUBSTANCE: null] [CALC_UNIT: J] [CALC_VALUE: -45200] [TYPE: thermo]",
                  "Final: [TYPE: thermo] [CALC_VALUE: -45200] [CALC_UNIT: J] [SUBSTANCE: null]. Done.",
                  "```\n[TYPE: thermo]\n[CALC_VALUE: -45200]\n[CALC_UNIT: J]\n[SUBSTANCE: null]\n```",
                  "`[TYPE: thermo] [CALC_VALUE: −45200] [CALC_UNIT: J]`",
                  "[TYPE: thermo] [CALC_VALUE: -45200] [CALC_UNIT: J] [TARGET_UNIT: kJ] [FINAL_VALUE: 999] [RENDER: wrong]",
                  {"TYPE": "thermo", "CALC_VALUE": -45200, "CALC_UNIT": "J", "SUBSTANCE": None},
                  {"calc_value": "-45200", "calc_unit": "J"},
                  {"Calc Value": [-45200], "Calc Unit": ["J"]}]:
            self._same(t)

    def test_brackets_and_commas_inside_values(self):
        p = answers.parse_answer_line("[TYPE: coord] [CALC_VALUE: K4[Fe(CN)6]] [CALC_UNIT: none] [SUBSTANCE: K4[Fe(CN)6], [Co(NH3)6]Cl3]")
        self.assertEqual(p["calc_value_raw"], "K4[Fe(CN)6]")
        self.assertEqual(p["substance"], ["K4[Fe(CN)6]", "[Co(NH3)6]Cl3"])
        p = answers.parse_answer_line("[CALC_VALUE: 2,2-dimethylpropane] [CALC_UNIT: none]")
        self.assertEqual(p["calc_value_raw"], "2,2-dimethylpropane")

    def test_no_line(self):
        for t in [None, "", "V = 29.8 L", 29.8, [], {}, {"answer": 29.8}, "[TYPE: x] [CALC_UNIT: J]", "[CALC_VALUE: ]"]:
            self.assertIsNone(answers.parse_answer_line(t), t)


class Numbers(unittest.TestCase):
    PAIRS = [("kJ mol⁻¹", "J/mol"), ("kJ mol⁻¹", "kcal/mol"), ("L", "mL"), ("L", "m^3"), ("mL", "L"),
             ("atm", "torr"), ("atm", "kPa"), ("atm", "bar"), ("s⁻¹", "min^-1"), ("mol L⁻¹", "mmol/L"),
             ("mol L⁻¹", "M"), ("g mL⁻¹", "kg/L"), ("J K⁻¹ mol⁻¹", "cal/(mol K)"), ("kJ", "J"), ("g", "mg"),
             ("nm", "pm"), ("K", "K"), ("", "none"), ("V", "mV"), ("S cm² mol⁻¹", "S m^2 mol^-1"),
             ("L mol⁻¹ s⁻¹", "dm^3 mol^-1 s^-1"), ("g mol⁻¹", "kg/mol"), ("Pa", "atm")]

    def _sig3(self, x):
        return float(f"{x:.3g}")

    def test_random_correct_answers_in_other_units_match(self):
        rng = random.Random(1234)
        n = 0
        for _ in range(4000):
            target, alt = rng.choice(self.PAIRS)
            v = rng.choice((-1, 1)) * rng.uniform(1, 10) * 10 ** rng.randint(-30, 30)
            if target == "K":
                v = abs(v)
            alt_v = self._sig3(units.convert(v, target, alt))             # what a solver would write
            r = _res(v, target)
            m, done = _member(r, f"[TYPE: t] [CALC_VALUE: {alt_v:.3e}] [CALC_UNIT: {alt}] [SUBSTANCE: null]")
            self.assertTrue(done["ok"], (v, target, alt, done))
            self.assertTrue(flow._code_match(r, m), (v, target, alt, alt_v, done))
            n += 1
        self.assertEqual(n, 4000)

    def test_random_wrong_answers_never_match(self):
        rng = random.Random(99)
        for _ in range(4000):
            target, alt = rng.choice(self.PAIRS)
            v = rng.uniform(1, 10) * 10 ** rng.randint(-30, 30)
            r = _res(v, target, tol=rng.choice((0.01, 0.0225, 0.05)))
            right = units.convert(v, target, alt)
            for wrong in (right * 1000, right / 1000, right * 10, right / 10, right * (1 + 2.2 * r.tolerance),
                          right * (1 - 2.2 * r.tolerance), -right):
                m, done = _member(r, f"[CALC_VALUE: {wrong:.6e}] [CALC_UNIT: {alt}]")
                self.assertTrue(done["ok"])
                self.assertFalse(flow._code_match(r, m), (v, target, alt, wrong))

    def test_forgot_to_convert_is_wrong(self):
        r = _res(156.1, "kJ mol⁻¹")
        m, _ = _member(r, "[CALC_VALUE: 156100] [CALC_UNIT: kJ/mol]")     # the number is J, labelled kJ
        self.assertFalse(flow._code_match(r, m))
        m, _ = _member(r, "[CALC_VALUE: 156100] [CALC_UNIT: J/mol]")
        self.assertTrue(flow._code_match(r, m))

    def test_number_formats(self):
        r = _res(1.507e-15, "", tol=0.0225)
        for v in ("1.507e-15", "1.507E-15", "1.51e-15", "+1.51e-15", "0.00000000000000151", "15.07e-16", "1.507e-015"):
            m, done = _member(r, f"[CALC_VALUE: {v}] [CALC_UNIT: none]")
            self.assertTrue(done["ok"] and flow._code_match(r, m), v)
        for v in ("1.5 × 10^-15", "1.5x10-15", "1,507e-15", "about 1.5e-15", "1.5e-15 (approx)", "3/2e-15", "1.5 e-15"):
            m, done = _member(r, f"[CALC_VALUE: {v}] [CALC_UNIT: none]")
            self.assertFalse(done["ok"], v)                               # restate request, never a guess

    def test_zero_answer(self):
        r = _res(0.0, "J")
        for v, want in (("0", True), ("0.0", True), ("-0", True), ("1e-17", True), ("0.001", False), ("5", False)):
            m, done = _member(r, f"[CALC_VALUE: {v}] [CALC_UNIT: J]")
            self.assertEqual(flow._code_match(r, m), want, v)

    def test_offset_temperatures(self):
        r = _res(298.15, "K")
        for v, u in (("298.15", "K"), ("25", "°C"), ("25", "degC"), ("77", "°F")):
            m, done = _member(r, f"[CALC_VALUE: {v}] [CALC_UNIT: {u}]")
            self.assertTrue(done["ok"] and flow._code_match(r, m), (v, u))

    def test_several_substances(self):
        r = SimpleNamespace(answer=[0.75, 0.25], unit="atm", kind="real", tolerance=0.01)
        spec = {"type": "number", "unit": "atm", "count": 2}
        done = answers.complete_answer(answers.parse_answer_line(
            "[TYPE: eq] [CALC_VALUE: 570, 0.25] [CALC_UNIT: torr, atm] [SUBSTANCE: N2, H2]"), spec)
        self.assertTrue(done["ok"])
        self.assertAlmostEqual(done["final_value"][0], 0.75, places=6)
        self.assertEqual(done["render"], "0.75 atm, 0.25 atm")
        one_unit = answers.complete_answer(answers.parse_answer_line("[CALC_VALUE: 570, 190] [CALC_UNIT: torr]"), spec)
        self.assertEqual([round(x, 6) for x in one_unit["final_value"]], [0.75, 0.25])
        self.assertFalse(answers.complete_answer(answers.parse_answer_line(
            "[CALC_VALUE: 570, 190] [CALC_UNIT: torr, atm, K]"), spec)["ok"])


class MultipleValues(unittest.TestCase):
    """Answers with several values (one per substance), as in
    [TYPE: equilibrium] [CALC_VALUE: 0.75, 570] [CALC_UNIT: atm, torr] [SUBSTANCE: N2, H2]."""

    def _r(self, vals, unit="atm", subs=("N2", "H2"), tol=0.01):
        return SimpleNamespace(answer=list(vals), unit=unit, kind="real", tolerance=tol,
                               answer_substances=list(subs) if subs else None)

    def _member(self, r, line):
        spec = answers.answer_spec(r.answer, r.kind, r.unit, None, r.answer_substances)
        done = answers.complete_answer(answers.parse_answer_line(line), spec)
        m = {"working": "w", "final_answer": line, "unit": ""}
        if done.get("ok"):
            m.update(final_value=done["final_value"], final_answer=done["render"], substance=done.get("substance"))
        return m, done

    def test_user_example_and_variants(self):
        r = self._r([0.75, 0.75])
        cases = [
            ("[TYPE: equilibrium] [CALC_VALUE: 0.75, 570] [CALC_UNIT: atm, torr] [SUBSTANCE: N2, H2]", True),
            ("[CALC_VALUE: 570, 0.75] [CALC_UNIT: torr, atm] [SUBSTANCE: H2, N2]", True),          # swapped, labelled
            ("[CALC_VALUE: 0.75, 0.75] [CALC_UNIT: atm] [SUBSTANCE: N₂, H₂]", True),              # one unit, subscripts
            ("[CALC_VALUE: 0.75, 0.75] [CALC_UNIT: atm] [SUBSTANCE: N2(g), H2(g)]", True),        # state labels
            ("[CALC_VALUE: 0.75, 0.75] [CALC_UNIT: atm] [SUBSTANCE: null]", True),                # no labels: by position
            ("[CALC_VALUE: 0.75, 0.80] [CALC_UNIT: atm] [SUBSTANCE: N2, H2]", False),             # one value wrong
            ("[CALC_VALUE: 0.75, 0.75] [CALC_UNIT: atm] [SUBSTANCE: N2, O2]", False),             # wrong substance
            ("[CALC_VALUE: 0.75, 0.75] [CALC_UNIT: atm] [SUBSTANCE: N2, N2]", False),             # duplicate label
            ("[CALC_VALUE: 0.75, 570] [CALC_UNIT: atm, atm] [SUBSTANCE: N2, H2]", False),         # forgot torr->atm
        ]
        for line, want in cases:
            m, done = self._member(r, line)
            self.assertTrue(done["ok"], (line, done))
            self.assertEqual(flow._code_match(r, m), want, line)

    def test_position_matters_without_labels(self):
        r = self._r([0.25, 0.75], subs=None)
        m, _ = self._member(r, "[CALC_VALUE: 0.25, 0.75] [CALC_UNIT: atm]")
        self.assertTrue(flow._code_match(r, m))
        m, _ = self._member(r, "[CALC_VALUE: 0.75, 0.25] [CALC_UNIT: atm]")
        self.assertFalse(flow._code_match(r, m))
        r = self._r([0.25, 0.75])                         # engine labelled, member did not: by position
        m, _ = self._member(r, "[CALC_VALUE: 0.75, 0.25] [CALC_UNIT: atm] [SUBSTANCE: null]")
        self.assertFalse(flow._code_match(r, m))

    def test_wrong_count_is_a_restate_not_a_grade(self):
        r = self._r([0.75, 0.25])
        for line in ("[CALC_VALUE: 0.75] [CALC_UNIT: atm]", "[CALC_VALUE: 0.75, 0.25, 0.1] [CALC_UNIT: atm]",
                     "[CALC_VALUE: 0.75, 0.25] [CALC_UNIT: atm, atm, atm]"):
            _, done = self._member(r, line)
            self.assertFalse(done["ok"], line)

    def test_zero_and_mixed_kinds(self):
        r = self._r([0.0, 2.5], unit="mol", subs=("A", "B"))
        m, _ = self._member(r, "[CALC_VALUE: 0, 2500] [CALC_UNIT: mol, mmol] [SUBSTANCE: A, B]")
        self.assertTrue(flow._code_match(r, m))
        m, _ = self._member(r, "[CALC_VALUE: 0.01, 2.5] [CALC_UNIT: mol] [SUBSTANCE: A, B]")
        self.assertFalse(flow._code_match(r, m))

    def test_random_permutations(self):
        rng = random.Random(5)
        names = ["N2", "H2", "NH3", "O2", "CO2", "SO3", "Cl2", "HCl"]
        alts = [("atm", "torr"), ("atm", "kPa"), ("mol L⁻¹", "mmol/L"), ("kJ mol⁻¹", "J/mol")]
        for _ in range(1500):
            n = rng.randint(2, 4)
            unit, alt = rng.choice(alts)
            subs = rng.sample(names, n)
            vals = [rng.uniform(1, 10) * 10 ** rng.randint(-6, 6) for _ in range(n)]
            r = self._r(vals, unit=unit, subs=subs)
            order = list(range(n))
            rng.shuffle(order)
            written = [float(f"{units.convert(vals[i], unit, alt):.3g}") for i in order]
            line = (f"[TYPE: t] [CALC_VALUE: {', '.join(f'{w:.3e}' for w in written)}] [CALC_UNIT: {alt}] "
                    f"[SUBSTANCE: {', '.join(subs[i] for i in order)}]")
            m, done = self._member(r, line)
            self.assertTrue(done["ok"] and flow._code_match(r, m), line)
            k = rng.randrange(n)                                   # now break one value
            written[k] *= 1.05
            bad = (f"[CALC_VALUE: {', '.join(f'{w:.3e}' for w in written)}] [CALC_UNIT: {alt}] "
                   f"[SUBSTANCE: {', '.join(subs[i] for i in order)}]")
            m, done = self._member(r, bad)
            self.assertFalse(flow._code_match(r, m), bad)

    def test_stem_and_prompt_for_several_values(self):
        r = self._r([0.75, 0.25])
        ad = SimpleNamespace(answer_format=lambda x: None)
        self.assertEqual(flow._answer_instruction(ad, r),
                         "Give the 2 answers in atm, to 3 significant figures, in the order: N2, H2.")
        spec = answers.answer_spec(r.answer, r.kind, r.unit, None, r.answer_substances)
        text = answers.spec_instruction(spec)
        self.assertIn("Give exactly 2 values", text)
        self.assertIn("(N2, H2)", text)
        self.assertEqual(flow.answer_text(r), "N2: 0.75 atm, H2: 0.25 atm")

    def test_solver_and_grade_for_several_values(self):
        r = self._r([0.75, 0.25])
        spec = answers.answer_spec(r.answer, r.kind, r.unit, None, r.answer_substances)
        replies = iter([{"working": "pN2 = 570 torr, pH2 = 0.25 atm", "answer": "pN2 = 570 torr, pH2 = 0.25 atm"},
                        {"answer": "[TYPE: equilibrium] [CALC_VALUE: 570, 0.25] [CALC_UNIT: torr, atm] [SUBSTANCE: N2, H2]"}])
        with mock.patch.object(models, "ask_json", lambda *a, **k: next(replies)):
            out = stages._solve("x/y", "stem", spec=spec)
        self.assertTrue(out["format_repaired"])
        self.assertEqual(out["substance"], ["N2", "H2"])
        g = flow._grade(r, out, {"verdict": "correct"})
        self.assertTrue(g["counts_as_solved"])
        g = flow._grade(r, {**out, "final_value": [0.75, 0.3]}, {"verdict": "wrong", "failure_type": "slip",
                                                                  "member_expression": "570/760"})
        self.assertFalse(g["counts_as_solved"])          # no slip confirmation for several values


class OptionsAndText(unittest.TestCase):
    DIR = "Answer with exactly one of: forward, backward, no shift."

    def test_choice(self):
        r = _res("forward", kind="text", fmt=self.DIR)
        for v, want in (("forward", True), ("Forward", True), ("FORWARD.", True), ("'forward'", True),
                        ("backward", False), ("no shift", False)):
            m, done = _member(r, f"[CALC_VALUE: {v}] [CALC_UNIT: none]")
            self.assertTrue(done["ok"], v)
            self.assertEqual(flow._code_match(r, m), want, v)
        m, done = _member(r, "[CALC_VALUE: shifts to the right] [CALC_UNIT: none]")
        self.assertFalse(done["ok"])                                       # not an option -> restate

    def test_yes_no(self):
        r = _res("precipitate forms", kind="text", fmt="Answer yes or no.")
        for v, want in (("yes", True), ("Yes", True), ("no", False), ("No.", False)):
            m, done = _member(r, f"[CALC_VALUE: {v}] [CALC_UNIT: none]")
            self.assertTrue(done["ok"], v)
            self.assertEqual(flow._code_match(r, m), want, v)

    def test_letters(self):
        r = _res(["A", "C"], kind="letters")
        for v, want in (("AC", True), ("CA", True), ("A, C", True), ("A and C", True), ("(A) (C)", True),
                        ("A", False), ("ABC", False), ("C", False)):
            m, done = _member(r, f"[CALC_VALUE: {v}] [CALC_UNIT: none]")
            self.assertTrue(done["ok"], v)
            self.assertEqual(flow._code_match(r, m), want, v)

    def test_text_shapes(self):
        cases = [("CH2O", "CH₂O", True), ("CH2O", "C6H12O6", False), ("Th-234", "234Th", True),
                 ("Th-234", "Pa-234", False), ("1s2 2s2 2p6", "1s² 2s² 2p⁶", True), ("3d", "3d", True),
                 ("AgCl", "AgCl(s)", True), ("2H2 + O2 -> 2H2O", "4H2 + 2O2 -> 4H2O", True),
                 ("K4[Fe(CN)6]", "K4[Fe(CN)6]", True)]
        for engine, given, want in cases:
            r = _res(engine, kind="text")
            m, done = _member(r, f"[CALC_VALUE: {given}] [CALC_UNIT: none]")
            self.assertTrue(done["ok"], given)
            self.assertEqual(bool(flow._code_match(r, m)), want, (engine, given))


class DecisionTable(unittest.TestCase):
    """solved? for every (answer matches?, verifier verdict, failure type) combination."""

    def test_every_row(self):
        r = _res(29.79, "L")
        right, _ = _member(r, "[CALC_VALUE: 29.8] [CALC_UNIT: L]", working="V = 1.4173*0.0821*320/1.25 = 29.8")
        wrong, _ = _member(r, "[CALC_VALUE: 31.0] [CALC_UNIT: L]", working="V = 1.4173*0.0821*320/1.25 = 31.0")
        good_expr = "1.4173*0.0821*320/1.25"
        rows = []
        for verdict in ("correct", "right_answer_wrong_reasoning", "wrong", "reference_wrong"):
            for ft in (None, "slip", "genuine_difficulty", "missing_knowledge", "unclear_wording"):
                rows.append((right, verdict, ft, None, verdict == "correct" or (verdict == "wrong" and ft == "slip")))
                slip_path = ft == "slip" or verdict == "correct"
                rows.append((wrong, verdict, ft, good_expr, slip_path))
                rows.append((wrong, verdict, ft, None, False))
        for member, verdict, ft, expr, want in rows:
            diag = {"verdict": verdict, "failure_type": ft, "member_expression": expr}
            g = flow._grade(r, member, diag)
            self.assertEqual(g["counts_as_solved"], want, (member["final_answer"], verdict, ft, expr))

    def test_malformed_verifier_replies_do_not_crash(self):
        r = _res(29.79, "L")
        m, _ = _member(r, "[CALC_VALUE: 29.8] [CALC_UNIT: L]")
        for diag in ({}, {"verdict": None}, {"verdict": "weird"}, {"verdict": "wrong", "failure_type": "slip",
                     "member_expression": "import os"}, {"verdict": "wrong", "failure_type": "slip",
                     "member_expression": "1/0"}, {"verdict": "correct", "member_expression": 12.5},
                     {"answer_equivalent": "yes"}):
            g = flow._grade(r, m, diag)
            self.assertIn(g["counts_as_solved"], (True, False))


class Fuzz(unittest.TestCase):
    """Random garbage anywhere in the path must never raise."""

    JUNK = [None, "", " ", "[]", "[CALC_VALUE:", "[CALC_VALUE: ] ]", "]]][[[", "[CALC_VALUE: nan] [CALC_UNIT: J]",
            "[CALC_VALUE: inf] [CALC_UNIT: J]", "[CALC_VALUE: 1e999] [CALC_UNIT: J]", "[CALC_VALUE: -0] [CALC_UNIT: J]",
            "[CALC_VALUE: 0x1F] [CALC_UNIT: J]", "[CALC_VALUE: 1,,,2] [CALC_UNIT: ,,]", "[CALC_VALUE: 5] [CALC_UNIT: J/0]",
            "[CALC_VALUE: 5] [CALC_UNIT: (((J]", "[CALC_VALUE: 5] [CALC_UNIT: 1/(]", "[CALC_VALUE: 5] [CALC_UNIT: __import__]",
            {"CALC_VALUE": {"x": 1}}, {"CALC_VALUE": [None, None]}, [1, 2, 3], 3.14, True, b"bytes",
            "[CALC_VALUE: " + "9" * 400 + "] [CALC_UNIT: J]", "[CALC_VALUE: 5] [CALC_UNIT: " + "m*" * 200 + "m]"]

    def test_no_raise_anywhere(self):
        rng = random.Random(7)
        specs = [answers.answer_spec(29.79, "positive", "L"), answers.answer_spec("forward", "text", "", OptionsAndText.DIR),
                 answers.answer_spec(["A"], "letters"), answers.answer_spec("CH2O", "text", "", "Give the empirical formula."),
                 answers.answer_spec([0.75, 0.25], "real", "atm", None, ["N2", "H2"])]
        results = [_res(29.79, "L"), _res("forward", kind="text", fmt=OptionsAndText.DIR), _res(["A"], kind="letters"),
                   _res("CH2O", kind="text"),
                   SimpleNamespace(answer=[0.75, 0.25], unit="atm", kind="real", tolerance=0.01, answer_substances=["N2", "H2"])]
        alphabet = "0123456789.-+eE []:,/^*()abcdeJLkmolsKatm°Cµ⁻¹²³_"
        junk = list(self.JUNK)
        for _ in range(1500):
            junk.append("".join(rng.choice(alphabet) for _ in range(rng.randint(0, 60))))
            junk.append(f"[CALC_VALUE: {rng.choice(alphabet) * rng.randint(0, 5)}] [CALC_UNIT: {rng.choice(alphabet) * 3}]")
        for j in junk:
            p = answers.parse_answer_line(j)
            for spec, r in zip(specs, results):
                done = answers.complete_answer(p, spec)
                self.assertIn(done.get("ok"), (True, False))
                m = {"working": "w", "final_answer": j if isinstance(j, str) else None, "unit": ""}
                if done.get("ok"):
                    m.update(final_value=done["final_value"], final_answer=done["render"], substance=done.get("substance"))
                self.assertIn(flow._code_match(r, m), (True, False, None))
                g = flow._grade(r, m, {"verdict": rng.choice(["correct", "wrong", "right_answer_wrong_reasoning"]),
                                       "failure_type": rng.choice([None, "slip"]), "member_expression": j if isinstance(j, str) else None})
                self.assertIn(g["counts_as_solved"], (True, False))

    def test_solver_reply_shapes(self):
        """Whatever a solver returns, _solve returns a record (repairing or falling back)."""
        spec = answers.answer_spec(29.79, "positive", "L")
        shapes = [{"working": "w", "answer": "[TYPE: g] [CALC_VALUE: 29.8] [CALC_UNIT: L] [SUBSTANCE: N2]"},
                  {"working": "w", "answer": {"CALC_VALUE": 29.8, "CALC_UNIT": "L"}},
                  {"working": "w", "final_answer": 29.8, "unit": "L"},
                  {"working": "w", "answer": "29.8 L"},
                  {"working": "w", "answer": None},
                  {"solution": "w", "result": "[CALC_VALUE: 29790] [CALC_UNIT: mL]"},
                  {"working": ["step 1", "step 2"], "answer": "[CALC_VALUE: 29.8] [CALC_UNIT: litre]"}]
        for shape in shapes:
            repair = {"answer": "[TYPE: g] [CALC_VALUE: 29.8] [CALC_UNIT: L] [SUBSTANCE: N2]"}
            replies = iter([shape, repair])
            with mock.patch.object(models, "ask_json", lambda *a, **k: next(replies)):
                out = stages._solve("x/y", "stem", spec=spec)
            self.assertIn("final_answer", out, shape)
            self.assertEqual(out.get("final_value"), [29.8] if "29790" not in str(shape) else [29.79], shape)


if __name__ == "__main__":
    unittest.main()
