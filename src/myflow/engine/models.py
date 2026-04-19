from __future__ import annotations
from typing import Any, Final, Literal, Optional
from pydantic import BaseModel, Field, field_validator


# ─── 工作流定义模型 ───
# 工作流对外契约
class ParamSpec(BaseModel):
    """工作流级输入/输出参数规格"""
    type: str = "string"
    description: str = ""
    required: bool = True
    default: Any = None

# Runner执行的对象
class WorkflowStep(BaseModel):
    """工作流步骤定义"""
    #步骤定位的核心
    id: int
    name: str
    #步骤执行的技能名称
    action: str
    description: str = ""
    # 输入映射
    inputs: dict[str, str] = Field(default_factory=dict)
    # 输出映射：key = 写入上下文的变量名；value = 本步技能返回值（Pydantic）中的字段名，须一致
    outputs: dict[str, str] = Field(default_factory=dict)
    # 条件判断
    condition: str | None = None
    # 失败时跳转目标步骤 ID
    on_fail: int | None = None
    max_retries: int = 3
    workflow: str | None = None  # 仅 sub_workflow 使用

    @field_validator("max_retries")
    @classmethod
    def cap_retries(cls, v: int) -> int:
        # 不在模型层截断重试次数：由 Validator 负责做确定性规则校验并给出错误码
        return v

    @field_validator("on_fail")
    @classmethod
    def on_fail_must_be_positive(cls, v: int | None) -> int | None:
        # 不在模型层限制 on_fail 目标：由 Validator 负责做确定性规则校验并给出错误码
        return v


class WorkflowModel(BaseModel):
    """工作流完整定义 —— 系统内部唯一真理"""
    name: str
    description: str
    version: str = "1.0"
    #入参规范
    inputs: dict[str, ParamSpec] = Field(default_factory=dict)
    #出参规范
    outputs: dict[str, ParamSpec] = Field(default_factory=dict)
    #步骤列表（驱动执行）
    steps: list[WorkflowStep] = Field(default_factory=list)


# ─── 校验报告模型 ───

class ValidationIssue(BaseModel):
    """单条校验问题"""
    code: str               # 错误码，如 "UNKNOWN_ACTION"
    message: str            # 人类可读描述
    step_id: int | None = None  # 关联步骤（如有）
    suggestion: str = ""    # 修复建议（回流给 LLM）

# 阻塞级警告：`passed` 仍可 True，但禁止执行且 Composer 须在闭环内重试直至消失
BLOCKING_WARNING_CODES: Final[frozenset[str]] = frozenset({"MERGEABLE_LLM_ANALYZE"})


class ValidationReport(BaseModel):
    """校验结果报告"""
    passed: bool = True
    errors: list[ValidationIssue] = Field(default_factory=list)
    warnings: list[ValidationIssue] = Field(default_factory=list)

    def add_error(self, code: str, message: str, step_id: int | None = None, suggestion: str = ""):
        self.errors.append(ValidationIssue(code=code, message=message, step_id=step_id, suggestion=suggestion))
        self.passed = False

    def add_warning(self, code: str, message: str, step_id: int | None = None, suggestion: str = ""):
        self.warnings.append(ValidationIssue(code=code, message=message, step_id=step_id, suggestion=suggestion))

    def has_blocking_warnings(self) -> bool:
        return any(w.code in BLOCKING_WARNING_CODES for w in self.warnings)

    def execution_ready(self) -> bool:
        """无 error 且无阻塞级 warning——可运行、可作为生成成功。"""
        return self.passed and not self.has_blocking_warnings()

    def error_summary(self) -> str:
        """格式化错误信息，用于回流给 LLM"""
        lines = []
        for e in self.errors:
            loc = f"step {e.step_id}" if e.step_id else "workflow"
            lines.append(f"[{e.code}] {loc}: {e.message}")
            if e.suggestion:
                lines.append(f"  修复建议: {e.suggestion}")
        return "\n".join(lines)

    def compose_feedback_summary(self) -> str:
        """回流 Composer：errors + 阻塞级 warnings（语义上等同「严格校验失败说明」）。"""
        chunks: list[str] = []
        if self.errors:
            chunks.append(self.error_summary())
        for w in self.warnings:
            if w.code not in BLOCKING_WARNING_CODES:
                continue
            loc = f"step {w.step_id}" if w.step_id else "workflow"
            line = f"[{w.code}] {loc}: {w.message}"
            chunks.append(line)
            if w.suggestion:
                chunks.append(f"  修复建议: {w.suggestion}")
        return "\n".join(chunks)


# ─── Skill 元数据模型 ───

class SkillCard(BaseModel):
    """Skill 对外暴露的元数据摘要，注入到 Composer 的 Prompt 中"""
    name: str
    description: str
    when_to_use: str
    do_not_use_when: str
    input_fields: dict[str, str]    # {field_name: type_description}
    output_fields: dict[str, str]
    idempotent: bool = True         # 是否幂等（决定是否允许自动重试）


# ─── 运行结果模型 ───

class StepResult(BaseModel):
    """单步执行结果"""
    step_id: int
    step_name: str
    action: str
    status: Literal["success", "failed", "skipped"]
    outputs: dict[str, Any] = Field(default_factory=dict)
    error: str | None = None
    duration_ms: int = 0

class RunResult(BaseModel):
    """工作流执行总结果"""
    run_id: str
    workflow_name: str
    status: Literal["completed", "failed", "interrupted"]
    # 所有步骤执行结果
    step_results: list[StepResult] = Field(default_factory=list)
    # 最终上下文
    final_context: dict[str, Any] = Field(default_factory=dict)
    # 总执行时间
    total_duration_ms: int = 0
    # 错误信息
    error: str | None = None