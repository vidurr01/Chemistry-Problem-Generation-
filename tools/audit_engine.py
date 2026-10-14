"""
Offline audit of the physical engine: every chain the graph walk can build (1-3 steps),
checked in code before any model is paid.

    python tools/audit_engine.py            # summary + every flag (exit 1 if any)
    python tools/audit_engine.py --pairs    # also list every linkable pair (for review)

Checks
  units      a value passed from one step to the next must arrive in the unit the next step
             reads it in (wiring never converts: L into an mL input is wrong by 1000)
  repeated   a later step asks for a value an earlier step of the same chain already states
             (the same input, or a second temperature / pressure / volume of what the story
             says is one state): the question would state two values that may contradict
  run        every pair and triple is run on sampled inputs (tests/engine_samples.py): it
             must give a finite answer of the declared kind with a unit pint can read, or
             refuse the inputs with an EngineError, never crash
"""

from __future__ import annotations

import argparse
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from core import units                                            # noqa: E402
from core.engine import physical as ph                            # noqa: E402
from core.engine.base import EngineError, links, plan_chain, roles_consistent  # noqa: E402

STATE_UNITS = {"K": "temperature", "atm": "pressure", "L": "volume", "°C": "temperature"}

# Units of extra output fields ("gives") that are not also an input of the same step.
GIVES_UNITS = {
    "T": "K", "T1": "K", "t1_celsius": "°C", "total_pressure": "atm", "delta_s": "J K⁻¹ mol⁻¹",
    "molar_mass": "g mol⁻¹", "atoms_per_formula": "", "water_mass": "g", "eq_amounts": "mol",
    "balanced_equation": "", "n_A": "mol", "n_B": "mol", "coef_A": "", "coef_B": "",
    "reactant_A": "", "reactant_B": "", "unpaired_electrons": "", "orbit_radius_m": "m",
    "Tc": "K", "Pc": "atm", "Vc": "L mol⁻¹", "acid_moles": "mol", "salt_moles": "mol",
    "temperature": "K", "average_life": "s", "max_speed": "m s⁻¹", "empirical_mass": "g mol⁻¹",
    "coefficient": "", "sum_of_coefficients": "", "lower_level": "", "electrons": "", "n": "",
    "atoms_per_cell": "", "density": "g mL⁻¹", "solute_molar_mass": "g mol⁻¹", "delta_h": "kJ mol⁻¹",
    "Kf": "K kg mol⁻¹", "Kb": "K kg mol⁻¹", "gas_volume": "L", "P": "atm", "V": "L",
}
# Inputs read as a plain number whatever unit the constant carries (K₂/K₁, k₂/k₁ ratios).
UNITLESS_OK = {"equilibrium_constant", "rate_constant"}


def _expected():
    """(earlier tx, later tx, input key) -> why the later step rightly asks again: it is a
    different thing of the same kind (another reaction, solution, state or substance)."""
    e = {}

    def add(earlier, later, key, why):
        for a in earlier:
            for b in later:
                e[(a, b, key)] = why
    add((11, 12), (13, 151, 27), "balanced_equation", "a second reaction, using the first one's product")
    add((152, 153, 154, 160), (154, 155, 157), "balanced_equation", "the reaction changed by step 156")
    add((103,), (104, 105, 108), "T", "another state of the same gas")
    add((103,), (104, 108), "P", "another state of the same gas")
    add((113, 135, 154), (132,), "T", "ΔG asked at another temperature")
    add((125, 87), (129,), "T", "the surroundings' temperature, not the gas's")
    add((330,), (240, 265, 329), "T", "another solution at its own temperature")
    add((265, 329, 330), (262, 263, 265, 329, 330), "vant_hoff_factor", "another solute (isotonic solution)")
    titr = (35, 36, 40, 42, 43)
    add(titr, titr, "volume", "another solution (titrant and titrated)")
    add((34,), (41,), "equivalent_mass", "the reagent's and the sample's")
    add((32,), (151,), "species_asked", "a different question about another species")
    add((2,), (1,), "molar_mass", "another substance (step 341 is ethanol)")
    add((234,), (0,), "molar_mass", "the metal of cell 2 (step 235)")
    add((335,), (234,), "molar_mass", "the substance of the second cell")
    add((335,), (234,), "electrons", "the substance of the second cell")
    add((84, 85, 86, 87), (125, 84, 85, 86, 87), "new_volume", "final state of a later process")
    add((84, 85, 86, 87), (125, 84, 85, 86, 87), "new_temperature", "final state of a later process")
    add((84, 85, 86, 87), (84, 85, 86, 87), "t2_celsius", "final state of a later process")
    add((19,), (20,), "density", "the diluted or mixed solution (step 23/24)")
    add((160,), (155,), "total_pressure", "the pressure at the new temperature (step 163)")
    return e


EXPECTED = _expected()


def output_unit(step, field):
    if field == step.answer:
        return None if callable(step.unit) else step.unit
    for p in step.needs:
        if p.key == field:
            return p.unit
    return GIVES_UNITS.get(field, "?")


def same_unit(u1, u2) -> bool:
    if (u1 or "") == (u2 or ""):
        return True
    try:
        return abs(units.convert(1.0, u1 or "", u2 or "") - 1.0) < 1e-9
    except Exception:  # noqa: BLE001
        return False


def _params(step):
    out = {p.key: p for p in step.needs}
    for d in step.derive:
        for p in d.params:
            out.setdefault(p.key, p)
    return out


