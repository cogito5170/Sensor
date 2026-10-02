"""PC-09 (baseline#3 CMD-S9): 근거는 참조다 -- 상태에 지표 값을 복사하지 않는다. 값은 ref 로 찾아 본다."""
import dataclasses
import unittest

from llmsensor.state.model import Evidence
from tests.test_state import A, end, engine, mc, tc


class EvidenceIsRef(unittest.TestCase):
    def test_no_value_field(self):
        self.assertEqual([f.name for f in dataclasses.fields(Evidence)], ["ref", "level", "name"])

    def test_state_dict_has_refs_that_resolve(self):
        E = engine([mc(0, 100), tc(0, 0, 110, err=True), end()])
        d = E.current[(A, "execution_health")].to_dict()
        self.assertTrue(d["evidence"])
        for e in d["evidence"]:
            self.assertNotIn("value", e)
            self.assertIn(e["ref"], E.metrics)          # 값은 참조로 찾는다
        names = {n["name"] for n in E.explain(A, "execution_health")["evidence"]}
        self.assertIn("tool_targets", names)


if __name__ == "__main__":
    unittest.main()
