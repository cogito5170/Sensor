"""센서 층 수집용 과업 12 개 -- 2026-10-01 에 얼렸다(수집 전).

목적은 **성공을 재는 것이 아니라 센서를 움직이는 것**이다: 도구 오류 · 재시도 · 시간 초과 · 잘못된 인자 · 긴 출력 ·
큰 읽기 · 회전 상한 등 서로 다른 관측값이 나오게 고른 과업들이다. 성공 여부는 보지 않는다.
"""
from __future__ import annotations

from pathlib import Path


def _w(p: Path, name, text, mode=None):
    f = p / name
    f.parent.mkdir(parents=True, exist_ok=True)
    f.write_text(text)
    if mode:
        f.chmod(mode)


def seed_none(p):
    pass


def seed_bug(p):
    _w(p, "calc.py", "def mean(xs):\n    return sum(xs) / len(xs) + 1\n\n\ndef median(xs):\n    s = sorted(xs)\n"
                     "    return s[len(s) // 2]\n")
    _w(p, "test_calc.py", "import unittest\nfrom calc import mean, median\n\n\nclass T(unittest.TestCase):\n"
                          "    def test_mean(self):\n        self.assertEqual(mean([1, 2, 3]), 2)\n\n"
                          "    def test_median_even(self):\n        self.assertEqual(median([1, 2, 3, 4]), 2.5)\n\n\n"
                          "if __name__ == '__main__':\n    unittest.main()\n")


def seed_search(p):
    for i in range(30):
        body = f"def helper_{i}(x):\n    return x + {i}\n"
        if i == 17:
            body += "\n\ndef zeta_target(a, b):\n    return a * b\n"
        _w(p, f"pkg/mod_{i:02d}.py", body)


def seed_csv(p):
    rows = ["a,b,c"] + [f"{i},{(i * 37) % 101},{i % 7}" for i in range(200)]
    _w(p, "data.csv", "\n".join(rows) + "\n")


def seed_flaky(p):
    _w(p, "flaky.sh", "#!/usr/bin/env bash\nn=$(cat .count 2>/dev/null || echo 0)\nn=$((n+1))\necho $n > .count\n"
                      "if [ $n -lt 3 ]; then echo \"transient failure $n\" >&2; exit 1; fi\necho success\n", 0o755)


def seed_big(p):
    lines = []
    for i in range(3000):
        lines.append(f"# section {i // 300}" if i % 300 == 0 else f"line {i}: value={i * 13 % 997}")
    _w(p, "big.txt", "\n".join(lines) + "\n")


def seed_rename(p):
    for i in range(5):
        _w(p, f"src/f{i}.py", f"x = {i}\n\n\ndef use_{i}():\n    return x * 2\n")


def seed_x(p):
    _w(p, "x.txt", "the secret word is lantern\n")


TASKS = {
    "t01_create_test": {"seed": seed_none, "prompt":
        "Create fib.py with a function fib(n) returning the n-th Fibonacci number (fib(0)=0), and test_fib.py using "
        "unittest with three cases. Run the tests with `python3 -m unittest -v` and report the result."},
    "t02_fix_bug": {"seed": seed_bug, "prompt":
        "The tests in test_calc.py fail. Fix calc.py so `python3 -m unittest -v` passes. Do not edit the tests."},
    "t03_search": {"seed": seed_search, "prompt":
        "Which file under pkg/ defines the function zeta_target, and on which line? Answer with path:line."},
    "t04_impossible": {"seed": seed_none, "prompt":
        "Run the program ./run_me in this directory and tell me its output. Do not create or modify any files."},
    "t05_long_write": {"seed": seed_none, "prompt":
        "Write a roughly 600-word plain-English explanation of how hash tables handle collisions into notes.md."},
    "t06_csv_mean": {"seed": seed_csv, "prompt":
        "Compute the mean of column b in data.csv using python3 and report the number with 3 decimals."},
    "t07_flaky_retry": {"seed": seed_flaky, "prompt":
        "Run ./flaky.sh. If it fails, run it again, up to 5 attempts total. Report how many attempts it took."},
    "t08_max_turns": {"seed": seed_rename, "max_turns": 3, "prompt":
        "In every file under src/, rename the variable x to count (all uses). Then show each file's contents."},
    "t09_big_read": {"seed": seed_big, "prompt":
        "Read big.txt fully and describe its structure: how many sections, and what each line looks like."},
    "t10_rename": {"seed": seed_rename, "prompt":
        "In every file under src/, rename the variable x to count (all uses). Then run python3 -c to import each "
        "module from src and print use_N() for N in 0..4."},
    "t11_timeout": {"seed": seed_none, "timeout": 400, "prompt":
        "Use the Bash tool to run exactly this command with no timeout parameter: sleep 150 && echo finished . "
        "Report what happened."},
    "t12_bad_args": {"seed": seed_x, "prompt":
        "Use the Read tool with the relative path 'x.txt' (not an absolute path) on your first attempt, then tell me "
        "the secret word in the file."},
}
