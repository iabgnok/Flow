from __future__ import annotations

from myflow.engine.models import SkillCard
from myflow.infra.config import AppConfig
from myflow.skills.base import Skill


class SkillNotFoundError(KeyError):
    pass


class SkillRegistry:
    def __init__(self):
        self._skills: dict[str, Skill] = {}

    def register(self, skill: Skill) -> None:
        if not skill.name:
            raise ValueError("Skill.name 不能为空")
        self._skills[skill.name] = skill

    def get(self, name: str) -> Skill:
        if name not in self._skills:
            raise SkillNotFoundError(f"未知技能 '{name}'。已注册技能: {sorted(self._skills.keys())}")
        return self._skills[name]

    @property
    def skill_names(self) -> set[str]:
        return set(self._skills.keys())

    def skill_output_field_sets(self) -> dict[str, frozenset[str] | None]:
        """各技能 output_model 的字段名。

        值为 ``None`` 时表示不做静态 outputs 映射校验（仅 ``sub_workflow``：运行时键由子工作流决定）。
        """
        out: dict[str, frozenset[str] | None] = {}
        for name, sk in self._skills.items():
            if name == "sub_workflow":
                out[name] = None
            else:
                out[name] = frozenset(sk.output_model.model_fields.keys())
        return out

    def all_skill_cards(self) -> list[SkillCard]:
        return [
            s.to_skill_card()
            for s in self._skills.values()
            if getattr(s, "include_in_prompt_catalog", True)
        ]

    def skill_cards_as_prompt(self) -> str:
        lines = ["## 可用技能清单\n"]
        for card in self.all_skill_cards():
            lines.append(f"### {card.name}")
            lines.append(f"用途: {card.description}")
            lines.append(f"适用: {card.when_to_use}")
            lines.append(f"不适用: {card.do_not_use_when}")
            lines.append(f"输入: {', '.join(f'{k} ({v})' for k, v in card.input_fields.items())}")
            lines.append(f"输出: {', '.join(f'{k} ({v})' for k, v in card.output_fields.items())}")
            lines.append(f"幂等: {'是' if card.idempotent else '否'}")
            lines.append("")
        return "\n".join(lines)


def build_default_registry(config: AppConfig | None = None) -> SkillRegistry:
    from myflow.infra.llm_client import LLMClient
    from myflow.infra.state_store import StateStore
    from myflow.skills.file_ops import FileReaderSkill, FileWriterSkill, MultiFileReaderSkill
    from myflow.skills.llm_call import LLMAnalyzeSkill, LLMGenerateSkill, LLMVerifySkill
    from myflow.skills.sub_workflow import SubWorkflowSkill

    cfg = config or AppConfig()
    llm = LLMClient(cfg)
    registry = SkillRegistry()
    store = StateStore(cfg.db_path)
    for skill in (FileReaderSkill(), MultiFileReaderSkill(), FileWriterSkill()):
        registry.register(skill)
    for skill in (LLMAnalyzeSkill(llm), LLMGenerateSkill(llm), LLMVerifySkill(llm)):
        registry.register(skill)
    registry.register(SubWorkflowSkill(registry, store, cfg))
    return registry

