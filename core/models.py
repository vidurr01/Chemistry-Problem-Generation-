"""
Model roster, the router and the one call helper every pipeline stage uses.

OpenRouter first; airouter.in once OpenRouter runs out of credit (see the Router section).
No model checks output from its own family: Gemini designs, writes, refines and words the
readable solution; DeepSeek extracts; GPT-6 Luna writes the solving program; the ladder (Meta,
Z.ai, OpenAI) solves; Claude diagnoses; Jev (TypeSafe) judges fit, level and coherence. One overlap
is known: Luna writes the solving program and is also the ladder's top step.
"""

from __future__ import annotations

import os
import threading

from core.llm import _log_unparseable, call_json, call_with_retry, load_env, parse_json
import ast as _ast
import json as _json
import math as _math
import operator as _mathop

load_env()

# ── Roster ───────────────────────────────────────────────────────────────────
GENERATOR = "google/gemini-3.7-flash"                 # picks inputs, writes stems and clarification hints
# The DESIGN step (the one creative step: which real system joins the formulas, through which hidden
# link, with which trap) decides whether a question is JEE Advanced, so it gets the strongest model of a
# family that only makes questions (never judges): Google's Pro model, pinned for the paper, thinking long.
# Cheaper designers failed on the stage runs of 2026-11-17: Gemini 3.8 Flash gave a JEE Main design
# (polonium density -> radius) and an impossible one (N2O4 at T = 1/R ~ 12 K, a volume with no K given);
# Kimi K2.6 ignored its thinking budget, and with thinking off gave a self-contradictory design.
DESIGNER = "google/gemini-3.1-pro-preview"
# The designer's thinking has a fixed budget, inside the reply's limit: an effort level let Flash think
# until the reply was cut off with no design ("high": 16000 tokens, $0.06; "medium": 8000, $0.03).
DESIGNER_THINKING = 3000    # tokens of thinking; 3500 more for the design text (Gemini Pro writes long designs:
                            # 2000 cut one off, 2026-11-17); at most ~8 cents a design
DESIGNER_EFFORT = f"{DESIGNER_THINKING} thinking tokens"     # shown by tools/step_by_step.py
# On airouter Gemini Pro ignored the token budget on the design prompt (thought ~4800 and ~6300 tokens against
# 3000; both designs cut off, $0.14, 2026-11-17), so there it gets an effort level instead (airouter's own
# reasoning_effort) and a reply cap. OpenRouter keeps the token budget, which it honours.
AIROUTER_DESIGNER_EFFORT = "medium"
AIROUTER_DESIGN_CAP = 6500
# Gemini 3 models ignore numeric thinking budgets and think at their own level ("high" by default): three
# designs were cut off at 6500 tokens after ~6000 of thinking ($0.22, 2026-11-17). So a Gemini 3 designer
# gets no budget, its default level (or GEMINI3_DESIGN_LEVEL: "low"/"high") and a cap with room to finish;
# only the tokens used are paid.
GEMINI3_DESIGN_LEVEL = "low"    # the cheaper level (2026-11-17); "high" if its designs are too shallow
GEMINI3_DESIGN_CAP = 8000
REFINER = "google/gemini-3.8-flash"                   # too easy: reads the solvers' working, redesigns inputs or rewrites
EXTRACTOR = "deepseek/deepseek-v4-flash-0731"          # chemistry gate: lists the facts a stem states
# No mismatch verifier since 2026-11-19 (the author: too weak; it called a right key wrong). Ladder answers are
# graded by code only. The same model still checks the written solution after acceptance:
SOLUTION_CHECKER = "anthropic/claude-haiku-5.5"
# Question-first refinement: Jev (TypeSafe AI) decides WHY a too-easy question was easy (one of
# core/pipeline/refine.CASES); the generator then rewrites it. Served by OpenRouter on its Decisions
# API (not /chat/completions), with the same OPENROUTER_KEY.
JEV_MODEL = "typesafe/jev-1.14"
JEV_URL = "https://openrouter.ai/api/alpha/decisions"
JEV_USD_PER_INPUT_TOKEN = 0.042e-6                    # $0.042 per million input tokens, output free
# Coder ("coder 2"): GPT-6 Luna writes the program that solves the question from its blanks, before any
# number is chosen (8/8 real JEE Advanced questions, tools/calibrate_coder.py). The numbers are picked by
# code, not a model (qf_numbers.pick_numbers): there is no number coder any more. Codestral made the
# basic errors of every run of 2026-11-16 (undefined names, find() misused, syntax errors, wrong units).
CODER = "openai/gpt-6-luna"
CODER_FALLBACKS = ()
# No escalation: the coder is already the strongest we use (CODER_STRONG = None).
CODER_STRONG = None


