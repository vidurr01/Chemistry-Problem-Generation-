"""
llm.py — shared helpers for the entry points, tools and calibration scripts:
loading .env, parsing JSON from model replies, writing JSON files atomically,
which API errors are worth retrying, the retry loop itself, and a JSON call that
also retries empty or unparseable replies.
"""

import json
import os
import re
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent


def load_env(path=None) -> None:
    """Load KEY=VALUE lines from the repo-root .env into os.environ (existing variables
    win). Blank lines and # comments are skipped; surrounding quotes are stripped."""
    path = Path(path) if path else ROOT / ".env"
    if not path.exists():
        return
    with open(path, encoding="utf-8") as f:
        for line in f:
            line = line.strip()
            if line and not line.startswith("#") and "=" in line:
                k, v = line.split("=", 1)
                os.environ.setdefault(k.strip(), v.strip().strip('"').strip("'"))


def _first_json_object(text: str) -> str:
    """The first balanced {...} block in text, ignoring braces inside strings, so prose
    or a second object after the JSON does not break parsing."""
    start = text.find("{")
    if start == -1:
        return ""
    depth, in_str, escape = 0, False, False
    for i in range(start, len(text)):
        ch = text[i]
        if in_str:
            if escape:
                escape = False
            elif ch == "\\":
                escape = True
            elif ch == '"':
                in_str = False
        elif ch == '"':
            in_str = True
        elif ch == "{":
            depth += 1
        elif ch == "}":
            depth -= 1
            if depth == 0:
                return text[start:i + 1]
    return ""


def _escape_inner_quotes(text: str) -> str:
    """Escape quotes a model left unescaped inside a string value ('the "crossed Cannizzaro"
    reaction'). Inside a string, a quote ends it only if the next non-space character can
    follow a JSON string (, } ] :); any other quote is part of the text."""
    out, in_str, escape, i = [], False, False, 0
    while i < len(text):
        ch = text[i]
        if in_str:
            if escape:
                escape = False
            elif ch == "\\":
                escape = True
            elif ch == '"':
                j = i + 1
                while j < len(text) and text[j] in " \t\r\n":
                    j += 1
                if j >= len(text) or text[j] in ",}]:":
                    in_str = False
                else:
                    out.append('\\"')
                    i += 1
                    continue
        elif ch == '"':
            in_str = True
        out.append(ch)
        i += 1
    return "".join(out)


def parse_json(content) -> dict:
    """A JSON object from a model reply. Tolerates ```json fences, prose before or after
    the object, a second object, and a single-element list. Raises ValueError (or
    json.JSONDecodeError, a subclass) when there is no object to be had."""
    text = (content if isinstance(content, str) else str(content or "")).strip()
    text = re.sub(r"^```(?:json)?\s*", "", text, flags=re.IGNORECASE).strip()
    text = re.sub(r"\s*```$", "", text).strip()
    try:
        obj = json.loads(text)
    except json.JSONDecodeError:
        obj = None
        # the object as written; then with quotes a model left unescaped inside the text
        for source in (text, _escape_inner_quotes(text)):
            block = _first_json_object(source)
            if not block:
                continue
            for attempt in (
                    lambda b: json.loads(b),
                    # LaTeX in a string (\ce, \Delta) is not a JSON escape: keep valid escapes
                    # (\" \\ \n \u...) and double any other backslash
                    lambda b: json.loads(re.sub(r'\\(["\\/bfnrtu])|\\',
                                                lambda m: m.group(0) if m.group(1) else "\\\\", b)),
                    # raw line breaks / tabs inside a string
                    lambda b: json.loads(b, strict=False),
                    # both
                    lambda b: json.loads(re.sub(r'\\(["\\/bfnrtu])|\\',
                                                lambda m: m.group(0) if m.group(1) else "\\\\", b), strict=False)):
                try:
                    obj = attempt(block)
                    break
                except json.JSONDecodeError:
                    continue
            if obj is not None:
                break
        if obj is None:
            raise ValueError(f"Could not parse JSON from model output: {text[:200]!r}")
    if isinstance(obj, list):
        obj = next((x for x in obj if isinstance(x, dict)), None)
    if not isinstance(obj, dict):
        raise ValueError(f"Expected a JSON object, got {type(obj).__name__}")
    return obj


_TRUE_WORDS = {"true", "yes", "y", "1", "pass", "correct"}
_FALSE_WORDS = {"false", "no", "n", "0", "fail", "incorrect", "none", "null", ""}


def as_bool(value, default: bool = False) -> bool:
    """A boolean from model JSON. Models sometimes write booleans as strings, and
    bool("false") is True in Python — so "false"/"no"/"0" must map to False here.
    Anything unrecognised gives `default`."""
    if isinstance(value, bool):
        return value
    if value is None:
        return default
    if isinstance(value, (int, float)):
        return value != 0
    word = str(value).strip().lower()
    if word in _TRUE_WORDS:
        return True
    if word in _FALSE_WORDS:
        return False
    return default


