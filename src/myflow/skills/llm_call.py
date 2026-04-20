from __future__ import annotations

import re

import structlog
from pydantic import BaseModel, Field

log = structlog.get_logger(__name__)

from myflow.infra.llm_client import LLMClient
from myflow.skills.base import Skill, SkillExecutionError

_PLACEHOLDER_SNIPPETS = (
    "<待填写>",
    "<填写>",
    "[待定]",
)
_DOUBLE_BRACE_FRAGMENT = re.compile(r"\{\{[\s\S]*?\}\}")

# on_fail 回跳后 Runner 写入 context；注入 user 侧避免「盲重试」
_MAX_PREV_ERROR_CHARS = 6000


def _append_on_fail_feedback(parts: list[str], context: dict) -> None:
    """若上一步校验/业务失败已写入 _prev_error，则附加到本轮 LLM user 文本（不依赖 YAML 显式引用）。"""
    prev_error = str(context.get("_prev_error", "")).strip()
    if not prev_error:
        return
    raw_attempt = context.get("_attempt", 0)
    try:
        attempt = int(raw_attempt)
    except (TypeError, ValueError):
        attempt = 0
    if attempt < 1:
        return
    if len(prev_error) > _MAX_PREV_ERROR_CHARS:
        prev_error = prev_error[:_MAX_PREV_ERROR_CHARS] + "\n…(已截断)"
    parts.append(
        f"\n【重试说明】这是第 {attempt + 1} 次尝试。"
        "上一步校验未通过或执行失败，原因如下:\n"
        f"{prev_error}\n"
        "请针对上述问题修正输出。"
    )

# 摘要/简洁类措辞：用于在 analyze/generate 中追加长度约束（非替换用户 instruction）
_CONCISE_KEYWORDS = re.compile(
    r"摘要|总结|概括|归纳|要点|简述|简要|简洁|提炼|梗概|一句话|几句话"
    r"|summary|summarize|brief|concise|overview|key\s*points|tl;?dr",
    re.IGNORECASE,
)


def _analysis_length_rule(instruction: str) -> str:
    if _CONCISE_KEYWORDS.search(instruction):
        return (
            "本次任务偏摘要/总结：analysis_result 长度**原则上不超过原文的 20%**，"
            "只保留核心论点与结论，不复述长篇论证细节。"
            "若原文很短（例如少于约 500 字），用约 3–5 句话概括即可。"
        )
    return (
        "除非指令明确要求「详细」「全面」，否则结论应简明，直击 instruction 所问。"
    )


def _generate_length_rule(instruction: str) -> str:
    if _CONCISE_KEYWORDS.search(instruction):
        return (
            "指令中含摘要/总结类要求时：相关段落长度**原则上不超过参考资料正文的 20%**，"
            "只提炼要点，不复述论证过程。"
        )
    return ""


def _reject_placeholder_delivery(text: str, *, role: str) -> None:
    """P2：禁止将模板占位符或未填标记当作最终交付（触发重试/on_fail）。"""
    if _DOUBLE_BRACE_FRAGMENT.search(text):
        raise SkillExecutionError(
            f"{role}仍含 '{{{{…}}}}' 占位片段，须替换为与用户任务相关的具体内容。"
        )
    lower = text.lower()
    for snip in _PLACEHOLDER_SNIPPETS:
        if snip.lower() in lower:
            raise SkillExecutionError(
                f"{role}检测到占位或未填标记 ({snip!r})，须输出可交付正文。"
            )


# llm_analyze — 与文档示例一致，主输出字段为 analysis_result
class LLMAnalyzeInput(BaseModel):
    content: str
    instruction: str


class LLMAnalyzeOutput(BaseModel):
    analysis_result: str = Field(description="分析结论或摘要")
    confidence: float = Field(default=1.0, description="置信度 0~1")


class LLMAnalyzeSkill(Skill):
    name = "llm_analyze"
    description = "用 LLM 分析文本内容并给出结构化结论"
    when_to_use = "需要对内容做归纳、对比、抽取要点或异常检测时"
    do_not_use_when = "确定性的字符串/正则即可完成的机械处理"
    idempotent = True
    input_model = LLMAnalyzeInput
    output_model = LLMAnalyzeOutput

    def __init__(self, llm: LLMClient):
        super().__init__()
        self._llm = llm

    async def execute(self, inputs: LLMAnalyzeInput, context: dict) -> LLMAnalyzeOutput:
        length_rule = _analysis_length_rule(inputs.instruction)
        system_parts = [
            "你是严谨的分析师。根据用户指令分析给定内容，输出简明、可执行的结论。",
            length_rule,
            "分析结论**必须基于给定内容**，不得替换为与给定内容无关的主题或示例。",
            "若给定内容为代码，分析和任何修改建议必须保留原有的函数名、类名和模块结构，"
            "不得将其替换为另一套无关代码或重新命名核心标识符。",
            "**禁止**在结论中使用未替换的占位符"
            "（如 {{{{字段名}}}}、<待填写>、待定、TBD 等非实质内容）；"
            "analysis_result 必须是面向最终读者的可用正文。",
        ]
        system = "\n".join(system_parts)
        parts = [f"指令:\n{inputs.instruction}\n\n---\n内容:\n{inputs.content}\n"]
        _append_on_fail_feedback(parts, context)
        user = "".join(parts)
        out = await self._llm.create_structured(
            response_model=LLMAnalyzeOutput,
            system=system,
            user=user,
            max_retries=2,
        )
        _reject_placeholder_delivery(out.analysis_result, role="analysis_result")
        return out