def coder_tokens(model: str) -> int:
    """A program is 20-40 lines: 4000 tokens caps a non-thinking coder's runaway reply (Codestral
    repeated one nested call until 12000); a thinking model needs room to think first."""
    return 4000 if model.startswith("mistralai/") else 12000
SOLUTION_WRITER = "google/gemini-3.8-flash"   # readable solution of an accepted question: it only words the
# engine's numbers, checked by code and the verifier; Google (it generates, never judges). It was GPT-6 Luna,
# also the coder and the ladder's top solver: one model in too many places.
# Difficulty ladder, weakest first (flow.judge). Calibrated on real JEE papers (2026-10-14;
# calibration/ladder_separation.py; hard Mains = top third by calculated_difficulty):
#                       Mains easy/medium  Mains hard  Advanced   $ per question
#   phi-4                    fails 14 %     fails 53 %  fails 53 %   0.00017   <- separates; decides accept
#   glm-5.3-flash            fails 14 %     fails 11 %  fails 29 %   0.00020   <- difficulty label
#   gpt-6-luna               fails  7 %     fails  0 %  fails  8 %   0.00057   <- difficulty label
# Bottom-step candidates measured: Llama 3.3 70B (29 % / 66 %, $0.00100), Phi-4 solves 21
# questions Llama 3.3 misses and Llama 8 Phi-4 misses (p = 0.02); GLM beats Phi-4 29 to 9
# (p = 0.002). Llama 4 Maverick (14 % / 28 %), Llama 4 Scout (43 % / 54 %) and GLM do not
# separate easy from hard; Granite 4.2 8B separates but refuses to answer solvable questions.
# A question is accepted when the first step fails it; the step that first solves it (or
# none) is its difficulty label. Later steps are called only after the earlier ones fail.
# 2026-11-17: phi-4 is not on airouter.in (UPI billing; OpenRouter needs an international card), so the
# bottom step is Llama 3.3 70B, the only other measured model that separates (gap 37.6 points against
# phi-4's 38.7), at the price of failing twice as many easy Mains questions (29 % against 14 %): more
# easy questions reach the GLM label. Meta is used nowhere else. Calibrated on OpenRouter's host; airouter
# serves the same open weights (meta/llama-3.3-70b).
# 2026-11-19: bottom step Granite 4.2 8B (the author: Llama "never a good option"). Measured with the forced
# calculator (calibration/anchor_calibration.py --council, ladder_separation.py): fails easy Mains 32.1 %,
# Advanced-level 52.2 % (gap 20.1), $0.00025 a question, 1 no-answer in 95; Llama never called the calculator unforced,
# wrote programs, replied empty, and failed 54 % of easy Mains. IBM is used nowhere else.
LADDER = [
    ("granite-4.2-8b", "ibm-granite/granite-4.2-8b"),          # IBM
    ("glm-5.3-flash", "z-ai/glm-5.3-flash"),                   # Z.ai
    ("minimax-m3", "minimax/minimax-m3"),                      # MiniMax
]
# Top step MiniMax M3 since 2026-11-19 (was GPT-6 Luna, the same model as the coder that writes the key, so its
# "solve" was the key agreeing with itself). 10 real Advanced physical numericals, forced calculator: MiniMax 9/10
# at Rs 1.05 a question, Qwen3.5-35B-A3B 9/10 at Rs 3.22; MiniMax's miss was 2022P2_Q1 (3.2 % of candidates).
COUNCIL = LADDER            # the solvers, in ladder order (council_eval.py and older code read COUNCIL)
COUNCIL_REASONING_EFFORT = "medium"
# First step that solves an accepted question -> its label. "hard_advanced" only when even the top step fails
# (the author, 2026-11-19: GLM failing and the top step solving is medium Advanced, not hard).
DIFFICULTY_LABELS = {
    "glm-5.3-flash": "advanced",
    "minimax-m3": "advanced_medium",
    None: "hard_advanced",
}

