from __future__ import annotations

from abc import ABC, abstractmethod

from pydantic import BaseModel

from myflow.engine.models import SkillCard


class SkillExecutionError(RuntimeError):
    pass


class Skill(ABC):
    name: str = ""
    description: str = ""
    when_to_use: str = ""
    do_not_use_when: str = ""
    idempotent: bool = True
    #: 若为 False，不参与 Composer 技能清单注入（旧别名仍可注册执行）。
    include_in_prompt_catalog: bool = True

    input_model: type[BaseModel] = BaseModel
    output_model: type[BaseModel] = BaseModel

    # 执行技能（异步，技能可能存在io操作）
    @abstractmethod
    async def execute(self, inputs: BaseModel, context: dict) -> BaseModel:
        ...
    # 将技能转换为技能卡片
    def to_skill_card(self) -> SkillCard:
        input_fields: dict[str, str] = {}
        # 遍历输入模型字段，获取字段名称和类型
        for field_name, field_info in self.input_model.model_fields.items():
            anno = field_info.annotation
            type_str = getattr(anno, "__name__", str(anno))
            input_fields[field_name] = f"{type_str}, {'必填' if field_info.is_required() else '可选'}"

        # 遍历输出模型字段，获取字段名称和类型
        output_fields: dict[str, str] = {}
        for field_name, field_info in self.output_model.model_fields.items():
            anno = field_info.annotation
            type_str = getattr(anno, "__name__", str(anno))
            output_fields[field_name] = type_str
            
        #组装技能卡片
        return SkillCard(
            name=self.name,
            description=self.description,
            when_to_use=self.when_to_use,
            do_not_use_when=self.do_not_use_when,
            input_fields=input_fields,
            output_fields=output_fields,
            idempotent=self.idempotent,
        )

