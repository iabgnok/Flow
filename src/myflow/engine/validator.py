from __future__ import annotations

import re
from collections import defaultdict

from myflow.engine.models import ValidationReport, WorkflowModel


DANGER_KEYWORDS = [
    r"\brm\b",
    r"\brmdir\b",
    r"shutil\.rmtree",
    r"DROP\s+TABLE",
    r"DELETE\s+FROM",
    r"\bsubprocess\b",
    r"os\.system",
    r"\bshutdown\b",
    r"\breboot\b",
]

# 整段输入仅为「双花括号」引用一个变量
_TEMPLATE_REF_RE = re.compile(r"^\{\{\s*([a-zA-Z_]\w*)\s*\}\}$")
# 整段输入仅为「单花括号」引用一个变量（兼容旧 YAML；建议改为双花括号）
_SINGLE_BRACE_FULL_RE = re.compile(r"^\{([a-zA-Z_]\w*)\}$")


class WorkflowValidator:
    def validate(
        self,
        workflow: WorkflowModel,
        available_skills: set[str],
        skill_output_fields: dict[str, frozenset[str] | None] | None = None,
    ) -> ValidationReport:
        report = ValidationReport()
        self._check_non_empty(workflow, report)
        self._check_unique_ids(workflow, report)
        self._check_actions(workflow, available_skills, report)
        self._check_outputs_declared(workflow, report)
        self._check_output_field_mappings(workflow, available_skills, skill_output_fields, report)
        self._check_variable_reachability(workflow, report)
        self._check_on_fail_targets(workflow, report)
        self._check_retries(workflow, report)
        self._check_template_residue(workflow, report)
        self._check_single_brace_placeholders(workflow, report)
        self._check_danger_keywords(workflow, report)
        self._check_sub_workflow_fields(workflow, report)
        self._check_mergeable_llm_analyze_steps(workflow, report)
        return report

    def _check_mergeable_llm_analyze_steps(self, wf: WorkflowModel, r: ValidationReport) -> None:
        """多步 llm_analyze 的 inputs.content 完全一致时应合并（阻塞级 warning，触发 Composer 重试）。

        仅比对字符串（strip 后相等），使整段 '{{var}}' 与含内插的长模板自然区分。
        llm_generate 暂不纳入（主输入语义更复杂，后续按需扩展）。
        """
        groups: dict[str, list[int]] = defaultdict(list)
        for step in wf.steps:
            if step.action != "llm_analyze":
                continue
            raw = (step.inputs or {}).get("content")
            if not isinstance(raw, str):
                continue
            key = raw.strip()
            groups[key].append(step.id)

        for ref, step_ids in groups.items():
            if len(step_ids) <= 1:
                continue
            sorted_ids = sorted(step_ids)
            short_ref = ref if len(ref) <= 120 else ref[:117] + "..."
            r.add_warning(
                "MERGEABLE_LLM_ANALYZE",
                f"步骤 {sorted_ids} 均使用 llm_analyze 且 inputs.content 完全相同（{short_ref!r}），"
                "应合并为一步；在同一条 instruction 中用编号列出各分析维度，勿重复传入同一大段正文。",
                step_id=sorted_ids[0],
                suggestion="单一 analysis_result（或分段标题的同一步输出）供后续引用；下游 context 引用合并结果而非再次传入原始正文。",
            )

    def _check_non_empty(self, wf: WorkflowModel, r: ValidationReport) -> None:
        if not wf.steps:
            r.add_error("EMPTY_STEPS", "工作流必须至少包含一个步骤")

    def _check_unique_ids(self, wf: WorkflowModel, r: ValidationReport) -> None:
        seen: set[int] = set()
        for step in wf.steps:
            if step.id < 1:
                r.add_error("DUPLICATE_STEP_ID", f"步骤 ID 必须为正整数: {step.id}", step_id=step.id)
                continue
            if step.id in seen:
                r.add_error("DUPLICATE_STEP_ID", f"步骤 ID {step.id} 重复", step_id=step.id)
            seen.add(step.id)

    def _check_actions(self, wf: WorkflowModel, skills: set[str], r: ValidationReport) -> None:
        for step in wf.steps:
            if step.action not in skills:
                r.add_error(
                    "UNKNOWN_ACTION",
                    f"未知技能 '{step.action}'",
                    step_id=step.id,
                    suggestion=f"可用技能: {sorted(skills)}",
                )

    def _check_outputs_declared(self, wf: WorkflowModel, r: ValidationReport) -> None:
        for step in wf.steps:
            if not step.outputs:
                r.add_error("MISSING_OUTPUT", "步骤必须声明至少一个输出映射（outputs）", step_id=step.id)

    def _check_output_field_mappings(
        self,
        wf: WorkflowModel,
        available_skills: set[str],
        skill_output_fields: dict[str, frozenset[str] | None] | None,
        r: ValidationReport,
    ) -> None:
        if not skill_output_fields:
            return
        for step in wf.steps:
            if step.action not in available_skills:
                continue
            allowed = skill_output_fields.get(step.action)
            if allowed is None:
                continue
            for ctx_name, skill_field in (step.outputs or {}).items():
                if skill_field not in allowed:
                    r.add_error(
                        "INVALID_OUTPUT_FIELD",
                        f"技能 '{step.action}' 没有输出字段 '{skill_field}'（上下文变量 '{ctx_name}'）。"
                        f"可用字段: {sorted(allowed)}",
                        step_id=step.id,
                    )

    def _vars_referenced_in_input_value(self, raw: str) -> list[str]:
        """从步骤输入字符串中收集被引用的上下文变量名。"""
        s = raw.strip()
        m = _TEMPLATE_REF_RE.fullmatch(s)
        if m:
            return [m.group(1)]
        m2 = _SINGLE_BRACE_FULL_RE.fullmatch(s)
        if m2:
            return [m2.group(1)]
        out: list[str] = []
        for m_emb in re.finditer(r"\{\{\s*([a-zA-Z_]\w*)\s*\}\}", raw):
            out.append(m_emb.group(1))
        # 去掉 {{var}} 后再收集内嵌单花括号 {var}，避免误解析 {{x}}
        masked = re.sub(r"\{\{\s*[a-zA-Z_]\w*\s*\}\}", "", raw)
        for m3 in re.finditer(r"\{([A-Za-z_][\w]*)\}", masked):
            out.append(m3.group(1))
        return out

    def _check_variable_reachability(self, wf: WorkflowModel, r: ValidationReport) -> None:
        available: set[str] = set(wf.inputs.keys())
        for step in sorted(wf.steps, key=lambda s: s.id):
            for _param_name, raw in (step.inputs or {}).items():
                if not isinstance(raw, str):
                    continue
                for var_name in self._vars_referenced_in_input_value(raw):
                    if var_name not in available:
                        r.add_error(
                            "UNBOUND_VARIABLE",
                            f"变量 '{var_name}' 在步骤 {step.id} 中被引用，但未在前序步骤中产出",
                            step_id=step.id,
                            suggestion=f"当前可用变量: {sorted(available)}",
                        )
            available.update((step.outputs or {}).keys())

    def _check_on_fail_targets(self, wf: WorkflowModel, r: ValidationReport) -> None:
        all_ids = {step.id for step in wf.steps}
        for step in wf.steps:
            if step.on_fail is None:
                continue
            if step.on_fail not in all_ids:
                r.add_error(
                    "ON_FAIL_TARGET_MISSING",
                    f"on_fail 目标步骤 {step.on_fail} 不存在",
                    step_id=step.id,
                )
            elif step.on_fail >= step.id:
                r.add_error(
                    "INVALID_ON_FAIL",
                    f"on_fail 目标必须 < 当前步骤 ID (当前={step.id}, 目标={step.on_fail})",
                    step_id=step.id,
                    suggestion="on_fail 只能向前跳转，形成重试循环",
                )

    def _check_retries(self, wf: WorkflowModel, r: ValidationReport) -> None:
        for step in wf.steps:
            if step.max_retries > 5:
                r.add_error("EXCESSIVE_RETRIES", "max_retries 不能超过 5", step_id=step.id)

    def _check_template_residue(self, wf: WorkflowModel, r: ValidationReport) -> None:
        for step in wf.steps:
            for k, v in (step.inputs or {}).items():
                if not isinstance(v, str):
                    continue
                if v.strip() in ("{{}}", "{{ }}", ""):
                    r.add_error("TEMPLATE_RESIDUE", f"输入 '{k}' 包含空的模板引用", step_id=step.id)

    def _check_single_brace_placeholders(self, wf: WorkflowModel, r: ValidationReport) -> None:
        """整段仅为单花括号占位符时提示统一为双花括号（规范）。"""
        for step in wf.steps:
            for k, v in (step.inputs or {}).items():
                if not isinstance(v, str):
                    continue
                if _SINGLE_BRACE_FULL_RE.match(v.strip()) and not _TEMPLATE_REF_RE.match(v.strip()):
                    r.add_warning(
                        "SINGLE_BRACE_STYLE",
                        f"输入 '{k}' 使用了整段单花括号占位符，建议改为双花括号形式 {{{{var}}}}",
                        step_id=step.id,
                    )

    def _check_danger_keywords(self, wf: WorkflowModel, r: ValidationReport) -> None:
        for step in wf.steps:
            text = f"{step.name} {step.description} {step.inputs} {step.outputs}"
            for pattern in DANGER_KEYWORDS:
                if re.search(pattern, text, re.IGNORECASE):
                    r.add_warning("DANGER_KEYWORD", f"检测到危险关键词匹配: {pattern}", step_id=step.id)

    def _check_sub_workflow_fields(self, wf: WorkflowModel, r: ValidationReport) -> None:
        for step in wf.steps:
            if step.action == "sub_workflow" and not step.workflow:
                r.add_error(
                    "MISSING_WORKFLOW_PATH",
                    "action 为 sub_workflow 时必须指定 workflow 字段",
                    step_id=step.id,
                )