ROSTER = {"generator": GENERATOR, "designer": DESIGNER, "refiner": REFINER, "extractor": EXTRACTOR, "coder": CODER,
          "coder_strong": CODER_STRONG, "refine_decider": JEV_MODEL,
          "solution_writer": SOLUTION_WRITER, "solution_checker": SOLUTION_CHECKER, "ladder": [slug for _, slug in LADDER]}


# ── Router ───────────────────────────────────────────────────────────────────
# OpenRouter first (fast); airouter.in (UPI billing) when OpenRouter has no key or runs out of credit in this
# run (HTTP 402), from then on for the rest of the run. Models airouter does not carry always go to
# OpenRouter. The roster keeps OpenRouter's model names; route_model() gives airouter's. (2026-11-17:
# OpenRouter needs an international card; airouter was 4-8x slower per call.)
ROUTERS = {"openrouter": ("OPENROUTER_KEY", "https://openrouter.ai/api/v1", "https://openrouter.ai/api/alpha/decisions"),
           "airouter": ("AIROUTER_KEY", "https://api.airouter.in/v1", "https://api.airouter.in/v1/decisions")}
AIROUTER_NAMES = {"typesafe/jev-1.14": "typesafe-ai/jev-1.14.0", "typesafe/jev-1.13": "typesafe-ai/jev-1.13.0",
                  "mistralai/codestral-2508": "mistral/codestral",
                  "meta-llama/llama-3.3-70b-instruct": "meta/llama-3.3-70b",
                  "mistralai/mistral-large-4-0": "mistral/mistral-large-4",
                  "mistralai/mistral-medium-3-5": "mistral/mistral-medium-3.5"}
AIROUTER_PREFIXES = {"z-ai/": "zai/", "mistralai/": "mistral/", "typesafe/": "typesafe-ai/"}
THINKING_OFF: set = set()       # models asked not to think when a call sets no thinking of its own
THINKING_BUDGET: dict = {}      # model -> thinking tokens, when a call sets no thinking of its own
AIROUTER_MISSING = {"microsoft/phi-4"}         # "not supported" on airouter (check_models, 2026-11-17)
# On airouter a model it lacks is served by a stand-in: Devstral (the number coder, 7/8 real JEE Advanced
# questions on OpenRouter) by Qwen3 Coder Next (Alibaba, no other role; 6/8, 1.25 tries, $0.0025 a question,
# tools/calibrate_coder.py, 2026-11-17). SERVED records which model really answered each roster model.
AIROUTER_STANDINS = {"mistralai/devstral-2512": "alibaba/qwen3-coder-next"}
SERVED: dict = {}
_OPENROUTER_OUT = threading.Event()             # set on a 402: OpenRouter has no credit left this run
_NOT_ON_OPENROUTER: set = set()                 # models OpenRouter called "not a valid model ID" this run


def _real(k: str) -> bool:
    return bool(k) and "your-" not in k


def _has(name: str) -> bool:
    return _real(os.environ.get(ROUTERS[name][0], ""))


def router(model: str | None = None) -> str:
    """Where this model's calls go now."""
    if model in AIROUTER_MISSING or not _has("airouter"):
        return "openrouter"
    if os.environ.get("LLM_ROUTER", "").strip().lower() == "airouter":
        return "airouter"                       # forced (PowerShell cannot blank a key: "" deletes it)
    if _has("openrouter") and not _OPENROUTER_OUT.is_set() and model not in _NOT_ON_OPENROUTER:
        return "openrouter"
    return "airouter"


_OUT_LOCK = threading.Lock()


def openrouter_out() -> bool:
    """A 402 from OpenRouter: the rest of this run goes to airouter, when there is one to go to. True for
    EVERY caller while airouter is available (said once): calls in flight together all get the 402, and
    returning False to all but the first made those re-raise it instead of moving to airouter."""
    if not _has("airouter"):
        return False
    with _OUT_LOCK:
        if not _OPENROUTER_OUT.is_set():
            _OPENROUTER_OUT.set()
            print("    [router] OpenRouter is out of credit: airouter.in from here on")
    return True


def route_model(model: str, where: str | None = None) -> str:
    """The model's name on the router its calls go to."""
    if (where or router(model)) != "airouter" or not model:
        return model
    if model in AIROUTER_STANDINS:
        return AIROUTER_STANDINS[model]
    if model in AIROUTER_NAMES:
        return AIROUTER_NAMES[model]
    for a, b in AIROUTER_PREFIXES.items():
        if model.startswith(a):
            return b + model[len(a):]
    return model


