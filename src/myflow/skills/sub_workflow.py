from __future__ import annotations

from pydantic import BaseModel, ConfigDict

from myflow.engine.skill_registry import SkillRegistry
from myflow.engine.workflow_io import load_workflow, resolve_existing_workflow_file
from myflow.infra.config import AppConfig
from myflow.infra.state_store import StateStore
from myflow.skills.base import Skill, SkillExecutionError


class SubWorkflowInput(BaseModel):
    """workflow_path 由 Runner 注入；其余字段为子工作流契约输入。"""

    workflow_path: str
    model_config = ConfigDict(extra="allow")


class SubWorkflowOutput(BaseModel):
    """子工作流 outputs 键扁平合并到父上下文；具体键由子 YAML 契约决定。"""

    model_config = ConfigDict(extra="allow")


class SubWorkflowSkill(Skill):
    name = "sub_workflow"
    description = "加载并执行另一个 YAML 工作流，将其最终上下文中契约输出合并回当前上下文"
    when_to_use = "需要将复杂流程拆分为可复用子图、或多阶段流水线组合时"
    do_not_use_when = "单文件内少量步骤即可完成时（避免过度嵌套）"
    idempotent = False
    input_model = SubWorkflowInput
    output_model = SubWorkflowOutput

    def __init__(self, registry: SkillRegistry, store: StateStore, config: AppConfig) -> None:
        super().__init__()
        self._registry = registry
        self._store = store
        self._config = config

    async def execute(self, inputs: SubWorkflowInput, context: dict) -> SubWorkflowOutput:
        payload = inputs.model_dump()
        wf_path = str(payload.pop("workflow_path", "") or "").strip()
        if not wf_path:
            raise SkillExecutionError("sub_workflow 缺少 workflow_path")
        try:
            path = resolve_existing_workflow_file(wf_path, workflows_dir=self._config.workflows_dir)
        except (OSError, ValueError) as e:
            raise SkillExecutionError(f"无法解析子工作流路径: {wf_path}: {e}") from e

        try:
            child_wf = load_workflow(path)
        except Exception as e:
            raise SkillExecutionError(f"加载子工作流失败: {path}: {e}") from e

        child_ctx = {k: v for k, v in payload.items() if v is not None}
        from myflow.engine.runner import Runner

        runner = Runner(self._registry, self._store, self._config)
        sub_run = await runner.run(child_wf, initial_context=child_ctx)
        if sub_run.status != "completed":
            err = sub_run.error or "子工作流未成功完成"
            raise SkillExecutionError(f"子工作流执行失败 ({child_wf.name}): {err}")

        out: dict = {}
        for key in child_wf.outputs.keys():
            if key in sub_run.final_context:
                out[key] = sub_run.final_context[key]
        if not out:
            out = {k: v for k, v in sub_run.final_context.items() if not str(k).startswith("_")}
        return SubWorkflowOutput(**out)