def chains(max_len=3):
    """Every chain of 1..max_len steps the walk can build: consecutive steps share a graph
    node (dst -> src), link, keep roles consistent and plan."""
    S = list(ph.STEPS.values())
    nxt = {s.tx: [b for b in S if b is not s and s.dst == b.src and links(s, b, ph.BRIDGES)] for s in S}
    out = []

    def grow(chain):
        try:
            plan = plan_chain(chain)
        except EngineError:
            return
        out.append((chain, plan))
        if len(chain) < max_len:
            for b in nxt[chain[-1].tx]:
                if b not in chain and roles_consistent(chain + [b]):
                    grow(chain + [b])
    for s in S:
        grow([s])
    return out


def check_chain(chain, plan):
    flags = []
    for i in range(1, len(chain)):
        a, b, w = chain[i - 1], chain[i], plan.wiring[i]
        params = _params(b)
        for key, (src, ref) in w.items():
            if src != "prev":
                continue
            ou, p = output_unit(a, ref), params.get(key)
            iu = p.unit if p else None
            if ou == "?":
                flags.append(("units", f"{key}: unit of {a.tx}'s output '{ref}' unknown"))
            elif ou is None or p is None:
                continue
            elif not same_unit(ou, iu) and not (key in UNITLESS_OK and not iu):
                flags.append(("units", f"{key}: {a.tx} gives [{ou}], {b.tx} reads [{iu}]"))
    # a value asked again: same input key, or another state variable of a step that is wired on
    for qk, g in plan.givens.items():
        later = min(g.steps)
        if later == 0:
            continue
        for j in range(later):
            earlier = chain[j]
            same = [p for p in earlier.needs if p.key == g.param.key and p.kind not in ("choice",)]
            if (earlier.tx, chain[later].tx, g.param.key) in EXPECTED:
                continue
            if same and not g.param.key.startswith(("which", "count")):
                flags.append(("repeated", f"'{g.param.key}' stated for step {j + 1} ({earlier.tx}) "
                                          f"and again for step {later + 1} ({chain[later].tx})"))
    return flags


def run_chain_samples(chain, plan, n=20, seed=0):
    """Run a chain on n sampled inputs. Returns (ok, refused, problems): a problem is a crash
    that is not an EngineError, a non-finite or wrongly typed answer, or an answer unit pint
    cannot read."""
    import math
    import random
    from core.engine.base import run_chain
    from tests.engine_samples import sample_values
    rng = random.Random(seed)
    ok = refused = 0
    problems = []
    for _ in range(n):
        try:
            values = sample_values(plan, rng)
            r = run_chain(plan, values)
        except EngineError:
            refused += 1
            continue
        except Exception as e:  # noqa: BLE001
            problems.append(f"crash: {type(e).__name__}: {str(e)[:120]}")
            continue
        ok += 1
        a = r.answer
        nums = a if isinstance(a, (list, tuple)) else [a]
        for x in nums:
            if isinstance(x, (int, float)) and not isinstance(x, bool) and not math.isfinite(x):
                problems.append(f"non-finite answer {x!r}")
        if not isinstance(r.unit, str):
            problems.append(f"unit is not text: {r.unit!r}")
        elif r.unit and units.parse(r.unit) is None:
            problems.append(f"answer unit {r.unit!r} cannot be read")
        for t in r.traps:
            if t["wrong_answer"] == a:
                problems.append(f"trap {t['id']} gives the right answer")
    return ok, refused, problems


def describe(chain, plan):
    lines = [" -> ".join(str(s.tx) for s in chain) + "   " + " => ".join(s.asks[:40] for s in chain)]
    for i in range(1, len(chain)):
        w = plan.wiring[i]
        wired = ", ".join(f"{k}<-{ref}" for k, (s, ref) in w.items() if s == "prev")
        given = "; ".join(f"{g.param.desc} [{g.param.unit}]" for qk, g in plan.givens.items() if min(g.steps) == i)
        lines.append(f"      step {i + 1} wired: {wired} | states: {given}")
    return "\n".join(lines)


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--pairs", action="store_true")
    ap.add_argument("--run", action="store_true", help="also run every chain on sampled inputs")
    args = ap.parse_args()
    all_chains = chains()
    flags = []
    for chain, plan in all_chains:
        for kind, msg in check_chain(chain, plan):
            flags.append((kind, chain, msg))
    never = []
    if args.run:
        for chain, plan in all_chains:
            ok, refused, problems = run_chain_samples(chain, plan)
            for msg in dict.fromkeys(problems):
                flags.append(("run", chain, msg))
            if ok == 0:
                never.append((chain, refused))
    by_len = {n: sum(1 for c, _ in all_chains if len(c) == n) for n in (1, 2, 3)}
    print(f"steps {len(ph.STEPS)}, chains: {by_len[1]} single, {by_len[2]} pairs, {by_len[3]} triples; "
          f"flags {len(flags)}")
    seen = set()
    if args.run:
        print(f"chains that refused all 20 sampled inputs: {len(never)}")
        for chain, refused in never:
            print(f"  {'->'.join(str(s.tx) for s in chain)}")
    for kind in ("units", "repeated", "run"):
        fl = [f for f in flags if f[0] == kind]
        print(f"\n== {kind}: {len(fl)}")
        for _, chain, msg in fl:
            key = (kind, msg)
            if key in seen:
                continue
            seen.add(key)
            print(f"  {'->'.join(str(s.tx) for s in chain):<14} {msg}")
    if args.pairs:
        print("\n== pairs")
        for chain, plan in all_chains:
            if len(chain) == 2:
                print(describe(chain, plan))
    return 1 if flags else 0


if __name__ == "__main__":
    sys.exit(main())