def api_key(model: str | None = None) -> str:
    return os.environ.get(ROUTERS[router(model)][0], "")


def key_is_set(model: str | None = None) -> bool:
    """A real key for the router this model's calls go to. (It used to say yes when ANY router had a key, so
    a model only OpenRouter serves, such as phi-4, passed with only AIROUTER_KEY set and was sent with an
    empty key.) With no model: the router a call goes to by default."""
    return _real(api_key(model))


def decisions_url(model: str | None = None) -> str:
    return ROUTERS[router(model)][2]


def _client(where: str | None = None):
    from openai import OpenAI
    where = where or router()
    # 180 s: the client's own default (10 min) let a stuck airouter call hang a run silently (2026-11-17);
    # a timeout is retried by core.llm like any transient error, and says so
    return OpenAI(api_key=os.environ.get(ROUTERS[where][0], ""), base_url=ROUTERS[where][1], timeout=180,
                  max_retries=0)


# ── Spend tracking ───────────────────────────────────────────────────────────

class Spend:
    """Tokens and cost (USD, as OpenRouter reports it) per role for this process."""

    def __init__(self):
        self._lock = threading.Lock()
        self.by_role: dict = {}

    def add(self, role: str, usage) -> None:
        if usage is None:
            return
        get = (lambda k: usage.get(k)) if isinstance(usage, dict) else (lambda k: getattr(usage, k, None))
        with self._lock:
            r = self.by_role.setdefault(role, {"calls": 0, "prompt_tokens": 0, "completion_tokens": 0, "cost": 0.0})
            r["calls"] += 1
            r["prompt_tokens"] += get("prompt_tokens") or 0
            r["completion_tokens"] += get("completion_tokens") or 0
            r["cost"] += float(get("cost") or get("total_cost") or 0.0)     # airouter: total_cost
            self._write_total()

    def _write_total(self) -> None:
        """The running total to the file named by SPEND_FILE (set by generate_questions.py for each run): a run
        killed at the driver's timeout never prints its "Spend this run" line, so its cost went uncounted."""
        path = os.environ.get("SPEND_FILE")
        if not path:
            return
        try:
            with open(path + ".tmp", "w", encoding="utf-8") as f:
                f.write(repr(self.total_cost))
            os.replace(path + ".tmp", path)
        except OSError:                              # a spend note must never break a call
            pass

    @property
    def total_cost(self) -> float:
        return sum(r["cost"] for r in self.by_role.values())

    def summary(self) -> dict:
        return {"total_cost_usd": round(self.total_cost, 5), "by_role": self.by_role}


SPEND = Spend()


# Output caps for models whose context window is smaller than a call's default cap
# (prompt + max_tokens must fit; Phi-4 has 16k in total and does not think at length).
MAX_OUTPUT_TOKENS = {"microsoft/phi-4": 8000, "meta-llama/llama-4-scout": 8000}
# Models whose providers refuse JSON mode: asked for JSON in the prompt only (parse_json reads it).
NO_JSON_MODE = {"meta-llama/llama-4-scout"}


# ── Calculator tool (given to coder programs via sandbox and to ladder models via tool-calling) ─

def _calc_pow(a, b):
    """a ** b in floating point: an integer power such as 9**9**9 built a number with hundreds of millions
    of digits and hung the tool loop (no timeout there); as a float it overflows at once."""
    return _math.pow(float(a), float(b))


def _calc_factorial(n):
    """n! for n <= 170 (171! does not fit a float); a larger n would run for a long time."""
    if not float(n).is_integer() or not 0 <= n <= 170:
        raise ValueError("factorial needs a whole number from 0 to 170")
    return float(_math.factorial(int(n)))


