"""The model layer (core/models.py): the solvers' calculator, routing and retries (no API calls).

Run:  python -m unittest tests.test_models
"""

import os
import threading
import time
import unittest
from types import SimpleNamespace
from unittest import mock

from core import models


class Calculator(unittest.TestCase):
    def test_ordinary_arithmetic(self):
        self.assertEqual(models._eval_calc("2.5 * 6.022e23 / 1000"), "1.5055e+21")
        self.assertEqual(models._eval_calc("2**10"), "1024")
        self.assertEqual(models._eval_calc("10**-3"), "0.001")
        self.assertEqual(models._eval_calc("factorial(5)"), "120")
        self.assertEqual(models._eval_calc("sqrt(16) + log10(1000)"), "7")

    def test_huge_powers_and_factorials_fail_fast(self):
        # 9**9**9 used to build an integer with ~370 million digits and hang the solver's tool loop
        for expr in ("9**9**9", "10**10**10", "factorial(100000)", "factorial(2.5)"):
            t0 = time.time()
            self.assertTrue(models._eval_calc(expr).startswith("ERROR"), expr)
            self.assertLess(time.time() - t0, 1.0, expr)


def _reply(content=None, tool_calls=None):
    msg = SimpleNamespace(content=content, tool_calls=tool_calls, reasoning=None, model_extra={})
    return SimpleNamespace(choices=[SimpleNamespace(message=msg, finish_reason="stop")], usage=None, model="m")


class ToolCalls(unittest.TestCase):
    """Ladder solvers call the calculator tool; these calls now get the same retries and router switch as
    every other call (before: one transient error or one unreadable reply parked the question)."""

    def _ask(self, script, env=None, sent=None):
        served = []

        def client(where=None):
            def create(**kw):
                served.append(where)
                if sent is not None:
                    sent.append([dict(m) for m in kw["messages"]])
                step = script.pop(0)
                if isinstance(step, Exception):
                    raise step
                return step
            return SimpleNamespace(chat=SimpleNamespace(completions=SimpleNamespace(create=create)))
        env = env or {"OPENROUTER_KEY": "or-test", "AIROUTER_KEY": ""}
        with mock.patch.dict(os.environ, env), mock.patch.object(models, "_client", client), \
                mock.patch.object(models, "_OPENROUTER_OUT", threading.Event()), \
                mock.patch("core.llm.time.sleep"), mock.patch("core.llm._log_unparseable"), \
                mock.patch.object(models, "_log_unparseable"), \
                mock.patch.object(models.SPEND, "add", lambda *a: None), mock.patch("builtins.print"):
            out = models.ask_json("council", "openai/gpt-6-luna", "s", "u", tools=models.CALC_TOOL)
        return out, served

    def test_a_transient_error_is_retried(self):
        class Busy(Exception):
            status_code = 503
        out, served = self._ask([Busy("503 overloaded"), _reply('{"answer": "2.24"}')])
        self.assertEqual(out["answer"], "2.24")
        self.assertEqual(len(served), 2)

    def test_an_unreadable_final_reply_is_asked_again(self):
        out, _ = self._ask([_reply("I think the answer is 2.24"), _reply('{"answer": "2.24"}')])
        self.assertEqual(out["answer"], "2.24")

    def test_a_python_program_instead_of_json_is_answered_in_the_same_conversation(self):
        """Llama 3.3 wrote a Python program three times running (2026-11-18): it is now told, in the same
        conversation, to use the calculator and reply with the JSON; a fresh start had repeated the program."""
        code = "```python\nimport math\nn_H2 = 1.9 * 0.644 / (0.08206 * 294)\n```"
        sent = []
        out, served = self._ask([_reply(code), _reply('{"answer": "54.6"}')], sent=sent)
        self.assertEqual((out["answer"], len(served)), ("54.6", 2))
        second = sent[1]
        self.assertEqual(second[-2], {"role": "assistant", "content": code})          # its own reply kept
        self.assertEqual(second[-1]["content"], models.FORMAT_NUDGE)
        self.assertEqual(second[1]["content"], "u")                                     # the same conversation

    def test_a_program_then_an_empty_reply_is_still_answered(self):
        """Run of 2026-11-19: Llama wrote a program, was told, then replied with nothing; the empty reply
        ended the call and the parked question was parked again. An empty reply is now told too."""
        code = "```python\nimport math\n```"
        sent = []
        out, served = self._ask([_reply(code), _reply(""), _reply('{"answer": "50.3"}')], sent=sent)
        self.assertEqual((out["answer"], len(served)), ("50.3", 3))
        third = sent[2]
        self.assertEqual(third[-1]["content"], models.EMPTY_NUDGE)
        self.assertNotIn({"role": "assistant", "content": ""}, third)                # no empty assistant turn

    def test_tool_rounds_then_answer(self):
        call = SimpleNamespace(id="c1", function=SimpleNamespace(name="calculate",
                                                                 arguments='{"expression": "0.1*22.4"}'))
        out, served = self._ask([_reply(tool_calls=[call]), _reply('{"answer": "2.24"}')])
        self.assertEqual((out["answer"], len(served)), ("2.24", 2))

    def test_out_of_credit_moves_to_airouter(self):
        class Out(Exception):
            status_code = 402
        out, served = self._ask([Out("Error code: 402"), _reply('{"answer": "2.24"}')],
                                env={"OPENROUTER_KEY": "or-test", "AIROUTER_KEY": "ar-test"})
        self.assertEqual(out["answer"], "2.24")
        self.assertEqual(served, ["openrouter", "airouter"])


