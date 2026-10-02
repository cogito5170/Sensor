"""Token 센싱(기준선) -- 얼마나 썼나, 맥락이 런타임 경계의 어느 쪽인가. **최적화 정책은 여기 없다.**"""
from .. import SensingPack
from .._base import M, R, canon

PACK = SensingPack(
    "token", "모형 호출이 무엇을 읽고 무엇을 썼나(토큰) · 맥락이 런타임이 선언한 경계의 어느 쪽인가",
    canon("tokens.input_uncached", "tokens.cache_read", "tokens.cache_write", "tokens.output", "tokens.reasoning",
          "tokens.reasoning_estimate", "call.tool_uses", "call.context_window", "run.context_window",
          "run.compaction_threshold"),
    tuple(M[n] for n in ("context_tokens", "context_window", "compaction_threshold", "context_utilization",
                         "context_margin", "compaction_margin", "context_growth", "reasoning_tokens",
                         "reasoning_estimate")),
    (R["context_pressure"],))
