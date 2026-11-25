"""Calculator spellings and the tool loop's round cap (2026-11-25: GLM 5.3 Flash called the calculator
20 rounds, three times; the council call failed and the physical batch stopped)."""
import sys
import types
import unittest
from pathlib import Path
from unittest import mock

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from core import models  # noqa: E402


class CalcSpellings(unittest.TestCase):
    def test_ln_and_prefixes(self):
        e = models._eval_calc
        self.assertEqual(e("ln(e)"), "1")
        self.assertEqual(e("math.log(e)"), "1")
        self.assertEqual(e("np.exp(0)"), "1")
        self.assertEqual(e("log10(1000)"), "3")


class RoundCap(unittest.TestCase):
    def test_answer_asked_at_cap(self):
        tc = types.SimpleNamespace(id="t", function=types.SimpleNamespace(name="calculate",
                                                                         arguments='{"expression": "1+1"}'))
        seen = []

        def create(**kw):
            seen.append(kw["tool_choice"])
            if kw["tool_choice"] == "none":
                msg = types.SimpleNamespace(content='{"working": "w", "answer": "2"}', tool_calls=None)
            else:
                msg = types.SimpleNamespace(content=None, tool_calls=[tc])
            return types.SimpleNamespace(choices=[types.SimpleNamespace(message=msg, finish_reason="stop")], usage=None)
        client = types.SimpleNamespace(chat=types.SimpleNamespace(completions=types.SimpleNamespace(create=create)))
        with mock.patch.object(models, "_client", lambda w: client), mock.patch("builtins.print"):
            out = models._ask_json_with_tools("council", "m", "m", "openrouter", "s", "u", 100, 0.2, {},
                                              models.CALC_TOOL, {})
        self.assertEqual(out["answer"], "2")
        self.assertEqual(seen[-1], "none")
        self.assertEqual(seen.count("none"), 1)


if __name__ == "__main__":
    unittest.main()
