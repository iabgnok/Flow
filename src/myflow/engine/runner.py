from __future__ import annotations

import re
import types
import time
from collections.abc import Callable
from typing import Any, Union, get_args, get_origin
from uuid import uuid4

import structlog
from simpleeval import NameNotDefined, simple_eval
from tenacity import AsyncRetrying, retry_if_not_exception_type, stop_after_attempt, wait_exponential

from myflow.engine.models import RunResult, StepResult, WorkflowModel, WorkflowStep
from myflow.engine.skill_registry import SkillNotFoundError, SkillRegistry
from myflow.engine.validator import WorkflowValidator
from myflow.infra.config import AppConfig
from myflow.infra.state_store import StateStore
from myflow.skills.base import SkillExecutionError

log = structlog.get_logger(__name__)

# 整段仅为一个变量引用（保留上下文中的原始类型）
_WHOLE_TEMPLATE_REF_RE = re.compile(r"^\{\{\s*([a-zA-Z_]\w*)\s*\}\}$")
_SINGLE_BRACE_FULL_RE = re.compile(r"^\{([a-zA-Z_]\w*)\}$")
# 字符串内插：一处或多处 {{var}}
_EMBEDDED_TEMPLATE_RE = re.compile(r"\{\{\s*([a-zA-Z_]\w*)\s*\}\}")
# 内插中的单花括号 {var}（避免误伤 JSON；不与 {{ 配对）
_EMBEDDED_SINGLE_BRACE_RE = re.compile(r"(?<!\{)\{([a-zA-Z_]\w*)\}(?!\})")


def _expects_str_annotation(annotation: Any) -> bool:
    """判定 Pydantic 字段注解是否包含 str（含 Optional[str]、str | None）。"""
    if annotation is str:
        return True
    origin = get_origin(annotation)
    args = get_args(annotation)
    if origin is Union:
        return any(_expects_str_annotation(a) for a in args)
    if origin is types.UnionType:
        return any(_expects_str_annotation(a) for a in args)
    return False


def format_path_content_dict_as_text(path_content: dict[str, Any]) -> str:
    """将 path→content 的 dict（如 multi_file_reader.file_contents）格式化为可读正文。"""
    chunks: list[str] = []
    for path in sorted(path_content.keys()):
        raw = path_content[path]
        body = raw if isinstance(raw, str) else str(raw)
        chunks.append(f"=== {path} ===\n{body}\n")
    return "\n".join(chunks)


class StepFailedError(RuntimeError):
    pass


