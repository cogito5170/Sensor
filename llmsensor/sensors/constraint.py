"""제약 센서 -- 필수 필드 · 형식 · 스키마 · 하드 제약.

최종 답(task.answer)에 건다. 스키마를 주면 답에서 JSON 을 꺼내(통째 · ```json 블록 · 첫 {...}/[...]) 검사한다.
제약을 하나도 안 주면 UNKNOWN -- "검사할 것이 없었다" 는 "통과했다" 가 아니다.

스키마 검사기는 JSON Schema 의 **부분집합**이다: type · required · properties · additionalProperties(false) ·
enum · const · minLength · maxLength · pattern · minimum · maximum · items · minItems · maxItems.
$ref · oneOf · anyOf · format 은 모른다 -- 그런 키를 만나면 위반이 아니라 `unsupported` 로 적고 UNKNOWN 쪽으로 간다.
"""
from __future__ import annotations

import json
import re

from ..reading import Reading, OK, FAULT, UNKNOWN
from ..trace import Task

_TYPES = {"object": dict, "array": list, "string": str, "boolean": bool, "null": type(None)}
_KNOWN = {"type", "required", "properties", "additionalProperties", "enum", "const", "minLength", "maxLength",
          "pattern", "minimum", "maximum", "items", "minItems", "maxItems", "title", "description", "$schema"}


def _is(v, t: str) -> bool:
    if t == "integer":
        return isinstance(v, int) and not isinstance(v, bool)
    if t == "number":
        return isinstance(v, (int, float)) and not isinstance(v, bool)
    return isinstance(v, _TYPES.get(t, object))


def validate(v, schema: dict, path: str = "$") -> "tuple[list[str], list[str]]":
    """(위반들, 모르는 키들)."""
    errs, unk = [], [f"{path}:{k}" for k in schema if k not in _KNOWN]
    t = schema.get("type")
    if t is not None:
        ts = t if isinstance(t, list) else [t]
        if not any(_is(v, x) for x in ts):
            return [f"{path}: 형 {type(v).__name__} != {t}"], unk
    if "const" in schema and v != schema["const"]:
        errs.append(f"{path}: const 아님")
    if "enum" in schema and v not in schema["enum"]:
        errs.append(f"{path}: enum 밖 {v!r}")
    if isinstance(v, str):
        if "minLength" in schema and len(v) < schema["minLength"]:
            errs.append(f"{path}: 길이 {len(v)} < {schema['minLength']}")
        if "maxLength" in schema and len(v) > schema["maxLength"]:
            errs.append(f"{path}: 길이 {len(v)} > {schema['maxLength']}")
        if "pattern" in schema and not re.search(schema["pattern"], v):
            errs.append(f"{path}: pattern 불일치")
    if isinstance(v, (int, float)) and not isinstance(v, bool):
        if "minimum" in schema and v < schema["minimum"]:
            errs.append(f"{path}: {v} < {schema['minimum']}")
        if "maximum" in schema and v > schema["maximum"]:
            errs.append(f"{path}: {v} > {schema['maximum']}")
    if isinstance(v, dict):
        for k in schema.get("required", []):
            if k not in v:
                errs.append(f"{path}: 필수 필드 '{k}' 없음")
        props = schema.get("properties", {})
        for k, sub in props.items():
            if k in v:
                e, u = validate(v[k], sub, f"{path}.{k}")
                errs += e
                unk += u
        if schema.get("additionalProperties") is False:
            errs += [f"{path}: 허용 안 된 필드 '{k}'" for k in v if k not in props]
    if isinstance(v, list):
        if "minItems" in schema and len(v) < schema["minItems"]:
            errs.append(f"{path}: 항목 {len(v)} < {schema['minItems']}")
        if "maxItems" in schema and len(v) > schema["maxItems"]:
            errs.append(f"{path}: 항목 {len(v)} > {schema['maxItems']}")
        if isinstance(schema.get("items"), dict):
            for i, x in enumerate(v):
                e, u = validate(x, schema["items"], f"{path}[{i}]")
                errs += e
                unk += u
    return errs, unk


def extract_json(text: str):
    """답에서 JSON 하나를 꺼낸다. 없으면 예외."""
    s = text.strip()
    try:
        return json.loads(s)
    except json.JSONDecodeError:
        pass
    m = re.search(r"```(?:json)?\s*\n(.*?)```", s, re.S)
    if m:
        return json.loads(m.group(1))
    dec = json.JSONDecoder()
    for i, ch in enumerate(s):
        if ch in "{[":
            try:
                return dec.raw_decode(s[i:])[0]
            except json.JSONDecodeError:
                continue
    raise ValueError("답에 JSON 이 없다")


class ConstraintSensor:
    name = "constraint"

    def __init__(self, schema: "dict | None" = None, must=(), must_not=(), max_chars: "int | None" = None,
                 predicates=()):
        """must / must_not: 정규식. predicates: (이름, fn(answer:str)->bool) 의 목록."""
        self.schema, self.must, self.must_not = schema, list(must), list(must_not)
        self.max_chars, self.predicates = max_chars, list(predicates)

    def read(self, task: "Task | str") -> Reading:
        ans = task if isinstance(task, str) else task.answer
        if self.schema is None and not (self.must or self.must_not or self.max_chars or self.predicates):
            return Reading(self.name, UNKNOWN, "걸린 제약이 없다")
        errs, unk = [], []
        if self.schema is not None:
            try:
                e, unk = validate(extract_json(ans), self.schema)
                errs += e
            except ValueError as ex:          # json.JSONDecodeError 도 ValueError 다
                errs.append(f"JSON 을 못 꺼냄: {ex}")
        errs += [f"있어야 할 형식 없음: /{p}/" for p in self.must if not re.search(p, ans, re.M)]
        errs += [f"없어야 할 것이 있음: /{p}/" for p in self.must_not if re.search(p, ans, re.M)]
        if self.max_chars is not None and len(ans) > self.max_chars:
            errs.append(f"길이 {len(ans)} > {self.max_chars}")
        for nm, fn in self.predicates:
            try:
                if not fn(ans):
                    errs.append(f"제약 '{nm}' 위반")
            except Exception as ex:           # 제약 함수가 터진 것은 위반이 아니라 평가 실패다
                unk.append(f"제약 '{nm}' 평가 실패: {type(ex).__name__}")
        det = {"violations": errs, "unsupported": unk}
        if errs:
            return Reading(self.name, FAULT, f"위반 {len(errs)}: {errs[0]}", float(len(errs)), det)
        if unk:
            return Reading(self.name, UNKNOWN, f"평가 못 한 제약 {len(unk)}: {unk[0]}", None, det)
        return Reading(self.name, OK, "걸린 제약을 전부 만족", 0.0, det)