def _eval_calc(expr: str) -> str:
    """Safely evaluate a numeric arithmetic expression; return the result as a string."""
    _BINOPS = {_ast.Add: _mathop.add, _ast.Sub: _mathop.sub, _ast.Mult: _mathop.mul,
               _ast.Div: _mathop.truediv, _ast.Pow: _calc_pow, _ast.Mod: _mathop.mod,
               _ast.FloorDiv: _mathop.floordiv}
    _UNOPS  = {_ast.USub: _mathop.neg, _ast.UAdd: _mathop.pos}
    _FUNCS  = {"sqrt": _math.sqrt, "log": _math.log, "log10": _math.log10,
               "log2": _math.log2, "exp": _math.exp, "abs": abs,
               "sin": _math.sin, "cos": _math.cos, "tan": _math.tan,
               "asin": _math.asin, "acos": _math.acos, "atan": _math.atan,
               "atan2": _math.atan2, "sinh": _math.sinh, "cosh": _math.cosh,
               "tanh": _math.tanh, "ceil": _math.ceil, "floor": _math.floor,
               "round": round, "factorial": _calc_factorial}
    _CONSTS = {"pi": _math.pi, "e": _math.e, "inf": _math.inf, "tau": _math.tau}

    def _ev(node):
        if isinstance(node, _ast.Constant):
            if isinstance(node.value, (int, float)):
                return node.value
            raise ValueError(f"unsupported constant: {node.value!r}")
        if isinstance(node, _ast.Name):
            if node.id in _CONSTS:
                return _CONSTS[node.id]
            raise ValueError(f"unknown name: {node.id!r}")
        if isinstance(node, _ast.BinOp):
            if type(node.op) not in _BINOPS:
                raise ValueError(f"unsupported operator: {type(node.op).__name__}")
            return _BINOPS[type(node.op)](_ev(node.left), _ev(node.right))
        if isinstance(node, _ast.UnaryOp):
            if type(node.op) not in _UNOPS:
                raise ValueError(f"unsupported unary op: {type(node.op).__name__}")
            return _UNOPS[type(node.op)](_ev(node.operand))
        if isinstance(node, _ast.Call):
            if not (isinstance(node.func, _ast.Name) and node.func.id in _FUNCS):
                raise ValueError(f"unsupported call: {_ast.dump(node.func)}")
            return _FUNCS[node.func.id](*(_ev(a) for a in node.args))
        raise ValueError(f"unsupported node: {_ast.dump(node)}")

    try:
        result = _ev(_ast.parse(expr.strip(), mode="eval").body)
        if isinstance(result, float) and result == int(result) and abs(result) < 1e15:
            return str(int(result))
        return f"{result:.10g}"
    except Exception as exc:
        return f"ERROR: {exc}"


CALC_TOOL = [{
    "type": "function",
    "function": {
        "name": "calculate",
        "description": (
            "Evaluate an arithmetic expression exactly. Call this for every non-trivial "
            "arithmetic step to avoid manual errors. Returns the numeric result as a string."
        ),
        "parameters": {
            "type": "object",
            "properties": {
                "expression": {
                    "type": "string",
                    "description": (
                        "A numeric expression using numbers, +, -, *, /, ** (power), % "
                        "and functions: sqrt, log, log10, log2, exp, abs, sin, cos, tan, "
                        "asin, acos, atan, sinh, cosh, tanh, ceil, floor, round, factorial. "
                        "Constants: pi, e. No variables — only numbers and these functions."
                    )
                }
            },
            "required": ["expression"]
        }
    }
}]


TOOL_PARSE_RETRIES = 2      # an unreadable final reply after tool calls is asked for again this many times
FORMAT_NUDGES = 2           # ... after first being told, in the same conversation, what was wrong with it
# Llama 3.3 70B (the ladder's bottom step) sometimes answers a calculator-equipped prompt with a Python program in
# a code block (run of 2026-11-18, 3 times on one question): asked again from scratch it did the same each time.
FORMAT_NUDGE = ("That reply is not what was asked for. Do not write code or a program: nothing will run it. Use the "
                "calculate tool for any arithmetic you need, then reply with ONLY the JSON object, with exactly the "
                "keys the problem asked for.")
# Roles whose first turn MUST call the calculator (tool_choice "required"; later turns free). Probes of
# 2026-11-19: unforced, Llama 3.3 called it 0/5 (even when told it must), Granite 1/2, Qwen3.5 1/2, GLM 1/3; forced,
# Llama called it 5/5. The author: the calculator is a must, so it no longer depends on the model.
FORCE_FIRST_TOOL_CALL = ("council",)
EMPTY_NUDGE = ("Your last reply was empty. Reply now with ONLY the JSON object, with exactly the keys the problem "
               "asked for.")