def as_number(value):
    """A number from model JSON ("85", "85%", 85.0), or None if it is not one."""
    if isinstance(value, bool):
        return None
    if isinstance(value, (int, float)):
        return value
    try:
        return float(str(value).strip().rstrip("%").strip())
    except (TypeError, ValueError):
        return None


def write_json_atomic(path, data, **dump_kwargs) -> None:
    """json.dump via a temp file + os.replace, so an interrupted write never leaves a
    truncated file. dump_kwargs go to json.dump (default indent=2)."""
    path = str(path)
    os.makedirs(os.path.dirname(os.path.abspath(path)), exist_ok=True)
    dump_kwargs.setdefault("indent", 2)
    tmp = path + ".tmp"
    with open(tmp, "w", encoding="utf-8") as f:
        json.dump(data, f, **dump_kwargs)
    os.replace(tmp, path)

try:
    import openai
    _TRANSIENT_TYPES = (openai.RateLimitError, openai.APITimeoutError,
                        openai.APIConnectionError, openai.InternalServerError)
except Exception:          # openai missing or too old: fall back to message matching
    _TRANSIENT_TYPES = ()

# HTTP statuses that a later attempt can succeed on (rate limits, overload, gateways).
TRANSIENT_STATUS = {408, 409, 425, 429, 500, 502, 503, 504, 520, 522, 524, 529}
_STATUS_IN_MESSAGE = re.compile(r"(?:error code|status(?: code)?)\s*:?\s*(\d{3})", re.IGNORECASE)
_TRANSIENT_WORDS = ("rate limit", "rate_limit", "timed out", "timeout", "overloaded",
                    "temporarily unavailable", "connection reset", "connection error",
                    "connection aborted", "remote end closed", "bad gateway")


def is_rate_limit(exc) -> bool:
    status = getattr(exc, "status_code", None)
    msg = str(exc).lower()
    return status == 429 or "429" in msg or "rate limit" in msg or "rate_limit" in msg


def is_transient(exc) -> bool:
    """True for errors a retry can fix (429, 5xx, timeouts, dropped connections).
    False for ones it cannot (400 bad request, 401/403 key or spend limit, 404 model)."""
    if _TRANSIENT_TYPES and isinstance(exc, _TRANSIENT_TYPES):
        return True
    status = getattr(exc, "status_code", None)
    if status is None:
        m = _STATUS_IN_MESSAGE.search(str(exc))
        status = int(m.group(1)) if m else None
    if status is not None:
        return status in TRANSIENT_STATUS
    msg = str(exc).lower()
    return any(w in msg for w in _TRANSIENT_WORDS)


def call_with_retry(fn, retries: int = 5, base_wait: float = 10, label: str = "API"):
    """Call fn(); on a transient error wait base_wait * 2**attempt and try again.
    Non-transient errors, and the last transient one, are raised."""
    for attempt in range(retries):
        try:
            return fn()
        except Exception as e:
            if not is_transient(e) or attempt == retries - 1:
                raise
            wait = base_wait * (2 ** attempt)
            print(f"    [{label}] {type(e).__name__}: {str(e)[:90]} — retrying in {wait:.0f}s "
                  f"({attempt + 1}/{retries})")
            time.sleep(wait)


UNPARSEABLE_LOG = os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", "outputs",
                               "unparseable_replies.jsonl")


def _log_unparseable(label, resp, content, err):
    """Keep every reply that could not be read, whole, so the cause is seen and not guessed."""
    try:
        choice = resp.choices[0] if getattr(resp, "choices", None) else None
        rec = {"at": time.strftime("%Y-%m-%dT%H:%M:%S"), "label": label,
               "model": getattr(resp, "model", None),
               "finish_reason": getattr(choice, "finish_reason", None),
               "error": str(err)[:300], "content": content}
        os.makedirs(os.path.dirname(UNPARSEABLE_LOG), exist_ok=True)
        with open(UNPARSEABLE_LOG, "a", encoding="utf-8") as f:
            f.write(json.dumps(rec, ensure_ascii=False, default=str) + "\n")
    except Exception:  # noqa: BLE001 - logging must never break a call
        pass


def call_json(create, parse, retries: int = 5, parse_retries: int = 2, base_wait: float = 10,
              label: str = "API"):
    """create() makes one chat completion; returns parse(reply text). Transient API
    errors are retried by call_with_retry; an empty or unparseable reply (usually a
    truncated or fenced answer) is asked for again up to parse_retries times."""
    for i in range(parse_retries + 1):
        resp = call_with_retry(create, retries=retries, base_wait=base_wait, label=label)
        content = resp.choices[0].message.content if getattr(resp, "choices", None) else None
        try:
            if not content or not str(content).strip():
                raise ValueError("empty completion")
            return parse(content)
        except (ValueError, json.JSONDecodeError) as e:
            _log_unparseable(label, resp, content, e)
            if i == parse_retries:
                raise
            print(f"    [{label}] unusable reply ({str(e)[:80]}) — asking again ({i + 1}/{parse_retries})")