class Keys(unittest.TestCase):
    def test_a_key_for_the_router_the_model_goes_to(self):
        with mock.patch.dict(os.environ, {"OPENROUTER_KEY": "", "AIROUTER_KEY": "ar-test"}):
            self.assertTrue(models.key_is_set())
            self.assertTrue(models.key_is_set("openai/gpt-6-luna"))
            self.assertFalse(models.key_is_set("microsoft/phi-4"))        # only OpenRouter serves it
        with mock.patch.dict(os.environ, {"OPENROUTER_KEY": "or-test", "AIROUTER_KEY": ""}):
            self.assertTrue(models.key_is_set("microsoft/phi-4"))
        with mock.patch.dict(os.environ, {"OPENROUTER_KEY": "your-key-here", "AIROUTER_KEY": ""}):
            self.assertFalse(models.key_is_set())                          # the .env placeholder


class JevRetries(unittest.TestCase):
    """refine._jev_post: a refusal no retry can change is said at once; a transient one is retried."""

    def _post(self, errors):
        import io
        import json
        import urllib.error
        from core.pipeline import refine
        tries, pauses = [], []

        def urlopen(req, timeout=0):
            tries.append(1)
            if errors:
                code = errors.pop(0)
                raise urllib.error.HTTPError("u", code, "x", {}, io.BytesIO(b"{}"))
            body = json.dumps({"answers": {"q": {"noul": 0.7}}, "usage": {}}).encode()
            return mock.MagicMock(__enter__=lambda s: SimpleNamespace(read=lambda: body), __exit__=lambda *a: False)
        with mock.patch.dict(os.environ, {"OPENROUTER_KEY": "or-test", "AIROUTER_KEY": ""}), \
                mock.patch("urllib.request.urlopen", urlopen), mock.patch("time.sleep", pauses.append), \
                mock.patch.object(models.SPEND, "add", lambda *a: None):
            try:
                out = refine.jev_decide({"x": 1}, {"q": "?"})
            except RuntimeError as e:
                out = e
        return out, len(tries), pauses

    def test_a_bad_key_is_not_retried(self):
        out, tries, pauses = self._post([401])
        self.assertIsInstance(out, RuntimeError)
        self.assertEqual((tries, pauses), (1, []))

    def test_an_overloaded_router_is_retried(self):
        out, tries, _ = self._post([503, 503])
        self.assertEqual((out, tries), ({"q": 0.7}, 3))


class NumbersInAnswers(unittest.TestCase):
    def test_thousands_separators_and_approximate_signs(self):
        from core.answers import numeric_value
        for text, want in (("1,200 J", 1200.0), ("12,500", 12500.0), ("-1,200", -1200.0), ("1,234,567.5 J", 1234567.5),
                           ("≈ 0.25", 0.25), ("~0.25", 0.25), ("approximately 0.25", 0.25), ("Approx. 3.1 kJ", 3.1),
                           ("2.5 × 10⁻³ M", 0.0025), ("pH = 4.74", 4.74), ("3/4", 0.75)):
            self.assertAlmostEqual(numeric_value(text), want, msg=text)
        for text in ("1,2", "2, 3", "x = 2, y = 3", "Option B"):     # not one number: left to the verifier
            self.assertIsNone(numeric_value(text), text)


class RunSpend(unittest.TestCase):
    """A run keeps its running spend in SPEND_FILE, so the batch driver counts a run killed at its timeout
    (which never prints "Spend this run")."""

    def test_running_total_file_and_the_drivers_reading_of_it(self):
        import tempfile
        import generate_questions as gq
        path = os.path.join(tempfile.mkdtemp(), "spend.txt")
        spend = models.Spend()
        with mock.patch.dict(os.environ, {"SPEND_FILE": path}):
            spend.add("council", {"cost": 0.01})
            spend.add("verifier", {"total_cost": 0.002})
        self.assertAlmostEqual(gq._run_spend(path, printed=[]), 0.012)
        self.assertFalse(os.path.exists(path))                           # read once, then removed
        self.assertEqual(gq._run_spend(path, printed=[0.05]), 0.05)       # no file: the printed line
        self.assertEqual(gq._run_spend(path, printed=[]), 0.0)