def _ask_json_with_tools(role, model, asked_for, where, system, user,
                          max_tokens, temperature, extra, tools, holder):
    """Tool-calling loop: execute calculator calls until the model returns its final JSON."""
    _TOOL_MAP = {"calculate": lambda args: _eval_calc(args.get("expression", ""))}
    MAX_TOOL_ROUNDS = 20  # safety limit against infinite loops
    messages = [{"role": "system", "content": system}, {"role": "user", "content": user}]
    client = _client(where)
    nudges = 0
    force = role in FORCE_FIRST_TOOL_CALL         # ladder solvers: the first turn must call the calculator

    def create(choice):
        # one tool call per turn: some hosts of Llama 3.3 refuse a turn with several ("This model only supports
        # single tool-calls at once!", AkashML and CoreWeave via OpenRouter): 11 of 96 calibration questions got no
        # answer that way on 2026-11-19
        return client.chat.completions.create(model=model, messages=messages, temperature=temperature,
                                              max_tokens=max_tokens, extra_body=extra, tools=tools,
                                              tool_choice=choice, parallel_tool_calls=False)

    for _round in range(MAX_TOOL_ROUNDS):
        # each request retried on transient errors (429, 5xx, timeouts), as every other call is
        choice_now = "required" if force and _round == 0 else "auto"
        try:
            resp = call_with_retry(lambda: create(choice_now), label=role)
        except Exception as e:                     # noqa: BLE001
            if choice_now != "required" or getattr(e, "status_code", None) not in (400, 404, 422):
                raise
            # a provider that does not take tool_choice "required": the call goes on unforced, and says so
            print(f"    [{role} {asked_for.split('/')[-1]}] cannot force a calculator call "
                  f"({str(e)[:80]}); asking unforced")
            resp = call_with_retry(lambda: create("auto"), label=role)
        holder["usage"] = getattr(resp, "usage", None)
        SPEND.add(role, holder["usage"])

        choice = resp.choices[0] if getattr(resp, "choices", None) else None
        if not choice:
            raise ValueError("empty response in tool-calling loop")
        msg = choice.message
        tool_calls = getattr(msg, "tool_calls", None)

        if not tool_calls:
            # Final reply — parse as JSON
            content = getattr(msg, "content", None) or ""
            holder["reasoning"] = (getattr(msg, "reasoning", None)
                                   or (getattr(msg, "model_extra", None) or {}).get("reasoning"))
            try:
                if not str(content).strip():
                    raise ValueError(f"empty final reply after tool calls "
                                     f"(finish_reason={getattr(choice, 'finish_reason', None)})")
                return parse_json(content)
            except ValueError as e:
                _log_unparseable(role, resp, content, e)
                if nudges < FORMAT_NUDGES:
                    # said in the same conversation what was wrong: a fresh start repeated the same reply.
                    # An EMPTY reply is told too: after one nudge Llama answered with nothing, and that ended
                    # the call (run of 2026-11-19: the parked flask question was parked again)
                    nudges += 1
                    if str(content).strip():
                        messages.append({"role": "assistant", "content": content})
                    messages.append({"role": "user", "content": FORMAT_NUDGE if str(content).strip() else EMPTY_NUDGE})
                    print(f"    [{role}] reply was not the JSON asked for ({str(e)[:60]}); told so ({nudges}/{FORMAT_NUDGES})")
                    continue
                raise

        # Only the first call of a turn is kept and answered: a turn with several calls in the history fails on
        # hosts that take one call at a time (the model simply asks again for the others)
        tool_calls = list(tool_calls)[:1]

        # Append assistant tool-call turn to the conversation
        messages.append({
            "role": "assistant",
            "content": getattr(msg, "content", None),
            "tool_calls": [
                {"id": tc.id, "type": "function",
                 "function": {"name": tc.function.name,
                              "arguments": tc.function.arguments}}
                for tc in tool_calls
            ],
        })

        # Execute each tool call and return results
        for tc in tool_calls:
            fn = _TOOL_MAP.get(tc.function.name)
            if fn is None:
                result = f"ERROR: unknown tool {tc.function.name!r}"
            else:
                try:
                    result = str(fn(_json.loads(tc.function.arguments or "{}")))
                except Exception as exc:
                    result = f"ERROR: {exc}"
            messages.append({
                "role": "tool",
                "tool_call_id": tc.id,
                "content": result,
            })
        print(f"    [{role} {asked_for.split('/')[-1]}] calc tool: {len(tool_calls)} call(s) in round {_round + 1}")

    raise ValueError(f"tool-calling loop did not terminate after {MAX_TOOL_ROUNDS} rounds")


