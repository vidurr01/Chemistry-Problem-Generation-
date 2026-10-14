"""
Reading model replies (core.llm.parse_json), offline.

Phi-4's calibration replies were sometimes unreadable ("Could not parse JSON"): a quote left
unescaped inside the working ends the string early, so no balanced {...} is found. Each
shape of broken reply a model writes is here, and every valid reply must parse exactly as
json.loads does.
"""

import json
import os
import random
import sys
import tempfile
import types
import unittest
from pathlib import Path
from unittest import mock

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from core import llm                                            # noqa: E402
from core.llm import parse_json                                 # noqa: E402

GOOD = {"working": "n = 4.4/44 = 0.1 mol", "final_answer": "2.24", "unit": "L", "objection": None}


class BrokenReplies(unittest.TestCase):
    def test_unescaped_quotes_in_working(self):
        raw = ('{\n  "working": "1. The reaction of acetaldehyde with excess formaldehyde is a "crossed '
               'Cannizzaro" reaction; the "aldol" step comes first.",\n  "final_answer": "18",\n'
               '  "unit": "",\n  "objection": null\n}')
        got = parse_json(raw)
        self.assertEqual(got["final_answer"], "18")
        self.assertIn('"crossed Cannizzaro"', got["working"])
        self.assertIsNone(got["objection"])

    def test_quote_then_colon_or_brace_text(self):
        raw = '{"working": "he said "x" then {y}", "final_answer": 5}'
        self.assertEqual(parse_json(raw)["final_answer"], 5)

    def test_raw_line_breaks_inside_strings(self):
        raw = '{"working": "line one\nline two\ttabbed", "final_answer": "0.22"}'
        got = parse_json(raw)
        self.assertEqual(got["final_answer"], "0.22")
        self.assertIn("line two", got["working"])

    def test_latex_backslashes(self):
        raw = r'{"working": "\Delta G = -RT \ln K, \ce{H2O}", "final_answer": "4.5"}'
        self.assertEqual(parse_json(raw)["final_answer"], "4.5")

    def test_fences_prose_and_second_object(self):
        raw = 'Here is my answer:\n```json\n' + json.dumps(GOOD) + '\n```\nAnd {"note": 1}'
        self.assertEqual(parse_json(raw), GOOD)
        self.assertEqual(parse_json("Sure! " + json.dumps(GOOD) + " Hope it helps."), GOOD)
        self.assertEqual(parse_json("[" + json.dumps(GOOD) + "]"), GOOD)

    def test_combined_faults(self):
        raw = ('{"working": "the "Hofmann" product,\nthen \\ce{CH3NH2}", '
               '"final_answer": "3", "unit": "", "objection": null}')
        self.assertEqual(parse_json(raw)["final_answer"], "3")

    def test_truly_truncated_reply_still_fails(self):
        with self.assertRaises(ValueError):
            parse_json('{\n  "working": "1. The reaction of acetaldehyde with excess formaldehyde')
        with self.assertRaises(ValueError):
            parse_json("no json here at all")


class ValidRepliesUnchanged(unittest.TestCase):
    def test_random_valid_objects(self):
        """5000 random valid objects (quotes, braces, backslashes, unicode in the strings):
        parse_json must equal json.loads on each, so the repairs never touch valid JSON."""
        rng = random.Random(4)
        alphabet = 'abc xyz 0123456789 "{}[]:,\\/ \n\t ΔG° → ⁻¹ ₂ \' '
        for _ in range(5000):
            obj = {"working": "".join(rng.choice(alphabet) for _ in range(rng.randint(0, 80))),
                   "final_answer": rng.choice([None, 0, -1.5, "2.24", "Th-234", [1, 2], {"a": "b"}]),
                   "unit": rng.choice(["", "L", "kJ mol⁻¹"]), "objection": rng.choice([None, {"type": "wording",
                                                                                     "detail": 'a "b" c'}])}
            text = json.dumps(obj, ensure_ascii=rng.random() < 0.5, indent=rng.choice([None, 2]))
            self.assertEqual(parse_json(text), obj, text)


class UnreadableRepliesAreKept(unittest.TestCase):
    def test_logged_whole(self):
        tmp = os.path.join(tempfile.mkdtemp(), "unparseable.jsonl")
        bad = '{"working": "cut off here'
        resp = types.SimpleNamespace(model="microsoft/phi-4",
                                     choices=[types.SimpleNamespace(finish_reason="length",
                                                                    message=types.SimpleNamespace(content=bad))])
        with mock.patch.object(llm, "UNPARSEABLE_LOG", tmp), mock.patch.object(llm, "call_with_retry", lambda *a, **k: resp), \
                mock.patch("builtins.print"):
            with self.assertRaises(ValueError):
                llm.call_json(lambda: resp, parse_json, parse_retries=1, label="council")
        lines = [json.loads(x) for x in open(tmp, encoding="utf-8")]
        self.assertEqual(len(lines), 2)                     # first try and the retry
        self.assertEqual(lines[0]["content"], bad)
        self.assertEqual((lines[0]["model"], lines[0]["finish_reason"]), ("microsoft/phi-4", "length"))


if __name__ == "__main__":
    unittest.main()
