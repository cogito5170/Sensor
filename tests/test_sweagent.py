import gzip
import json
import os
import tempfile
import unittest

from llmsensor.adapters.sweagent import from_sweagent
from eval.swe_lite import auroc_rank, auroc_trap, split_of


class Adapter(unittest.TestCase):
    def test_traj(self):
        d = {"trajectory": [
            {"action": "python reproduce.py", "observation": "Traceback (most recent call last):\n  x", "thought": "a"},
            {"action": "edit 1:1\nfix\nend_of_edit", "observation": "[File: a.py (1 lines total)]", "thought": "b"},
            {"action": "submit", "observation": "diff --git", "thought": "고쳤습니다. 제출합니다."}],
             "history": [{"role": "system", "content": "s"}, {"role": "user", "content": "demo", "is_demo": True},
                         {"role": "user", "content": "이슈 본문 1234"}],
             "info": {"exit_status": "submitted", "submission": "diff",
                      "model_stats": {"tokens_sent": 900, "tokens_received": 100, "api_calls": 3}}}
        with tempfile.TemporaryDirectory() as tmp:
            p = os.path.join(tmp, "astropy__astropy-1.traj.gz")
            with gzip.open(p, "wt", encoding="utf-8") as f:
                json.dump(d, f)
            t = from_sweagent(p)
        self.assertEqual((t.cls, t.tokens, t.prompt), ("astropy", 1000, "이슈 본문 1234"))
        self.assertEqual([c.ok for c in t.calls], [False, True, True])
        self.assertEqual(t.answer, "고쳤습니다. 제출합니다.")
        self.assertEqual(t.meta["instance_id"], "astropy__astropy-1")


class Metrics(unittest.TestCase):
    def test_auroc_two_ways_agree(self):
        import random
        rng = random.Random(1)
        for _ in range(20):
            y = [rng.random() < .3 for _ in range(40)]
            if not 0 < sum(y) < 40:
                continue
            s = [round(rng.random(), 1) for _ in y]           # 동점 많이
            self.assertAlmostEqual(auroc_rank(s, y), auroc_trap(s, y), places=9)
        self.assertEqual(auroc_rank([1, 2, 3, 4], [0, 0, 1, 1]), 1.0)
        self.assertEqual(auroc_rank([1, 1, 1, 1], [0, 0, 1, 1]), 0.5)

    def test_split_is_deterministic(self):
        self.assertEqual(split_of("x__y-1"), split_of("x__y-1"))
        ids = [f"r__r-{i}" for i in range(400)]
        self.assertTrue(150 < sum(split_of(i) == "fit" for i in ids) < 250)