class Runner:
    # 初始化Runner对象：入参：技能注册表，状态存储，配置，回调函数（用于打印步骤结果）
    def __init__(
        self,
        registry: SkillRegistry,
        state_store: StateStore,
        config: AppConfig,
        *,
        on_step_result: Callable[[StepResult], None] | None = None,
    ):
        self.registry = registry  # 技能注册表
        self.state_store = state_store  # 状态存储
        self.config = config  # 配置
        self._on_step_result = on_step_result
        self.validator = WorkflowValidator()  # 工作流验证器

    # .run方法：执行工作流（入参：工作流定义模型，初始上下文，一次工作流执行的唯一标识）->（工作流）执行结果
    async def run(
        self,
        workflow: WorkflowModel,
        initial_context: dict | None = None,

        # run_id不传入则自动生成；手动传入相当于续跑和恢复一次run；
        # run_id用于保存工作流级的结果
        # 读取和恢复: 查state_store.load_run(run_id) 查是否存在“正在运行中的旧记录
        # 保存断点和step级的结果：配合step_id和当前上下文，保存断点和step级的结果
        run_id: str | None = None,  
    ) -> RunResult:
        # 初始化一次run的所有资产
        run_id = run_id or uuid4().hex
        # 上下文context是工作流执行过程中不断更新的状态；
        # 初始值来自入参 initial_context（如果有的话），否则是空字典；每步执行成功后会把技能输出写回上下文；每步执行前会把当前上下文保存到 state_store 以支持断点续传；
        context = dict(initial_context or {})
        step_results: list[StepResult] = []
        retry_counts: dict[int, int] = {}
        start_time = time.monotonic()
        # 工作流校验：.validate方法会对工作流运行所有的checks类方法，生成report；如果校验不通过，则返回失败结果；
        report = self.validator.validate(
            workflow,
            self.registry.skill_names,
            skill_output_fields=self.registry.skill_output_field_sets(),
        )
        if not report.execution_ready():
            fb = report.compose_feedback_summary().strip()
            detail = fb if fb else report.error_summary()
            return RunResult(
                run_id=run_id,
                workflow_name=workflow.name,
                status="failed",
                error=f"工作流校验失败:\n{detail}",
            )
        # 异步初始化state_store：用于后续的断点续传和持久化；
        await self.state_store.init()
        # 断点续传：尝试从state_store中恢复上下文和当前步骤索引；
        context, start_index = await self._maybe_resume(run_id, context, workflow)
        # 工作流输入预处理：将工作流契约中声明的 default 填入上下文（仅当该键缺失或为 None）
        # 校验 CLI 传入的键名与必填输入；有问题则返回失败结果；
        self._seed_workflow_input_defaults(workflow, context)
        runtime_err = self._validate_runtime_inputs(workflow, context, initial_context or {})
        if runtime_err:
            return RunResult(
                run_id=run_id,
                workflow_name=workflow.name,
                status="failed",
                error=runtime_err,
                total_duration_ms=int((time.monotonic() - start_time) * 1000),
            )
        
        # 首先按步骤id大小排序（线性引擎），大小顺序就是执行顺序（on_fail是特殊情况）
        steps_sorted = sorted(workflow.steps, key=lambda s: s.id)
        resume_cursor = 0 if start_index == 0 else steps_sorted[start_index].id
        # 持久化运行记录（run表），状态置为 running，保存初始上下文和恢复起点（如果有的话）
        await self.state_store.save_run(run_id, workflow.name, "running", context, current_step_id=resume_cursor)

        # 主循环：遍历工作流步骤列表，执行每个步骤；
        # 运行的异常收口和状态落盘
        i = start_index
        try:
            while i < len(steps_sorted):
                step = steps_sorted[i]
                step_start = time.monotonic()
                if self.config.debug:
                    log.debug(
                        "step_enter",
                        run_id=run_id[:8],
                        workflow=workflow.name,
                        step_id=step.id,
                        action=step.action,
                    )
                #当 step.condition 存在且条件判定为 False 时（步骤中没有要执行的技能）：
                # 跳过下一步执行技能步骤，继续执行下一个步骤；
                if step.condition:
                    if not self._condition_true(step.condition, context):
                        sr = StepResult(
                            step_id=step.id,
                            step_name=step.name,
                            action=step.action,
                            status="skipped",
                        )
                        step_results.append(sr)
                        if self._on_step_result:
                            self._on_step_result(sr)
                        i += 1
                        continue

                # step执行正式开始
                # 持久化锚点：将当前上下文保存到state_store（run表）中，表示步骤开始执行；
                await self.state_store.save_checkpoint(run_id, step.id, context)

                # 执行技能
                # 运行级的重试块：处理onfail跳转
                try:
                    # 获取技能实例：根据step的action属性从注册表中获取技能实例
                    skill = self.registry.get(step.action)
                    # 解析输入：将step.inputs中的{{var}}引用替换为context中的实际值
                    resolved_inputs = self._resolve_inputs(step, context)
                    resolved_inputs = self._coerce_resolved_inputs_for_skill(skill, resolved_inputs)
                    # 针对子工作流的调用
                    if step.action == "sub_workflow":
                        wp = step.workflow or ""
                        resolved_inputs["workflow_path"] = str(
                            self._resolve_template_value(wp, context)
                        )
                    # 校验输入：用技能的 input_model 做校验 + 构造 （**打包成字典）
                    validated_inputs = skill.input_model(**resolved_inputs)
                    # 带重试策略的执行技能（据skill.idempotent判断是否需要重试）[技能级的重试逻辑]
                    output = await self._execute_with_retry(skill, validated_inputs, context, step=step)
                    # 写回上下文：先将输出规范化为字典，再将输出写回上下文
                    output_dict = output.model_dump()
                    self._apply_step_outputs(step, output_dict, context)
                    # 记录步骤结果
                    step_duration_ms = int((time.monotonic() - step_start) * 1000)
                    sr = StepResult(
                        step_id=step.id,
                        step_name=step.name,
                        action=step.action,
                        status="success",
                        outputs=output_dict,
                        duration_ms=step_duration_ms,
                    )
                    step_results.append(sr)
                    if self._on_step_result:
                        self._on_step_result(sr)
                    # 持久化步骤结果
                    await self.state_store.save_step(
                        run_id, step.id, "success", output_dict, context, duration_ms=step_duration_ms
                    )
                    # 避免后续无关步骤仍看到上一轮 on_fail 的反馈（仅应在紧接回跳后的 LLM 步注入）
                    context.pop("_prev_error", None)
                    context.pop("_attempt", None)
                    # 进度展示交给 CLI 的 on_step_result（可打印更友好的一行）

                # 异常分支处理：
                # 未知技能，硬失败，不重试
                except SkillNotFoundError:
                    raise
                # 其他异常，根据on_fail重试逻辑处理：
                except Exception as e:
                    # 记录失败步骤结果
                    step_duration_ms = int((time.monotonic() - step_start) * 1000)
                    sr = StepResult(
                        step_id=step.id,
                        step_name=step.name,
                        action=step.action,
                        status="failed",
                        error=str(e),
                        duration_ms=step_duration_ms,
                    )
                    step_results.append(sr)
                    if self._on_step_result:
                        self._on_step_result(sr)
                    # 持久化失败步骤结果
                    await self.state_store.save_step(
                        run_id, step.id, "failed", {"error": str(e)}, context, duration_ms=step_duration_ms
                    )
                    # 进度展示交给 CLI 的 on_step_result（可打印更友好的一行）

                    # 根据on_fail重试逻辑处理（当step配置了on_fail时）[工作流级的重试逻辑]：
                    if step.on_fail is not None:
                        # 每一个具有on_fail的step，都会有一个重试计数器，用于记录重试次数
                        retry_counts[step.id] = retry_counts.get(step.id, 0) + 1
                        # 如果重试次数小于最大重试次数，则重试
                        if retry_counts[step.id] <= step.max_retries:
                            # 写入本次错误信息到上下文中，用于后续重试
                            context["_prev_error"] = str(e)
                            # 记录当前重试次数
                            context["_attempt"] = retry_counts[step.id]
                            # 找到on_fail目标步骤的索引
                            target_index = self._find_step_index(steps_sorted, step.on_fail)
                            # 跳转到on_fail目标步骤，继续执行
                            i = target_index
                            continue  # 立即跳转
                    
                    # 如果没有on_fail，或者重试次数大于最大重试次数，则抛出异常，结束当前步骤执行
                    raise StepFailedError(f"Step {step.id} ({step.name}) 失败: {e}") from e

                i += 1

        except KeyboardInterrupt:
            # 用户中断，持久化当前运行记录的生命周期
            cur = steps_sorted[i].id if i < len(steps_sorted) else 0
            await self.state_store.save_run(run_id, workflow.name, "running", context, current_step_id=cur)
            raise

        # 依然抛错，本次run失败
        except Exception as e:
            # 持久化失败的运行结果，状态置为failed
            await self.state_store.save_run(run_id, workflow.name, "failed", context)
            # 返回失败的运行结果
            return RunResult(
                run_id=run_id,
                workflow_name=workflow.name,
                status="failed",
                step_results=step_results,
                final_context=context,
                error=str(e),
                total_duration_ms=int((time.monotonic() - start_time) * 1000),
            )
        # 完成，本次run成功
        # 持久化完成的运行结果，状态置为completed
        await self.state_store.save_run(run_id, workflow.name, "completed", context)
        # 返回完成的运行结果
        return RunResult(
            run_id=run_id,
            workflow_name=workflow.name,
            status="completed",
            step_results=step_results,
            final_context=context,
            total_duration_ms=int((time.monotonic() - start_time) * 1000),
        )
    

    # 条件求值：根据条件表达式和上下文，求出条件是否成立，决定step是继续执行还是skip
    # 在 run() 哪用：遇到 step.condition 时决定该 step 是 skipped 还是继续执行。
    # 核心逻辑：用 simple_eval 在 context 变量环境里求值（例如 x > 0 and flag）。
    def _condition_true(self, condition: str, context: dict) -> bool:
        try:
            return bool(simple_eval(condition, names=context))
        except NameNotDefined:
            return False
        except Exception:
            return False

    # 解析输入：将step.inputs中的{{var}}引用替换为context中的实际值
    # 输入值如果是 "{{ xxx }}"，就从 context["xxx"] 取；
    # 取不到就给 ""（空字符串）；
    # 不是模板引用就原样传入（可以是字面量字符串/数字/布尔等）。
    def _seed_workflow_input_defaults(self, workflow: WorkflowModel, context: dict) -> None:
        """将工作流契约中声明的 default 填入上下文（仅当该键缺失或为 None）。"""
        for name, spec in workflow.inputs.items():
            if name in context and context[name] is not None:
                continue
            if spec.default is not None:
                context[name] = spec.default

    def _validate_runtime_inputs(
        self, workflow: WorkflowModel, context: dict, initial_context: dict
    ) -> str | None:
        """校验 CLI 传入的键名与必填输入；有问题则返回可读错误文案。"""
        if workflow.inputs:
            extra = set(initial_context.keys()) - set(workflow.inputs.keys())
            if extra:
                unknown = ", ".join(sorted(extra))
                accepted = ", ".join(sorted(workflow.inputs.keys()))
                return f"未知的 --input 参数: {unknown}。本工作流接受的参数名为: {accepted}"

        missing: list[str] = []
        for name, spec in workflow.inputs.items():
            if not spec.required:
                continue
            val = context.get(name)
            if val is None:
                missing.append(name)
            elif isinstance(val, str) and not str(val).strip():
                missing.append(name)

        if missing:
            need = ", ".join(sorted(missing))
            accepted = ", ".join(sorted(workflow.inputs.keys()))
            return f"缺少必填的工作流输入（或值为空）: {need}。请传入例如 --input …（可用参数: {accepted}）"

        return None

    def _apply_step_outputs(
        self, step: WorkflowStep, output_dict: dict[str, object], context: dict[str, object]
    ) -> None:
        """按步骤 ``outputs`` 映射将技能返回值写入上下文（不做字段猜测）。"""
        for context_name, skill_field in (step.outputs or {}).items():
            if skill_field not in output_dict:
                raise StepFailedError(
                    f"步骤 {step.id} outputs 声明从技能字段 '{skill_field}' 映射到上下文 "
                    f"'{context_name}'，但本步实际输出键为 {sorted(output_dict.keys())}"
                )
            context[context_name] = output_dict[skill_field]

    def _resolve_inputs(self, step: WorkflowStep, context: dict) -> dict:
        resolved: dict[str, object] = {}
        for key, ref in (step.inputs or {}).items():
            resolved[key] = self._resolve_template_value(ref, context)
        return resolved

    def _coerce_resolved_inputs_for_skill(self, skill: object, resolved: dict[str, object]) -> dict[str, object]:
        """技能入参若为 str，而上下文给出 dict（常见于 multi_file_reader→llm_*），序列化为可读正文。"""
        model = getattr(skill, "input_model", None)
        if model is None or not hasattr(model, "model_fields"):
            return resolved
        out = dict(resolved)
        for fname, finfo in model.model_fields.items():
            if fname not in out:
                continue
            val = out[fname]
            if not isinstance(val, dict):
                continue
            if not _expects_str_annotation(finfo.annotation):
                continue
            out[fname] = format_path_content_dict_as_text(val)
        return out

    def _resolve_template_value(self, raw: object, context: dict) -> object:
        if not isinstance(raw, str):
            return raw
        stripped = raw.strip()
        # 1) 整段即单个 {{var}}：保留上下文中的类型（bool/int/对象等）
        m_whole = _WHOLE_TEMPLATE_REF_RE.fullmatch(stripped)
        if m_whole:
            return context.get(m_whole.group(1), "")
        # 2) 整段即单个 {var}（兼容写法）
        m_single = _SINGLE_BRACE_FULL_RE.fullmatch(stripped)
        if m_single:
            return context.get(m_single.group(1), "")
        # 3) 含内插占位符：结果为 str，各占位符替换为 str(变量值)
        if _EMBEDDED_TEMPLATE_RE.search(raw) or _EMBEDDED_SINGLE_BRACE_RE.search(raw):

            def repl_double(m: re.Match[str]) -> str:
                return str(context.get(m.group(1), ""))

            out = _EMBEDDED_TEMPLATE_RE.sub(repl_double, raw)
            out = _EMBEDDED_SINGLE_BRACE_RE.sub(repl_double, out)
            return out
        return raw

    # 带重试策略的执行技能（据skill.idempotent判断是否需要重试）[技能级的重试逻辑]
    # 若技能标记为 幂等（idempotent=True），则对 skill.execute 做 最多 3 次指数退避重试；
    # 否则不重试。
    async def _execute_with_retry(self, skill, inputs, context, step: WorkflowStep):
        if getattr(skill, "idempotent", True):
            async for attempt in AsyncRetrying(
                stop=stop_after_attempt(3),
                wait=wait_exponential(multiplier=1, max=10),
                retry=retry_if_not_exception_type(SkillExecutionError),
                reraise=True,
            ):
                with attempt:
                    return await skill.execute(inputs, context)
        return await skill.execute(inputs, context)

    # 尝试从state_store中恢复上下文和当前步骤索引
    # 用 run_id 从 state_store 读取历史 run；
    # 若发现该 run 之前是 running 状态，说明可能中断过：
    # 合并保存的 context
    # 取出 current_step_id 作为恢复目标
    # 返回“恢复后的 context + 恢复起点索引”
    # 否则从第 0 步开始。
    async def _maybe_resume(self, run_id: str, context: dict, workflow: WorkflowModel) -> tuple[dict, int]:
        saved = await self.state_store.load_run(run_id)
        if saved and saved.get("status") == "running":
            context.update(saved.get("context", {}))
            raw = saved.get("current_step_id")
            resume_step_id = 0 if raw is None else int(raw)
            steps_sorted = sorted(workflow.steps, key=lambda s: s.id)
            if resume_step_id == 0:
                return context, 0
            return context, self._find_step_index(steps_sorted, resume_step_id)
        return context, 0

    # 找到步骤的索引
    # 在 run() 哪用：
    # on_fail 回跳时：把目标 step id 转换成 while 循环用的 i；
    # _maybe_resume 恢复时：把 current_step_id 转成起始索引。
    def _find_step_index(self, steps_sorted: list[WorkflowStep], step_id: int) -> int:
        for idx, step in enumerate(steps_sorted):
            if step.id == step_id:
                return idx
        raise ValueError(f"步骤 ID {step_id} 不存在")

