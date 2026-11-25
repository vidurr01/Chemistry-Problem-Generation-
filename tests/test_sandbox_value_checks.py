"""Values a program computes in plain Python are checked (sandbox.check_value), and the number step aims the answer
into answer_range (sandbox._aim). Case: Cu/Ag co-deposition, 2026-11-25 (3.05 A, 126 min, 6.62 g: Q_Ag < 0)."""

import unittest

from core.engine import sandbox

CU_AG = '''
def solve():
    Q = current * time_min * 60
    a, b = 63.5 / (2 * 96485), 107.9 / 96485
    Q_Ag = (m_total - a * Q) / (b - a)
    Q_Cu = Q - Q_Ag
    m_check = step_234(charge=Q, molar_mass=63.5, electrons=2)["mass"]
    return Q_Cu * 3.5 + 0 * m_check
'''


class ValueKind(unittest.TestCase):
    def test_kinds(self):
        for name, kind in [("Q_Ag", "nonneg"), ("q_Cu", "nonneg"), ("moles_HCl", "nonneg"), ("n_total", "nonneg"),
                           ("V2", "nonneg"), ("mass_left", "nonneg"), ("T2", "temperature"), ("alpha", "fraction"),
                           ("fraction_forward", "fraction"), ("density_alpha", "nonneg"),
                           ("Q", None), ("q_rev", None), ("dH", None), ("delta_n", None), ("n_diff", None),
                           ("slope", None), ("E_cell", None), ("radius_alpha", None)]:
            self.assertEqual(sandbox.value_kind(name), kind, name)


class PlainPythonValues(unittest.TestCase):
    def test_impossible_split_refused(self):
        run = sandbox._evaluate(CU_AG, [234], preset={"current": 3.05, "time_min": 126, "m_total": 6.62})
        self.assertFalse(run["ok"])
        self.assertIn("Q_Ag", run["error"])

    def test_possible_split_accepted(self):
        run = sandbox._evaluate(CU_AG, [234], preset={"current": 3.05, "time_min": 126, "m_total": 12.0})
        self.assertTrue(run["ok"], run.get("error"))


class AimAnswer(unittest.TestCase):
    RANGES = {"current": (1.0, 5.0, False), "time_min": (30.0, 180.0, False), "m_total": (2.0, 12.0, False)}

    def _feasible(self, v):
        q = v["current"] * v["time_min"] * 60
        return q * 63.5 / (2 * 96485) <= v["m_total"] <= q * 107.9 / 96485

    def test_values_in_range_and_possible(self):
        for seed in range(5):
            out = sandbox._search(sandbox.clean_code(CU_AG), [234], self.RANGES, {}, answer_range=(50000, 120000),
                                  tries=200, min_traps=0, seed=seed, deadline_s=60)
            self.assertTrue(out["ok"], out)
            self.assertTrue(self._feasible(out["values"]), out["values"])
            self.assertTrue(50000 <= out["run"]["answer"] <= 120000)


if __name__ == "__main__":
    unittest.main()