class LLMGenerateInput(BaseModel):
    instruction: str = Field(description="生成要求")
    context: str = Field(default="", description="可选的背景材料")


class LLMGenerateOutput(BaseModel):
    generated_text: str = Field(description="生成结果正文")


class LLMGenerateSkill(Skill):
    name = "llm_generate"
    description = "用 LLM 生成报告、代码或说明性文本"
    when_to_use = "需要从零撰写或改写一段自然语言产物时"
    do_not_use_when = "仅需复制或拼接已有文件内容时"
    idempotent = True
    input_model = LLMGenerateInput
    output_model = LLMGenerateOutput

    def __init__(self, llm: LLMClient):
        super().__init__()
        self._llm = llm

    async def execute(self, inputs: LLMGenerateInput, context: dict) -> LLMGenerateOutput:
        length_extra = _generate_length_rule(inputs.instruction)
        system_parts = [
            "你是写作与代码助手。严格遵守用户指令，直接给出所需正文。",
            "**直接输出最终内容**，不要添加：开场套话（如「以下是…」「根据您的要求…」）、"
            "冗长过渡、结尾客套（如「希望对您有帮助」）、或与任务无关的免责声明。",
            "用户要报告则从标题/第一节写起；要代码则从代码块或首行写起；要翻译则直接给出译文。",
        ]
        if length_extra:
            system_parts.append(length_extra)
        if inputs.context.strip():
            system_parts.append(
                "若提供了参考资料：生成内容**必须基于参考资料**，不得换成无关主题或无关示例。"
                "参考资料为代码时，输出须为对该代码的修改、扩展或围绕其的实现，不得换成另一套无关代码。"
                "生成测试代码时：import 中的模块名与符号必须与参考资料里真实出现的名称一致，不得臆造。"
            )
        system_parts.append(
            "**禁止**输出未替换的双花括号模板、或 <待填写> / 待定类非实质占位内容；"
            "generated_text 必须是可交付的最终结果。"
        )
        system = "\n".join(system_parts)
        parts = [f"要求:\n{inputs.instruction}"]
        if inputs.context.strip():
            parts.append(f"\n参考资料:\n{inputs.context}")
        _append_on_fail_feedback(parts, context)
        user = "\n".join(parts)
        out = await self._llm.create_structured(
            response_model=LLMGenerateOutput,
            system=system,
            user=user,
            max_retries=2,
        )
        _reject_placeholder_delivery(out.generated_text, role="generated_text")
        return out


class LLMVerifyInput(BaseModel):
    artifact: str = Field(description="待检查的文本或产物内容")
    criteria: str = Field(description="判定标准")


class LLMVerifyOutput(BaseModel):
    verify_result: str = Field(description="核验说明（通过或不通过的理由）")
    passed: bool = Field(description="是否满足标准")


class LLMVerifySkill(Skill):
    name = "llm_verify"
    description = "对产物做软规则检查（结构/格式/占位符/关键字等客观条件）"
    when_to_use = (
        "需要对单一产物做客观可核对的门禁检查时：结构是否齐全、格式是否合规、是否含占位符、"
        "是否包含明确的关键字/片段等。适合与 on_fail 配合形成可收敛的重试闭环。"
    )
    do_not_use_when = (
        "不要用于主观评价或不可稳定判定的标准（如“专业/生产级”“充分覆盖”“翻译自然流畅”“分析深入全面”等），"
        "尤其不要把这类主观标准配 on_fail 作为打回重做门禁；此类需求应改为在 generate/analyze 的 instruction 中约束，"
        "或仅输出建议、不触发重试闭环。若能用单元测试/静态规则完全覆盖，也不应使用。"
    )
    idempotent = True
    input_model = LLMVerifyInput
    output_model = LLMVerifyOutput

    def __init__(self, llm: LLMClient):
        super().__init__()
        self._llm = llm

    async def execute(self, inputs: LLMVerifyInput, context: dict) -> LLMVerifyOutput:
        system = (
            "你是质检员。根据「标准」判断「待检查内容」是否满足要求。"
            "必须给出 passed 布尔值；若不通过，在 verify_result 中指出缺失项。"
        )
        user = f"标准:\n{inputs.criteria}\n\n---\n待检查内容:\n{inputs.artifact}\n"
        out = await self._llm.create_structured(
            response_model=LLMVerifyOutput,
            system=system,
            user=user,
            max_retries=2,
        )
        if not out.passed:
            log.info(
                "llm_verify_failed",
                passed=False,
                verify_result=out.verify_result,
            )
            raise SkillExecutionError(out.verify_result)
        return out