def ask_json(role: str, model: str, system: str, user: str, *, max_tokens: int = 4000,
             temperature: float = 0.2, reasoning_effort: str | None = None, fallbacks=(),
             retry_cut_off: bool = True, reasoning_tokens: int | None = None,
             tools: list | None = None) -> dict:
    """One chat call that must return a JSON object. Transient errors and unusable
    replies are retried (core.llm.call_json); token use and cost go to SPEND[role].
    If tools is provided, a tool-calling loop runs before the final JSON reply."""
    max_tokens = min(max_tokens, MAX_OUTPUT_TOKENS.get(model, max_tokens))
    asked_for, where = model, router(model)
    on_openrouter = where == "openrouter"
    extra = {"usage": {"include": True}} if on_openrouter else {}
    if fallbacks and on_openrouter:                 # OpenRouter tries these, in order, if `model` fails
        extra["models"] = [model, *fallbacks]
    model = route_model(model, where)
    SERVED.setdefault(asked_for, set()).add(f"{where}:{model}")
    if reasoning_tokens is not None:                # a fixed thinking budget inside max_tokens; 0: off
        extra["reasoning"] = {"max_tokens": reasoning_tokens} if reasoning_tokens > 0 else {"enabled": False}
    elif reasoning_effort:
        extra["reasoning"] = {"effort": reasoning_effort}
    elif asked_for in THINKING_BUDGET:
        extra["reasoning"] = {"max_tokens": THINKING_BUDGET[asked_for]}
    elif asked_for in THINKING_OFF:
        extra["reasoning"] = {"enabled": False}
    holder = {}

    def with_tools():
        # an unreadable final reply is asked again (the whole conversation, as call_json does for a plain
        # call): before, one bad reply from a ladder solver parked the question
        for i in range(TOOL_PARSE_RETRIES + 1):
            try:
                return _ask_json_with_tools(role, model, asked_for, where, system, user,
                                            max_tokens, temperature, extra, tools, holder)
            except ValueError as e:
                if i == TOOL_PARSE_RETRIES:
                    raise
                print(f"    [{role}] unusable reply ({str(e)[:80]}) — asking again ({i + 1}/{TOOL_PARSE_RETRIES})")

    def create():
        resp = _client(where).chat.completions.create(
            model=model,
            messages=[{"role": "system", "content": system}, {"role": "user", "content": user}],
            temperature=temperature,
            max_tokens=max_tokens,
            extra_body=extra,
            **({} if model in NO_JSON_MODE else {"response_format": {"type": "json_object"}}),
        )
        holder["usage"] = getattr(resp, "usage", None)
        SPEND.add(role, holder["usage"])
        msg = resp.choices[0].message if getattr(resp, "choices", None) else None
        holder["reasoning"] = (getattr(msg, "reasoning", None)
                               or (getattr(msg, "model_extra", None) or {}).get("reasoning")) if msg else None
        return resp

    try:
        # with tools too: the same 402 / missing-model switch to airouter below (tool calls skipped it)
        out = with_tools() if tools else call_json(create, parse_json, label=role, retry_cut_off=retry_cut_off)
    except Exception as e:                          # noqa: BLE001
        missing = (on_openrouter and getattr(e, "status_code", None) == 400 and _has("airouter")
                   and "not a valid model" in str(e) and asked_for not in _NOT_ON_OPENROUTER)
        if missing:                                 # a model only airouter carries (mistral/mistral-large-4)
            _NOT_ON_OPENROUTER.add(asked_for)
        if (missing or (on_openrouter and getattr(e, "status_code", None) == 402 and openrouter_out())) \
                and router(asked_for) == "airouter":
            return ask_json(role, asked_for, system, user, max_tokens=max_tokens, temperature=temperature,
                            reasoning_effort=reasoning_effort, fallbacks=fallbacks, retry_cut_off=retry_cut_off,
                            reasoning_tokens=reasoning_tokens, tools=tools)
        raise
    if holder.get("reasoning") and isinstance(out, dict):
        out["_reasoning"] = str(holder["reasoning"])        # the model's thinking, when the provider returns it
    return out