class ForcedCalculator(unittest.TestCase):
    """The author (2026-11-19): ladder solvers must use the calculator. Their first turn is tool_choice
    "required", later turns "auto"; a provider that refuses "required" is asked unforced, not failed."""

    def _run(self, script):
        choices = []

        def client(where=None):
            def create(**kw):
                choices.append(kw["tool_choice"])
                step = script.pop(0)
                if isinstance(step, Exception):
                    raise step
                return step
            return SimpleNamespace(chat=SimpleNamespace(completions=SimpleNamespace(create=create)))
        with mock.patch.dict(os.environ, {"OPENROUTER_KEY": "or-test", "AIROUTER_KEY": ""}), \
                mock.patch.object(models, "_client", client), \
                mock.patch.object(models, "_OPENROUTER_OUT", threading.Event()), \
                mock.patch("core.llm.time.sleep"), mock.patch.object(models, "_log_unparseable"), \
                mock.patch.object(models.SPEND, "add", lambda *a: None), mock.patch("builtins.print"):
            out = models.ask_json("council", "meta-llama/llama-3.3-70b-instruct", "s", "u", tools=models.CALC_TOOL)
        return out, choices

    def test_first_turn_required_then_auto(self):
        call = SimpleNamespace(id="c1", function=SimpleNamespace(name="calculate", arguments='{"expression": "2*3"}'))
        out, choices = self._run([_reply(tool_calls=[call]), _reply('{"answer": "6"}')])
        self.assertEqual((out["answer"], choices), ("6", ["required", "auto"]))

    def test_one_tool_call_per_turn(self):
        """Hosts of Llama 3.3 refused a turn with several calls ("only supports single tool-calls at once!", 11 of
        96 calibration questions unanswered): parallel calls are switched off, and a turn that still has several
        keeps only its first in the conversation."""
        sent = []

        def client(where=None):
            def create(**kw):
                sent.append({"parallel": kw.get("parallel_tool_calls"), "messages": [dict(m) for m in kw["messages"]]})
                return script.pop(0)
            return SimpleNamespace(chat=SimpleNamespace(completions=SimpleNamespace(create=create)))
        two = [SimpleNamespace(id=f"c{i}", function=SimpleNamespace(name="calculate", arguments='{"expression": "1+1"}'))
               for i in (1, 2)]
        script = [_reply(tool_calls=two), _reply('{"answer": "2"}')]
        with mock.patch.dict(os.environ, {"OPENROUTER_KEY": "or-test", "AIROUTER_KEY": ""}), \
                mock.patch.object(models, "_client", client), \
                mock.patch.object(models, "_OPENROUTER_OUT", threading.Event()), \
                mock.patch("core.llm.time.sleep"), mock.patch.object(models, "_log_unparseable"), \
                mock.patch.object(models.SPEND, "add", lambda *a: None), mock.patch("builtins.print"):
            out = models.ask_json("council", "meta-llama/llama-3.3-70b-instruct", "s", "u", tools=models.CALC_TOOL)
        self.assertEqual(out["answer"], "2")
        self.assertEqual({s["parallel"] for s in sent}, {False})
        history = sent[1]["messages"]
        calls = [m for m in history if m.get("tool_calls")]
        self.assertEqual(len(calls[0]["tool_calls"]), 1)                            # only the first kept
        self.assertEqual(len([m for m in history if m.get("role") == "tool"]), 1)   # and only it answered

    def test_a_provider_that_refuses_required_is_asked_unforced(self):
        class Bad(Exception):
            status_code = 400
        out, choices = self._run([Bad("tool_choice required is not supported"), _reply('{"answer": "6"}')])
        self.assertEqual((out["answer"], choices), ("6", ["required", "auto"]))


class SolverPrompt(unittest.TestCase):
    def test_a_solver_given_the_calculator_is_told_no_code_runs(self):
        """Llama 3.x's template adds "Environment: ipython" when tools are passed: it wrote programs and then
        nothing (probe 2026-11-19: 0/5 usable; 5/5 with this line). Every solve that offers the calculator says so."""
        from core.pipeline import stages
        seen = []

        def fake(role, model, system, user, **kw):
            seen.append((system, kw.get("tools")))
            return {"working": "n = 2", "final_answer": "2", "unit": ""}
        with mock.patch.object(models, "ask_json", fake):
            stages._solve("meta-llama/llama-3.3-70b-instruct", "How many?")
        system, tools = seen[0]
        self.assertIs(tools, models.CALC_TOOL)
        self.assertIn("NO Python interpreter", system)
        self.assertIn("calculate function", system)


if __name__ == "__main__":
    unittest.main()
