"""eval/run_claude.py 의 캡처가 끝에 닫힘 줄을 쓰나(baseline#3 CMD-S11). claude 는 돌리지 않는다 -- 파이썬 자식 프로세스로."""
import json
import os
import sys
import tempfile
import unittest

from eval.run_claude import capture


def _run(code, timeout=30):
    with tempfile.TemporaryDirectory() as d:
        p = os.path.join(d, "s.jsonl")
        rc = capture([sys.executable, "-c", code], d, p, timeout)
        return rc, [json.loads(x) for x in open(p, encoding="utf-8")]


class Closed(unittest.TestCase):
    def test_last_line_is_closed_with_returncode(self):
        rc, rows = _run('import json;print(json.dumps({"type":"result"}));import sys;sys.exit(3)')
        self.assertEqual(rc, 3)
        self.assertEqual(rows[0]["line"], {"type": "result"})
        self.assertEqual((rows[-1]["closed"], rows[-1]["returncode"]), (True, 3))
        self.assertGreaterEqual(rows[-1]["_t"], rows[0]["_t"])

    def test_closed_line_after_non_json_output(self):
        rc, rows = _run('print("not json");import sys;sys.exit(1)')
        self.assertEqual(rows[0]["raw"], "not json")
        self.assertEqual((rows[-1]["closed"], rows[-1]["returncode"], rc), (True, 1, 1))
        self.assertEqual(sum(1 for r in rows if r.get("closed")), 1)
    # 알려 둘 한계(원래 동작, 이번에 바꾸지 않음): timeout 은 출력을 다 읽은 뒤의 wait 에만 걸린다 -- 출력이 열려 있는 동안은 못 끊는다

if __name__ == "__main__":
    unittest.main()
