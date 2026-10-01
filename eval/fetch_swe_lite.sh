#!/usr/bin/env bash
# SWE-agent + Claude 3.5 Sonnet, SWE-bench Lite (제출 20240620) 의 추적과 판정을 받는다.
# 판정(results.json)은 SWE-bench/experiments 저장소에서, 추적은 그 metadata.yaml 이 가리키는 공개 S3 에서.
# 쓰는 법: bash eval/fetch_swe_lite.sh <받을 곳>
set -euo pipefail
OUT=${1:?받을 곳}
SUB=20240620_sweagent_claude3.5sonnet
mkdir -p "$OUT/trajs"
if [ ! -d "$OUT/swe" ]; then
  git clone -q --filter=blob:none --sparse --depth 1 https://github.com/SWE-bench/experiments "$OUT/swe"
  git -C "$OUT/swe" sparse-checkout set --no-cone "/evaluation/lite/$SUB/results/" \
    "/evaluation/lite/20240402_sweagent_gpt4/results/" "/evaluation/lite/20240728_sweagent_gpt4o/results/"
fi
cp "$OUT/swe/evaluation/lite/$SUB/results/results.json" "$OUT/results.json"
# Lite 300 개의 이름 = 세 제출의 results.json 에 나온 이름의 합집합
python3 - "$OUT" <<'PY'
import glob, json, sys
ids = set()
for f in glob.glob(sys.argv[1] + "/swe/evaluation/lite/*/results/results.json"):
    for v in json.load(open(f)).values():
        ids |= set(v)
open(sys.argv[1] + "/ids.txt", "w").write("\n".join(sorted(ids)) + "\n")
print(len(ids), "instances")
PY
xargs -P 12 -I{} sh -c 'test -s "$0/trajs/{}.traj.gz" || (curl -sS -m 60 -f -o "$0/trajs/{}.traj" \
  "https://swe-bench-submissions.s3.amazonaws.com/lite/'"$SUB"'/trajs/{}.traj" && gzip -f "$0/trajs/{}.traj") \
  || echo "MISS {}"' "$OUT" < "$OUT/ids.txt"
ls "$OUT/trajs" | wc -l
