"""Saved wrong outputs, replayed through the stage they went wrong in (offline stages only:
grade, parse, program). Model stages run with: python -m tools.regress run --live

    python -m unittest tests.test_regressions
    REGRESS_STAGE=grade python -m unittest tests.test_regressions      # one stage only

A "fixed" case that fails again fails this suite. An "open" case that still fails is skipped
(the bug is known); one that now passes fails the suite until it is marked fixed, so a fix is
never left unrecorded.
"""

import os
import unittest

from tools import regress


class Regressions(unittest.TestCase):
    def test_cases_are_well_formed(self):
        for c in regress.load_cases():
            for key in ("id", "stage", "input", "expect", "what_went_wrong"):
                self.assertIn(key, c, c["_path"])
            self.assertIn(c.get("status", "open"), ("open", "fixed"), c["_path"])


def _make(case):
    def test(self):
        r = regress.replay(case)
        if case.get("status") == "fixed":
            self.assertTrue(r["passed"], f"{case['_path']} regressed: {r['detail']}")
        elif r["passed"]:
            self.fail(f"{case['_path']} now passes: mark it fixed (python -m tools.regress mark {case['id']} fixed)")
        else:
            self.skipTest(f"open: {r['detail'][:120]}")
    return test


for _c in regress.load_cases(os.environ.get("REGRESS_STAGE") or None):
    if _c["stage"] in regress.OFFLINE:
        setattr(Regressions, f"test_{_c['stage']}__{_c['id'].replace('-', '_')}", _make(_c))
