# MyFlow 完整设计文档

> 版本: v1.2  
> 日期: 2026-04-18  
> 状态: 设计基线（含阶段 4 工作方式、阶段 5 外部集成规划）  
> 适用读者: 实现者（人类或 AI），需要据此文档从零构建完整系统

---

## 目录

1. [项目定位与设计原则](#1-项目定位与设计原则)
2. [技术栈](#2-技术栈)
3. [系统架构](#3-系统架构)
4. [工作流格式规范](#4-工作流格式规范-yaml-dsl)
5. [数据模型定义](#5-数据模型定义-pydantic)
6. [Skill 体系设计](#6-skill-体系设计)
7. [引擎层详细设计](#7-引擎层详细设计)
8. [基础设施层详细设计](#8-基础设施层详细设计)
9. [CLI 设计](#9-cli-设计)
10. [全链路数据流](#10-全链路数据流)
11. [幻觉控制体系](#11-幻觉控制体系)
12. [安全性与鲁棒性设计](#12-安全性与鲁棒性设计)
13. [测试策略与质量指标](#13-测试策略与质量指标)
14. [目录结构](#14-目录结构)
15. [实施阶段划分](#15-实施阶段划分)
16. [开发过程疑问区](#16-开发过程疑问区)
17. [阶段 5：外部集成扩展（HTTP 与 Serve）](#17-阶段-5外部集成扩展http-与-serve)

---

## 1. 项目定位与设计原则

### 1.1 定位

MyFlow 是一个以 YAML 为工作流格式、以 LLM 结构化输出为生成引擎、以确定性代码校验为治理手段的**工作流自动生成与执行系统**。

系统接收自然语言需求，输出可被本引擎重复执行的标准化 YAML 工作流文件，并提供 CLI 界面完成生成、校验、执行、状态查询等全部操作。

### 1.2 设计原则

```
原则 1: MVP 优先
    先做能跑通的最小系统，再迭代增强。
    每个模块的第一版必须是能运行的代码，不是设计文档。

原则 2: 确定性优先
    能用代码判定的规则，代码做最终判官，LLM 只做提议者。
    LLM 输出必须经过代码校验才能生效。

原则 3: 类型驱动
    全链路使用 Pydantic 类型化对象传递数据。
    不存在"LLM 输出字符串 → 手动 parse → dict"这种松散环节。

原则 4: 层数最少化
    三层架构（入口 → 引擎 → 基础设施），依赖方向单向向下。
    不引入"业务编排层""协调层"等中间抽象。

原则 5: CLI-First
    所有功能通过 CLI 暴露，CLI 是唯一的用户交互界面。
```

### 1.3 底线目标

```
底线 1: 生成的工作流必须可被本引擎正确执行。
底线 2: 安全检查由代码完成，不依赖 LLM 判断。
底线 3: 运行状态可持久化、可恢复。
```

---

## 2. 技术栈

### 2.1 核心依赖

| 领域 | 选型 | 版本要求 | 选型理由 |
|------|------|---------|---------|
| 语言 | Python | ≥3.11 | async/await 成熟，类型提示完备，AI 生态最丰富 |
| 包管理 | uv | latest | 速度快，lockfile 可靠，替代 pip/poetry |
| CLI 框架 | Typer | ≥0.12 | 基于类型提示自动生成 CLI，内置 async 支持，底层为 Click |
| 终端美化 | Rich | ≥13.0 | 表格、进度条、面板、语法高亮、日志美化，业界标准 |
| 类型系统 | Pydantic | ≥2.0 | 数据校验、序列化、JSON Schema 生成，全链路类型基础 |
| 配置管理 | pydantic-settings | ≥2.0 | 环境变量 + .env 文件统一加载，类型化配置 |
| LLM 结构化输出 | instructor | ≥1.0 | 将 LLM 输出强制转为 Pydantic 对象，内置重试与错误回流 |
| LLM SDK | anthropic / openai | latest | 直接使用提供商 SDK，不经过 LangChain 抽象层 |
| YAML 解析 | PyYAML / ruamel.yaml | latest | 工作流文件解析与序列化 |
| 条件表达式 | simpleeval | ≥1.0 | 安全沙盒表达式求值，替代 Python eval() |
| 数据库 | sqlite3 (标准库) + aiosqlite | latest | 状态持久化，轻量单机方案 |
| 重试 | tenacity | ≥8.0 | 指数退避重试，用于 Skill 执行层 |
| 日志 | structlog | ≥24.0 | 结构化日志，配合 Rich 终端渲染 |
| 测试 | pytest + pytest-asyncio | latest | 异步测试支持 |

### 2.2 不使用的技术（及理由）

| 技术 | 不使用理由 |
|------|-----------|
| LangChain / LangGraph | 抽象层过重，调试困难，个人项目不需要其生态集成能力 |
| Markdown DSL | 解析脆弱（需自写正则 Parser），LLM 生成不稳定，已被 YAML 替代 |
| pickle | 序列化不安全，对象不可序列化时整包丢失，用 JSON 替代 |
| Redis / PostgreSQL | 单机 SQLite 完全够用，不引入运维成本 |

### 2.3 pyproject.toml 依赖声明

```toml
[project]
name = "myflow"
version = "0.1.0"
requires-python = ">=3.11"
dependencies = [
    "typer[all]>=0.12",
    "rich>=13.0",
    "pydantic>=2.0",
    "pydantic-settings>=2.0",
    "instructor>=1.0",
    "anthropic>=0.40",
    "openai>=1.50",
    "ruamel.yaml>=0.18",
    "simpleeval>=1.0",
    "aiosqlite>=0.20",
    "tenacity>=8.0",
    "structlog>=24.0",
    # 阶段 5（外部集成）启用时追加:
    # "httpx>=0.27",
    # "fastapi>=0.115",
    # "uvicorn>=0.32",
]

[project.scripts]
myflow = "myflow.cli:app"

[tool.pytest.ini_options]
asyncio_mode = "auto"
```

---

## 3. 系统架构

### 3.1 三层架构

```
┌──────────────────────────────────────────────────────────┐
│  入口层  (CLI)                                            │
│    cli.py         Typer 命令定义与参数解析                  │
│    display.py     Rich 输出格式化（表格/进度条/面板/日志）   │
│                                                          │
│    职责: 解析用户输入，调用引擎层，格式化输出               │
│    禁止: 不包含任何业务逻辑或执行逻辑                      │
└──────────────────────┬───────────────────────────────────┘
                       │ import
┌──────────────────────▼───────────────────────────────────┐
│  引擎层  (Engine)                                         │
│    runner.py         步骤循环引擎，执行工作流               │
│    composer.py       LLM 工作流生成（需求→WorkflowModel）  │
│    validator.py      确定性规则校验（结构/依赖/安全）       │
│    models.py         Pydantic 数据模型定义                  │
│    skill_registry.py Skill 注册表与 SkillCard 生成         │
│    skills/           各 Skill 实现                         │
│                                                          │
│    职责: 工作流的生成、校验、执行                          │
│    禁止: 不直接操作 SQLite 或 LLM API                     │
└──────────────────────┬───────────────────────────────────┘
                       │ import
┌──────────────────────▼───────────────────────────────────┐
│  基础设施层  (Infra)                                      │
│    state_store.py    SQLite 状态持久化                      │
│    llm_client.py     LLM API 封装（instructor + SDK）      │
│    config.py         pydantic-settings 配置加载             │
│                                                          │
│    职责: 外部依赖适配（数据库、LLM API、文件系统）         │
│    禁止: 不 import 引擎层或入口层的任何模块                │
└──────────────────────────────────────────────────────────┘
```

### 3.2 依赖规则

```
入口层 → 引擎层 → 基础设施层（单向，不允许反向 import）

具体允许的 import 关系:
  cli.py       → runner, composer, validator, models, config, display
  display.py   → models (仅用于类型引用)
  runner.py    → validator, skill_registry, models, state_store, config
  composer.py  → models, skill_registry, llm_client, config
  validator.py → models (零外部依赖，纯逻辑)
  skill_registry.py → skills/*, models
  skills/*     → models, llm_client (各 Skill 可调用 LLM)
  state_store.py  → models (仅用于类型引用)
  llm_client.py   → config
  config.py       → 无内部依赖

# 阶段 5 启用 HTTP 触发后追加（见 §17）:
  server.py       → runner, workflow_io, skill_registry, models, state_store, config（无 Typer；
                    不向引擎层反向暴露 FastAPI）
```

### 3.3 双入口：CLI 与 HTTP 服务（阶段 5）

阶段 5 引入 **`myflow serve`**（`server.py`，FastAPI + uvicorn）后，系统存在**两条并列入口**，均只做「解析请求 → 调用引擎层」，**共用同一套 `Runner` / `Validator` / Skill**，与 §3.1「入口层不包含业务逻辑」一致。

```
                    外部系统 / CI                     终端用户
                     （Webhook、定时任务）              （交互式调试）
                           │                                  │
                           ▼                                  ▼
              ┌────────────────────────┐       ┌────────────────────────┐
              │ server.py               │       │ cli.py                  │
              │ uvicorn → FastAPI       │       │ Typer → run/generate…   │
              │ POST /run/{workflow}    │       │ myflow run *.yaml …     │
              │ GET  /runs/{run_id} …   │       │ display.py 格式化输出    │
              └───────────┬────────────┘       └────────────┬────────────┘
                          │                                   │
                          └────────────────┬──────────────────┘
                                           │
                                           ▼
               ┌───────────────────────────────────────────────────────────┐
               │ 引擎层（与 §3.1 相同）：Runner · Composer · Validator · Skill │
               └───────────────────────────────────────────────────────────┘
                                           │
                                           ▼
               ┌───────────────────────────────────────────────────────────┐
               │ 基础设施层：StateStore · LLMClient · Config · 本地文件系统     │
               └───────────────────────────────────────────────────────────┘
```

**约定**

- **`server.py` 与 `cli.py` 平级**：同属入口形态，互不 import；二者均可 import `runner`/`state_store`。  
- **Skills 不关心请求来源**：例如 `http_request`（§17.2）在工作流 YAML 中出现时，无论从 CLI 还是 `/run` 触发，执行路径一致。  
- **未启用阶段 5**：仓库可无 `server.py`，仅 CLI 上图右侧一支。

---

## 4. 工作流格式规范 (YAML DSL)

### 4.1 设计决策

使用 YAML 作为工作流定义格式，替代 Markdown DSL。理由如下:

- YAML 有标准解析器（ruamel.yaml），无需自写正则 Parser。
- YAML 结构清晰，字段即文档，人类可读可编辑。
- LLM 生成 YAML 比生成特定格式的 Markdown 更稳定。
- YAML 与 Pydantic 的 dict 形式天然兼容。

### 4.2 完整字段规范

```yaml
# ─── 文件头元数据 ───
name: string                    # 必填。工作流唯一名称，snake_case
description: string             # 必填。一句话描述工作流目标
version: string                 # 可选。语义化版本号，默认 "1.0"

# ─── 工作流级输入输出 ───
inputs:                         # 必填。工作流启动时需要的外部参数
  <param_name>:                 # 参数名，snake_case
    type: string                # 参数类型: string / integer / float / boolean / object / array
    description: string         # 参数描述
    required: boolean           # 是否必填，默认 true
    default: any                # 默认值（仅 required=false 时有意义）

outputs:                        # 必填。工作流最终输出
  <param_name>:
    type: string
    description: string

# ─── 步骤列表 ───
steps:                          # 必填。至少一个步骤
  - id: integer                 # 必填。步骤唯一 ID，从 1 开始递增
    name: string                # 必填。步骤名称，人类可读
    action: string              # 必填。技能名称，必须在 SkillRegistry 白名单中
    description: string         # 可选。步骤详细描述，会注入到 LLM Skill 的 prompt 中

    inputs:                     # 可选。步骤输入变量映射（值的合法形态见 §4.2.1）
      <param_name>: string       # 纯变量引用 / 字符串内插模板 / 字面量（见 §4.2.1）

    outputs:                    # 必填。dict：key=上下文变量名，value=技能输出模型字段名（须逐字一致）
      <context_var>: <skill_output_field>

    condition: string           # 可选。simpleeval 表达式，为 false 时跳过本步骤
    on_fail: integer            # 可选。失败时跳转目标步骤 ID，必须 < 当前 id
    max_retries: integer        # 可选。on_fail 最大重试次数，默认 3，上限 5

    # ─── 子工作流专用字段 ───
    workflow: string            # 仅 action=sub_workflow 时必填。子工作流文件路径
```

### 4.2.1 `step.inputs` 模板语法（Runner 基础能力）

`Runner` 在调用技能前对 `step.inputs` 的每个值做**模板解析**。以下为**仅有的三类合法写法**（Composer 与手写 YAML 均须遵守；亦为 `composer_system.md` 输出规则的阶段 1 基线）：

1. **纯变量引用**  
   整个字符串**恰好**为 `{{variable_name}}`（仅一对花括号、无前后缀空白以外的字符）。  
   **语义**：从当前 `context` 取出 `variable_name` 的**原始值**，**保留 Python 类型**（如 `dict`/`list`/`int` 等），不强制 `str()`。缺失键时视为空字符串 `""`（与实现保持一致，文档可约定）。

2. **字符串内插**  
   字符串中可含**一处或多处**`{{variable_name}}`子串，且**整段**不满足「情况 1」的 `fullmatch`。  
   **语义**：将每个占位符替换为 `str(context.get(variable_name, ""))` 后拼接为**单一字符串**；**不**对整段结果再尝试「整段变量引用」解析（避免循环）。

3. **字面量**  
   不含 `{{...}}` 模板语法的普通字符串（或 YAML 解析得到的标量）。**原样**传入技能（在解析阶段不变）。

**设计动机（真实缺陷）**：仅支持「情况 1」会导致 Composer 合理生成的  
`instruction: "将以下内容翻译为{{target_language}}：{{source_text}}"`  
无法解析，占位符原样进入 `llm_*` / `file_writer`，用户产物中出现大量 `{{...}}`。因此**字符串内插为 Runner 的必选基础能力**，不是可选增强。

**与单花括号**：历史 YAML 若整段为 `{var}` 形式，Runner 可保留兼容（见 §7.3 实现说明）；Composer **应统一生成双花括号**。

### 4.3 完整示例

```yaml
name: analyze_csv_trends
description: 读取CSV文件，用LLM分析数据趋势，生成摘要报告并写入文件
version: "1.0"

inputs:
  csv_path:
    type: string
    description: CSV 文件路径
  output_path:
    type: string
    description: 报告输出路径

outputs:
  report_path:
    type: string
    description: 生成的报告文件路径

steps:
  - id: 1
    name: 读取CSV文件
    action: file_reader
    inputs:
      file_path: "{{csv_path}}"
    outputs:
      file_content: file_content

  - id: 2
    name: 分析数据趋势
    action: llm_analyze
    description: 分析CSV数据中的趋势、异常值和关键指标，输出结构化分析结论
    inputs:
      content: "{{file_content}}"
      instruction: "分析以下CSV数据的趋势、异常值和关键指标，给出结论"
    outputs:
      analysis_result: analysis_result
      confidence: confidence

  - id: 3
    name: 生成报告文件
    action: file_writer
    inputs:
      file_path: "{{output_path}}"
      content: "{{analysis_result}}"
    outputs:
      report_path: report_path
      bytes_written: bytes_written

  - id: 4
    name: 验证报告质量
    action: llm_verify
    description: 验证生成的分析报告是否完整、逻辑自洽、涵盖了关键趋势
    inputs:
      artifact: "{{analysis_result}}"
      criteria: "报告必须包含趋势分析、异常值识别和关键指标总结"
    outputs:
      verify_result: verify_result
      passed: passed
    on_fail: 2
    max_retries: 3
```

### 4.4 字段校验规则（由 Validator 执行）

| 规则编号 | 规则描述 | 错误码 |
|---------|---------|--------|
| R01 | steps 列表不能为空 | `EMPTY_STEPS` |
| R02 | step.id 必须唯一且为正整数 | `DUPLICATE_STEP_ID` |
| R03 | step.action 必须在 SkillRegistry 白名单中 | `UNKNOWN_ACTION` |
| R04 | step.outputs 至少声明一个映射项（非空 dict） | `MISSING_OUTPUT` |
| R04b | step.outputs 的 value 必须是该技能输出模型中存在的字段名 | `INVALID_OUTPUT_FIELD` |
| R05 | step.inputs 中引用的变量必须在前序步骤 outputs 的 **key** 中已声明，或在工作流 inputs 中已定义 | `UNBOUND_VARIABLE` |
| R06 | step.on_fail 目标必须 < 当前 step.id（只能向前跳） | `INVALID_ON_FAIL` |
| R07 | step.on_fail 目标 step.id 必须实际存在 | `ON_FAIL_TARGET_MISSING` |
| R08 | step.max_retries 不能超过 5 | `EXCESSIVE_RETRIES` |
| R09 | step.inputs 中不能残留未替换的模板语法（如 `{{}}` 空引用） | `TEMPLATE_RESIDUE` |
| R10 | step.description 和 step.name 中出现危险关键词时记录警告 | `DANGER_KEYWORD` |
| R11 | action=sub_workflow 时，workflow 字段必填 | `MISSING_WORKFLOW_PATH` |
| R12 | 当 `action=file_reader` 且对应输入字段在 SkillCard 上为「单文件路径」语义时，若模板解析后的值**疑似**逗号拼接的多个路径，Validator 给出 **warning**（启发式，不误杀合法路径名中含逗号的极端情况） | `MULTI_PATH_SUSPICION` |
| R13 | `action=http_request` 且 `url` 为**字面量**（非整段 `{{var}}` 引用）时，URL 不得匹配内网 / 本地 / `file://` 等被策略禁止的模式（见 §17.2、§12.1） | `BLOCKED_URL` |

---

## 5. 数据模型定义 (Pydantic)

### 5.1 核心模型

以下为系统全部 Pydantic 数据模型的完整定义。这些模型是全链路类型化的基础。

```python
# src/myflow/engine/models.py

from __future__ import annotations
from typing import Any, Literal, Optional
from pydantic import BaseModel, Field, field_validator


# ─── 工作流定义模型 ───

class ParamSpec(BaseModel):
    """工作流级输入/输出参数规格"""
    type: str = "string"
    description: str = ""
    required: bool = True
    default: Any = None


class WorkflowStep(BaseModel):
    """工作流步骤定义"""
    id: int
    name: str
    action: str
    description: str = ""
    inputs: dict[str, str] = Field(default_factory=dict)
    outputs: dict[str, str] = Field(default_factory=dict)
    # key=上下文变量名；value=技能输出模型字段名（须与技能定义一致）
    condition: str | None = None
    on_fail: int | None = None
    max_retries: int = 3
    workflow: str | None = None  # 仅 sub_workflow 使用

    @field_validator("max_retries")
    @classmethod
    def cap_retries(cls, v: int) -> int:
        return min(v, 5)

    @field_validator("on_fail")
    @classmethod
    def on_fail_must_be_positive(cls, v: int | None) -> int | None:
        if v is not None and v < 1:
            return None
        return v


class WorkflowModel(BaseModel):
    """工作流完整定义 —— 系统内部唯一真理"""
    name: str
    description: str
    version: str = "1.0"
    inputs: dict[str, ParamSpec] = Field(default_factory=dict)
    outputs: dict[str, ParamSpec] = Field(default_factory=dict)
    steps: list[WorkflowStep] = Field(default_factory=list)


# ─── 校验报告模型 ───

class ValidationIssue(BaseModel):
    """单条校验问题"""
    code: str               # 错误码，如 "UNKNOWN_ACTION"
    message: str            # 人类可读描述
    step_id: int | None = None  # 关联步骤（如有）
    suggestion: str = ""    # 修复建议（回流给 LLM）

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

    def error_summary(self) -> str:
        """格式化错误信息，用于回流给 LLM"""
        lines = []
        for e in self.errors:
            loc = f"step {e.step_id}" if e.step_id else "workflow"
            lines.append(f"[{e.code}] {loc}: {e.message}")
            if e.suggestion:
                lines.append(f"  修复建议: {e.suggestion}")
        return "\n".join(lines)


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
    step_results: list[StepResult] = Field(default_factory=list)
    final_context: dict[str, Any] = Field(default_factory=dict)
    total_duration_ms: int = 0
    error: str | None = None
```

---

## 6. Skill 体系设计

### 6.1 设计目标

解决"LLM 生成不存在技能"的核心问题。方案包含两个层面:

- **代码层**: Skill 基类 + SkillRegistry 白名单，引擎层硬校验。
- **Prompt 层**: SkillCard 自动注入 LLM Prompt，让 LLM 在生成时就知道有哪些技能可用。

### 6.2 Skill 基类

```python
# src/myflow/skills/base.py

from abc import ABC, abstractmethod
from pydantic import BaseModel
from myflow.engine.models import SkillCard


class Skill(ABC):
    """所有技能的抽象基类。每个技能必须实现此接口。"""

    # ─── 元数据声明（子类必须覆盖） ───
    name: str = ""                     # 唯一标识，与工作流 step.action 对应
    description: str = ""              # 一句话描述
    when_to_use: str = ""              # 适用场景
    do_not_use_when: str = ""          # 不适用场景
    idempotent: bool = True            # 是否幂等（非幂等技能不自动重试）

    # ─── 类型声明（子类必须覆盖） ───
    input_model: type[BaseModel] = BaseModel    # 输入 Pydantic 模型
    output_model: type[BaseModel] = BaseModel   # 输出 Pydantic 模型

    @abstractmethod
    async def execute(self, inputs: BaseModel, context: dict) -> BaseModel:
        """
        执行技能。
        - inputs: 已校验的 Pydantic 输入对象
        - context: 当前运行上下文（只读，不应修改）
        - 返回: Pydantic 输出对象
        - 异常: 执行失败时抛出 SkillExecutionError
        """
        ...

    def to_skill_card(self) -> SkillCard:
        """从类声明自动生成 SkillCard 元数据。"""
        input_fields = {}
        for field_name, field_info in self.input_model.model_fields.items():
            type_str = str(field_info.annotation.__name__) if hasattr(field_info.annotation, '__name__') else str(field_info.annotation)
            required = field_info.is_required()
            input_fields[field_name] = f"{type_str}, {'必填' if required else '可选'}"

        output_fields = {}
        for field_name, field_info in self.output_model.model_fields.items():
            type_str = str(field_info.annotation.__name__) if hasattr(field_info.annotation, '__name__') else str(field_info.annotation)
            output_fields[field_name] = type_str

        return SkillCard(
            name=self.name,
            description=self.description,
            when_to_use=self.when_to_use,
            do_not_use_when=self.do_not_use_when,
            input_fields=input_fields,
            output_fields=output_fields,
            idempotent=self.idempotent,
        )
```

### 6.3 内置 Skill 清单

系统初始版本包含以下 Skill，每个 Skill 对应一个 Python 文件:

| Skill 名称 | 文件 | 功能 | 幂等 |
|------------|------|------|------|
| `file_reader` | `skills/file_ops.py` | 读取**单个**本地文件内容（路径须为单文件；多文件见 `multi_file_reader`） | 是 |
| `multi_file_reader` | `skills/file_ops.py`（规划） | 按路径列表批量读取多个文件，返回路径到内容的映射 | 是 |
| `file_writer` | `skills/file_ops.py` | 将内容写入本地文件 | 否 |
| `llm_analyze` | `skills/llm_call.py` | 用 LLM 分析内容并返回结论 | 是 |
| `llm_generate` | `skills/llm_call.py` | 用 LLM 生成内容（文本/代码/报告） | 是 |
| `llm_verify` | `skills/llm_call.py` | 用 LLM 验证产物是否满足标准 | 是 |
| `sub_workflow` | `skills/sub_workflow.py` | 调用另一个已注册的子工作流 | 取决于子工作流 |
| `http_request` | `skills/http_request.py`（阶段 5） | 发送 HTTP 请求到外部 API，返回状态码与响应体 | **否**（`idempotent=False`） |

### 6.4 Skill 实现示例

```python
# src/myflow/skills/file_ops.py

from pydantic import BaseModel
from myflow.skills.base import Skill


class FileReaderInput(BaseModel):
    file_path: str

class FileReaderOutput(BaseModel):
    file_content: str

class FileReaderSkill(Skill):
    name = "file_reader"
    description = "读取本地文件内容，返回文本字符串"
    when_to_use = "需要读取文件、配置、模板等本地资源时"
    do_not_use_when = "写入或修改文件（使用 file_writer）"
    idempotent = True
    input_model = FileReaderInput
    output_model = FileReaderOutput

    async def execute(self, inputs: FileReaderInput, context: dict) -> FileReaderOutput:
        with open(inputs.file_path, "r", encoding="utf-8") as f:
            content = f.read()
        return FileReaderOutput(file_content=content)


class FileWriterInput(BaseModel):
    file_path: str
    content: str

class FileWriterOutput(BaseModel):
    report_path: str
    bytes_written: int

class FileWriterSkill(Skill):
    name = "file_writer"
    description = "将内容写入本地文件，返回写入路径和字节数"
    when_to_use = "需要保存生成的报告、代码、配置等到文件时"
    do_not_use_when = "读取文件（使用 file_reader）"
    idempotent = False   # 写操作非幂等，不自动重试
    input_model = FileWriterInput
    output_model = FileWriterOutput

    async def execute(self, inputs: FileWriterInput, context: dict) -> FileWriterOutput:
        with open(inputs.file_path, "w", encoding="utf-8") as f:
            written = f.write(inputs.content)
        return FileWriterOutput(report_path=inputs.file_path, bytes_written=written)
```

### 6.5 SkillRegistry

```python
# src/myflow/engine/skill_registry.py

from myflow.skills.base import Skill
from myflow.engine.models import SkillCard


class SkillNotFoundError(Exception):
    """未知技能，硬失败，不允许软跳过"""
    pass


class SkillRegistry:
    """技能注册表。启动时扫描所有 Skill 子类并注册。"""

    def __init__(self):
        self._skills: dict[str, Skill] = {}

    def register(self, skill: Skill) -> None:
        self._skills[skill.name] = skill

    def get(self, name: str) -> Skill:
        if name not in self._skills:
            raise SkillNotFoundError(
                f"未知技能 '{name}'。已注册技能: {list(self._skills.keys())}"
            )
        return self._skills[name]

    @property
    def skill_names(self) -> set[str]:
        return set(self._skills.keys())

    def all_skill_cards(self) -> list[SkillCard]:
        return [s.to_skill_card() for s in self._skills.values()]

    def skill_cards_as_prompt(self) -> str:
        """生成注入 Composer Prompt 的技能清单文本"""
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


def build_default_registry() -> SkillRegistry:
    """构建包含所有内置 Skill 的默认注册表"""
    from myflow.skills.file_ops import FileReaderSkill, FileWriterSkill  # MultiFileReaderSkill 阶段 3 加入
    from myflow.skills.llm_call import LLMAnalyzeSkill, LLMGenerateSkill, LLMVerifySkill
    from myflow.skills.sub_workflow import SubWorkflowSkill

    registry = SkillRegistry()
    for skill_cls in [
        FileReaderSkill,
        FileWriterSkill,
        LLMAnalyzeSkill,
        LLMGenerateSkill,
        LLMVerifySkill,
        SubWorkflowSkill,
    ]:
        registry.register(skill_cls())
    return registry
```

### 6.6 SkillCard 注入 Prompt 的机制

Composer 在构建 System Prompt 时，调用 `registry.skill_cards_as_prompt()` 将完整技能清单嵌入。LLM 看到的效果:

```
你是一个工作流生成器。根据用户需求生成 YAML 工作流。

## 可用技能清单

### file_reader
用途: 读取本地文件内容，返回文本字符串
适用: 需要读取文件、配置、模板等本地资源时
不适用: 写入或修改文件（使用 file_writer）
输入: file_path (str, 必填)
输出: file_content (str)
幂等: 是

### llm_analyze
用途: 用 LLM 分析文本内容并返回结构化结论
适用: 需要对内容做总结、分类、提取时
不适用: 纯机械的文本处理（用正则或脚本）
输入: content (str, 必填), instruction (str, 必填)
输出: result (str), confidence (float)
幂等: 是

[...其他技能...]

## 规则
- step.action 只能使用上述清单中的技能名称，不允许使用其他名称
- step.inputs 的字段名必须与技能的输入字段名完全一致
- step.outputs 为 dict：key 为写入上下文的变量名，value 为技能输出模型字段名（须存在于该技能的输出 schema 中）
```

---

## 7. 引擎层详细设计

### 7.1 Validator（确定性校验）

Validator 是引擎层的"判官"模块。它只消费 `WorkflowModel`，零 LLM 依赖，零 IO 操作，纯逻辑。

```python
# src/myflow/engine/validator.py

import re
from myflow.engine.models import WorkflowModel, ValidationReport

DANGER_KEYWORDS = [
    r"\brm\b", r"\brmdir\b", r"shutil\.rmtree",
    r"DROP\s+TABLE", r"DELETE\s+FROM",
    r"\bsubprocess\b", r"os\.system",
    r"\bshutdown\b", r"\breboot\b",
]


class WorkflowValidator:
    """
    确定性规则校验器。
    所有可由代码判定对错的规则集中在此类中，是系统中唯一的规则来源。
    """

    def validate(self, workflow: WorkflowModel, available_skills: set[str]) -> ValidationReport:
        report = ValidationReport()
        self._check_non_empty(workflow, report)
        self._check_unique_ids(workflow, report)
        self._check_actions(workflow, available_skills, report)
        self._check_outputs_declared(workflow, report)
        self._check_output_field_mapping(workflow, report)  # R04b: value 须为技能输出模型字段名
        self._check_variable_reachability(workflow, report)
        self._check_on_fail_targets(workflow, report)
        self._check_retries(workflow, report)
        self._check_template_residue(workflow, report)
        self._check_danger_keywords(workflow, report)
        self._check_sub_workflow_fields(workflow, report)
        return report

    def _check_non_empty(self, wf: WorkflowModel, r: ValidationReport):
        if not wf.steps:
            r.add_error("EMPTY_STEPS", "工作流必须至少包含一个步骤")

    def _check_unique_ids(self, wf: WorkflowModel, r: ValidationReport):
        seen = set()
        for step in wf.steps:
            if step.id in seen:
                r.add_error("DUPLICATE_STEP_ID", f"步骤 ID {step.id} 重复", step_id=step.id)
            seen.add(step.id)

    def _check_actions(self, wf: WorkflowModel, skills: set[str], r: ValidationReport):
        for step in wf.steps:
            if step.action not in skills:
                r.add_error(
                    "UNKNOWN_ACTION",
                    f"未知技能 '{step.action}'",
                    step_id=step.id,
                    suggestion=f"可用技能: {sorted(skills)}"
                )

    def _check_outputs_declared(self, wf: WorkflowModel, r: ValidationReport):
        for step in wf.steps:
            if not step.outputs:
                r.add_error("MISSING_OUTPUT", "步骤必须声明至少一个输出变量", step_id=step.id)

    def _check_output_field_mapping(self, wf: WorkflowModel, r: ValidationReport):
        """R04b: step.outputs 的每个 value 必须是该技能 output_model 上的字段名。"""
        # 实现时: 由 SkillRegistry 提供 action -> 合法输出字段集合，逐 step 校验。

    def _check_variable_reachability(self, wf: WorkflowModel, r: ValidationReport):
        """前向滚雪球算法: 检查每个步骤的 inputs 引用的变量是否已由前序步骤产出"""
        available: set[str] = set(wf.inputs.keys())
        for step in sorted(wf.steps, key=lambda s: s.id):
            for param_name, ref in step.inputs.items():
                var_name = ref.strip("{} ")
                if var_name and not var_name.startswith('"') and var_name not in available:
                    r.add_error(
                        "UNBOUND_VARIABLE",
                        f"变量 '{var_name}' 在步骤 {step.id} 中被引用，但未在前序步骤中产出",
                        step_id=step.id,
                        suggestion=f"当前可用变量: {sorted(available)}"
                    )
            available.update(step.outputs.keys())  # outputs 为 dict: key 写入上下文

    def _check_on_fail_targets(self, wf: WorkflowModel, r: ValidationReport):
        all_ids = {step.id for step in wf.steps}
        for step in wf.steps:
            if step.on_fail is not None:
                if step.on_fail not in all_ids:
                    r.add_error("ON_FAIL_TARGET_MISSING",
                                f"on_fail 目标步骤 {step.on_fail} 不存在", step_id=step.id)
                elif step.on_fail >= step.id:
                    r.add_error("INVALID_ON_FAIL",
                                f"on_fail 目标必须 < 当前步骤 ID (当前={step.id}, 目标={step.on_fail})",
                                step_id=step.id,
                                suggestion="on_fail 只能向前跳转，形成重试循环")

    def _check_retries(self, wf: WorkflowModel, r: ValidationReport):
        for step in wf.steps:
            if step.max_retries > 5:
                r.add_error("EXCESSIVE_RETRIES", f"max_retries 不能超过 5", step_id=step.id)

    def _check_template_residue(self, wf: WorkflowModel, r: ValidationReport):
        for step in wf.steps:
            for k, v in step.inputs.items():
                if v in ("{{}}",  "{{ }}", ""):
                    r.add_error("TEMPLATE_RESIDUE",
                                f"输入 '{k}' 包含空的模板引用", step_id=step.id)

    def _check_danger_keywords(self, wf: WorkflowModel, r: ValidationReport):
        for step in wf.steps:
            text = f"{step.name} {step.description} {step.inputs} {step.outputs}"
            for pattern in DANGER_KEYWORDS:
                if re.search(pattern, text, re.IGNORECASE):
                    r.add_warning("DANGER_KEYWORD",
                                  f"检测到危险关键词匹配: {pattern}", step_id=step.id)

    def _check_sub_workflow_fields(self, wf: WorkflowModel, r: ValidationReport):
        for step in wf.steps:
            if step.action == "sub_workflow" and not step.workflow:
                r.add_error("MISSING_WORKFLOW_PATH",
                            "action 为 sub_workflow 时必须指定 workflow 字段", step_id=step.id)
```

### 7.2 Composer（LLM 工作流生成）

```python
# src/myflow/engine/composer.py

from myflow.engine.models import WorkflowModel
from myflow.engine.skill_registry import SkillRegistry
from myflow.infra.llm_client import LLMClient
from myflow.infra.config import AppConfig

SYSTEM_PROMPT_TEMPLATE = """你是 MyFlow 工作流生成器。根据用户的自然语言需求，生成一个可执行的工作流定义。

{skill_cards}

## 输出规则
1. step.action 只能使用上述清单中列出的技能名称，禁止使用任何其他名称。
2. step.inputs 每个字段的值必须是以下三类之一（与 §4.2.1 / Runner 一致）：（1）整段纯引用 `"{{var}}"` 取 context 原始类型；（2）含 `"{{var}}"` 的字符串内插，替换为 str 后拼接；（3）无 `{{...}}` 的字面量。
3. step.outputs 为字典：key 为上下文变量名，value 为技能返回字段名（与 inputs 的映射对称，且 value 必须存在于该技能输出模型）。
4. 所有变量名使用 snake_case。
5. 如果某个步骤的产物需要质量验证，使用 llm_verify 并设置 on_fail 指向需要重新执行的步骤。
6. on_fail 目标步骤 ID 必须小于当前步骤 ID。

## few-shot 示例
{examples}
"""


class WorkflowComposer:
    """
    将自然语言需求转为 WorkflowModel。
    使用 instructor 强制 LLM 输出符合 Pydantic schema 的对象。
    """

    def __init__(self, llm_client: LLMClient, registry: SkillRegistry, config: AppConfig):
        self.llm = llm_client
        self.registry = registry
        self.config = config

    async def compose(
        self,
        requirement: str,
        prev_errors: list[str] | None = None,
        attempt: int = 1,
    ) -> WorkflowModel:
        system = SYSTEM_PROMPT_TEMPLATE.format(
            skill_cards=self.registry.skill_cards_as_prompt(),
            examples=self._load_examples(),
        )

        user_parts = [f"需求: {requirement}"]
        if prev_errors and attempt > 1:
            user_parts.append(f"\n上一次生成失败（第 {attempt} 次尝试），错误如下:\n" + "\n".join(prev_errors))
            user_parts.append("请根据以上错误修正工作流。")

        workflow = await self.llm.create_structured(
            response_model=WorkflowModel,
            system=system,
            user="\n".join(user_parts),
        )
        return workflow

    def _load_examples(self) -> str:
        """加载 few-shot 示例（从 prompts/examples/ 目录读取）"""
        # 实现略: 读取 YAML 示例文件并格式化为字符串
        return "（示例见 prompts/examples/ 目录）"
```

### 7.3 Runner（步骤循环引擎）

```python
# src/myflow/engine/runner.py（伪代码骨架，展示核心逻辑）

import time
from uuid import uuid4
from simpleeval import simple_eval, NameNotDefined
from myflow.engine.models import WorkflowModel, WorkflowStep, RunResult, StepResult
from myflow.engine.validator import WorkflowValidator
from myflow.engine.skill_registry import SkillRegistry, SkillNotFoundError
from myflow.infra.state_store import StateStore
from myflow.infra.config import AppConfig


class StepFailedError(Exception):
    pass


class Runner:
    """工作流执行引擎。遍历步骤列表，调用 Skill，管理状态。"""

    def __init__(self, registry: SkillRegistry, state_store: StateStore, config: AppConfig):
        self.registry = registry
        self.state_store = state_store
        self.config = config
        self.validator = WorkflowValidator()

    async def run(
        self,
        workflow: WorkflowModel,
        initial_context: dict | None = None,
        run_id: str | None = None,
    ) -> RunResult:
        run_id = run_id or uuid4().hex
        context = dict(initial_context or {})
        step_results: list[StepResult] = []
        retry_counts: dict[int, int] = {}
        start_time = time.monotonic()

        # ─── 校验 ───
        report = self.validator.validate(workflow, self.registry.skill_names)
        if not report.passed:
            return RunResult(
                run_id=run_id, workflow_name=workflow.name,
                status="failed", error=f"工作流校验失败:\n{report.error_summary()}"
            )

        # ─── 断点续传 ───
        context, start_index = await self._maybe_resume(run_id, context, workflow)

        # ─── 持久化初始状态 ───
        await self.state_store.save_run(run_id, workflow.name, "running", context)

        # ─── 主循环 ───
        i = start_index
        try:
            while i < len(workflow.steps):
                step = workflow.steps[i]
                step_start = time.monotonic()

                # 1. 条件求值
                if step.condition:
                    try:
                        if not simple_eval(step.condition, names=context):
                            step_results.append(StepResult(
                                step_id=step.id, step_name=step.name,
                                action=step.action, status="skipped"
                            ))
                            i += 1
                            continue
                    except NameNotDefined:
                        # 变量未就绪 = 条件不满足 = 跳过
                        step_results.append(StepResult(
                            step_id=step.id, step_name=step.name,
                            action=step.action, status="skipped"
                        ))
                        i += 1
                        continue

                # 2. 持久化锚点
                await self.state_store.save_checkpoint(run_id, step.id, context)

                # 3. 执行技能
                try:
                    skill = self.registry.get(step.action)
                    resolved_inputs = self._resolve_inputs(step, context)
                    validated_inputs = skill.input_model(**resolved_inputs)
                    output = await self._execute_with_retry(skill, validated_inputs, context)
                    output_dict = output.model_dump()
                    # 按 step.outputs 映射写入 context（非直接把技能字段名并入 context）
                    self._apply_step_outputs(step, output_dict, context)

                    step_results.append(StepResult(
                        step_id=step.id, step_name=step.name, action=step.action,
                        status="success", outputs=output_dict,
                        duration_ms=int((time.monotonic() - step_start) * 1000)
                    ))
                    await self.state_store.save_step(run_id, step.id, "success", output_dict, context)

                except SkillNotFoundError:
                    raise  # 未知技能，硬失败，不重试

                except Exception as e:
                    # on_fail 重试逻辑
                    if step.on_fail is not None:
                        retry_counts[step.id] = retry_counts.get(step.id, 0) + 1
                        if retry_counts[step.id] <= step.max_retries:
                            context["_prev_error"] = str(e)
                            context["_attempt"] = retry_counts[step.id]
                            target_index = self._find_step_index(workflow, step.on_fail)
                            step_results.append(StepResult(
                                step_id=step.id, step_name=step.name, action=step.action,
                                status="failed", error=str(e),
                                duration_ms=int((time.monotonic() - step_start) * 1000)
                            ))
                            i = target_index
                            continue
                    raise StepFailedError(f"Step {step.id} ({step.name}) 失败: {e}") from e

                i += 1

        except Exception as e:
            await self.state_store.save_run(run_id, workflow.name, "failed", context)
            return RunResult(
                run_id=run_id, workflow_name=workflow.name, status="failed",
                step_results=step_results, final_context=context,
                error=str(e),
                total_duration_ms=int((time.monotonic() - start_time) * 1000)
            )

        # ─── 完成 ───
        await self.state_store.save_run(run_id, workflow.name, "completed", context)
        return RunResult(
            run_id=run_id, workflow_name=workflow.name, status="completed",
            step_results=step_results, final_context=context,
            total_duration_ms=int((time.monotonic() - start_time) * 1000)
        )

    def _resolve_inputs(self, step: WorkflowStep, context: dict) -> dict:
        """解析 step.inputs：支持整段变量引用（保留类型）与字符串内插（见 §4.2.1）。"""
        resolved = {}
        for key, ref in step.inputs.items():
            resolved[key] = self._resolve_template_value(ref, context)
        return resolved

    def _resolve_template_value(self, raw: object, context: dict) -> object:
        """三类值：非 str 原样返回；整段 {{var}} 取 context 原始值；否则对子串 {{var}} 做 str 替换。"""
        import re
        if not isinstance(raw, str):
            return raw
        s = raw.strip()
        m = re.fullmatch(r"\{\{(\s*[\w]+\s*)\}\}", s)
        if m:
            return context.get(m.group(1).strip(), "")
        m_single = re.fullmatch(r"\{([A-Za-z_][\w]*)\}", s)
        if m_single:
            return context.get(m_single.group(1), "")
        if "{{" in raw and "}}" in raw:

            def replacer(mm: re.Match) -> str:
                return str(context.get(mm.group(1).strip(), ""))

            return re.sub(r"\{\{(\s*[\w]+\s*)\}\}", replacer, raw)
        return raw

    def _apply_step_outputs(
        self, step: WorkflowStep, output_dict: dict, context: dict
    ) -> None:
        """按 step.outputs 将技能输出字段映射到上下文变量名。"""
        for ctx_name, skill_field in (step.outputs or {}).items():
            context[ctx_name] = output_dict[skill_field]

    async def _execute_with_retry(self, skill, inputs, context):
        """对幂等技能使用 tenacity 重试，非幂等技能不重试"""
        if skill.idempotent:
            from tenacity import AsyncRetrying, stop_after_attempt, wait_exponential
            async for attempt in AsyncRetrying(
                stop=stop_after_attempt(3),
                wait=wait_exponential(multiplier=1, max=10),
                reraise=True,
            ):
                with attempt:
                    return await skill.execute(inputs, context)
        else:
            return await skill.execute(inputs, context)

    async def _maybe_resume(self, run_id, context, workflow):
        """尝试从 StateStore 恢复断点"""
        saved = await self.state_store.load_run(run_id)
        if saved and saved.get("status") == "running":
            context.update(saved.get("context", {}))
            resume_step_id = saved.get("current_step_id", 1)
            idx = self._find_step_index(workflow, resume_step_id)
            return context, idx
        return context, 0

    def _find_step_index(self, workflow: WorkflowModel, step_id: int) -> int:
        for i, step in enumerate(workflow.steps):
            if step.id == step_id:
                return i
        raise ValueError(f"步骤 ID {step_id} 不存在")
```

---

## 8. 基础设施层详细设计

### 8.1 LLMClient

```python
# src/myflow/infra/llm_client.py

import instructor
from anthropic import AsyncAnthropic
from openai import AsyncOpenAI
from pydantic import BaseModel
from myflow.infra.config import AppConfig


class LLMClient:
    """
    LLM 调用封装。使用 instructor 库将 LLM 输出强制转为 Pydantic 对象。
    instructor 的核心能力:
    - 自动将 Pydantic schema 注入 LLM 请求
    - LLM 返回的文本自动 parse 为 Pydantic 对象
    - 如果 parse 失败（格式不对），自动将 ValidationError 发给 LLM 重试
    - 最多重试 max_retries 次
    """

    def __init__(self, config: AppConfig):
        self.config = config
        if config.llm_provider == "anthropic":
            self._client = instructor.from_anthropic(AsyncAnthropic(api_key=config.llm_api_key))
        elif config.llm_provider == "openai":
            self._client = instructor.from_openai(AsyncOpenAI(api_key=config.llm_api_key))
        else:
            raise ValueError(f"不支持的 LLM 提供商: {config.llm_provider}")

    async def create_structured(
        self,
        response_model: type[BaseModel],
        system: str,
        user: str,
        max_retries: int = 2,
    ) -> BaseModel:
        """
        调用 LLM 并返回类型化的 Pydantic 对象。
        instructor 在 parse 失败时会自动重试，
        并将 Pydantic ValidationError 的详细信息发给 LLM 帮助其修正输出。
        """
        result = await self._client.chat.completions.create(
            model=self.config.llm_model,
            response_model=response_model,
            max_retries=max_retries,
            messages=[
                {"role": "system", "content": system},
                {"role": "user", "content": user},
            ],
            temperature=self.config.llm_temperature,
        )
        return result

    async def create_text(self, system: str, user: str) -> str:
        """普通文本 LLM 调用（用于 Skill 内部）"""
        if self.config.llm_provider == "anthropic":
            raw = AsyncAnthropic(api_key=self.config.llm_api_key)
            resp = await raw.messages.create(
                model=self.config.llm_model,
                max_tokens=4096,
                system=system,
                messages=[{"role": "user", "content": user}],
            )
            return resp.content[0].text
        elif self.config.llm_provider == "openai":
            raw = AsyncOpenAI(api_key=self.config.llm_api_key)
            resp = await raw.chat.completions.create(
                model=self.config.llm_model,
                messages=[
                    {"role": "system", "content": system},
                    {"role": "user", "content": user},
                ],
            )
            return resp.choices[0].message.content
```

### 8.2 StateStore

```python
# src/myflow/infra/state_store.py（接口定义）

import json
import aiosqlite
from typing import Any


class StateStore:
    """
    SQLite 状态持久化。所有数据以 JSON 存储。
    表结构:
      runs(run_id, workflow_name, status, current_step_id, context_json, updated_at)
      steps(run_id, step_id, status, output_json, context_json, created_at)
    """

    def __init__(self, db_path: str = "myflow_state.db"):
        self.db_path = db_path

    async def init(self):
        """创建表（如不存在）"""
        async with aiosqlite.connect(self.db_path) as db:
            await db.execute("""
                CREATE TABLE IF NOT EXISTS runs (
                    run_id TEXT PRIMARY KEY,
                    workflow_name TEXT NOT NULL,
                    status TEXT NOT NULL,
                    current_step_id INTEGER DEFAULT 0,
                    context_json TEXT DEFAULT '{}',
                    updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
                )
            """)
            await db.execute("""
                CREATE TABLE IF NOT EXISTS steps (
                    run_id TEXT NOT NULL,
                    step_id INTEGER NOT NULL,
                    status TEXT NOT NULL,
                    output_json TEXT DEFAULT '{}',
                    context_json TEXT DEFAULT '{}',
                    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                    PRIMARY KEY (run_id, step_id, created_at)
                )
            """)
            await db.commit()

    async def save_run(self, run_id: str, workflow_name: str, status: str, context: dict):
        async with aiosqlite.connect(self.db_path) as db:
            await db.execute(
                "INSERT OR REPLACE INTO runs VALUES (?,?,?,?,?,CURRENT_TIMESTAMP)",
                (run_id, workflow_name, status, 0, json.dumps(context, ensure_ascii=False, default=str))
            )
            await db.commit()

    async def save_checkpoint(self, run_id: str, step_id: int, context: dict):
        async with aiosqlite.connect(self.db_path) as db:
            await db.execute(
                "UPDATE runs SET current_step_id=?, context_json=?, updated_at=CURRENT_TIMESTAMP WHERE run_id=?",
                (step_id, json.dumps(context, ensure_ascii=False, default=str), run_id)
            )
            await db.commit()

    async def save_step(self, run_id: str, step_id: int, status: str, output: dict, context: dict):
        async with aiosqlite.connect(self.db_path) as db:
            await db.execute(
                "INSERT INTO steps VALUES (?,?,?,?,?,CURRENT_TIMESTAMP)",
                (run_id, step_id, status,
                 json.dumps(output, ensure_ascii=False, default=str),
                 json.dumps(context, ensure_ascii=False, default=str))
            )
            await db.commit()

    async def load_run(self, run_id: str) -> dict | None:
        async with aiosqlite.connect(self.db_path) as db:
            db.row_factory = aiosqlite.Row
            async with db.execute("SELECT * FROM runs WHERE run_id=?", (run_id,)) as cursor:
                row = await cursor.fetchone()
                if row:
                    return {
                        "run_id": row["run_id"],
                        "workflow_name": row["workflow_name"],
                        "status": row["status"],
                        "current_step_id": row["current_step_id"],
                        "context": json.loads(row["context_json"]),
                    }
        return None

    async def list_runs(self, limit: int = 20) -> list[dict]:
        async with aiosqlite.connect(self.db_path) as db:
            db.row_factory = aiosqlite.Row
            async with db.execute(
                "SELECT run_id, workflow_name, status, updated_at FROM runs ORDER BY updated_at DESC LIMIT ?",
                (limit,)
            ) as cursor:
                return [dict(row) async for row in cursor]

    async def load_steps(self, run_id: str) -> list[dict]:
        async with aiosqlite.connect(self.db_path) as db:
            db.row_factory = aiosqlite.Row
            async with db.execute(
                "SELECT step_id, status, output_json, created_at FROM steps WHERE run_id=? ORDER BY created_at",
                (run_id,)
            ) as cursor:
                return [dict(row) async for row in cursor]
```

### 8.3 Config

```python
# src/myflow/infra/config.py

from pydantic_settings import BaseSettings


class AppConfig(BaseSettings):
    """
    应用配置。按优先级从高到低加载:
    1. 环境变量
    2. .env 文件
    3. 默认值
    """
    # LLM 配置
    llm_provider: str = "anthropic"           # anthropic / openai
    llm_model: str = "claude-sonnet-4-20250514"
    llm_api_key: str = ""
    llm_temperature: float = 0.3

    # 存储配置
    db_path: str = "myflow_state.db"
    workflows_dir: str = "workflows"

    # 执行配置
    max_global_retries: int = 5       # 单个工作流执行的全局最大重试总数
    default_step_retries: int = 3     # step.max_retries 默认值

    model_config = {"env_prefix": "MYFLOW_", "env_file": ".env"}
```

---

## 9. CLI 设计

### 9.1 命令结构

```
myflow — AI 工作流生成与执行引擎

用法:
  myflow <command> [options]

核心命令:
  run <workflow_path> [--input key=value ...]   执行指定工作流
  generate <requirement> [--output path]         根据自然语言生成工作流
  validate <workflow_path>                       校验工作流定义

工作流目录命令（仅依赖 YAML 元数据，扫描配置中的 workflows 目录）:
  list-workflows                               列出目录下全部 .yaml 工作流摘要（名称、描述、步骤数）
  show <name_or_path>                          展示单个工作流的输入/输出契约、步骤列表、on_fail 说明与 run 用法示例

管理命令（运行记录，阶段三）:
  list [--limit N]             列出最近 N 次运行记录
  logs <run_id>                查看指定运行的详细日志
  status <run_id>              查看指定运行的状态

服务命令（阶段五，见 §17）:
  serve [--host HOST] [--port PORT]   启动 HTTP API（FastAPI + uvicorn），供外部系统触发工作流

全局选项:
  --verbose / -v               详细输出模式（按子命令定义）
  --quiet / -q                 静默模式（仅输出结果）
  --model <model_name>         覆盖默认 LLM 模型
  --config <path>              指定配置文件路径
  --help / -h                  显示帮助信息
```

### 9.2 CLI 实现骨架

```python
# src/myflow/cli.py

import asyncio
import typer
from pathlib import Path
from rich.console import Console
from myflow.display import Display

app = typer.Typer(
    name="myflow",
    help="AI 工作流生成与执行引擎",
    no_args_is_help=True,
)
console = Console()
display = Display(console)


@app.command()
def run(
    workflow_path: Path = typer.Argument(..., help="工作流 YAML 文件路径"),
    inputs: list[str] = typer.Option([], "--input", "-i", help="输入参数 key=value"),
    verbose: bool = typer.Option(False, "--verbose", "-v"),
    run_id: str | None = typer.Option(None, "--resume", help="恢复指定 run_id 的中断执行"),
):
    """执行指定工作流"""
    asyncio.run(_run_workflow(workflow_path, inputs, verbose, run_id))


@app.command()
def generate(
    requirement: str = typer.Argument(..., help="自然语言需求描述"),
    output: Path = typer.Option(None, "--output", "-o", help="输出文件路径"),
    verbose: bool = typer.Option(False, "--verbose", "-v"),
    execute: bool = typer.Option(False, "--run", help="生成后立即执行"),
):
    """根据自然语言生成工作流"""
    asyncio.run(_generate_workflow(requirement, output, verbose, execute))


@app.command()
def validate(
    workflow_path: Path = typer.Argument(..., help="工作流 YAML 文件路径"),
):
    """校验工作流定义"""
    asyncio.run(_validate_workflow(workflow_path))


@app.command(name="list-workflows")
def list_workflows():
    """扫描 workflows 目录，列出可用工作流（YAML 元数据）"""
    asyncio.run(_list_workflows())


@app.command()
def show(
    name_or_path: str = typer.Argument(..., help="工作流文件名（无后缀）、相对路径或绝对路径"),
):
    """展示工作流详细用法（输入输出、步骤、重试提示、run 示例）"""
    asyncio.run(_show_workflow_usage(name_or_path))


@app.command(name="list")
def list_runs(
    limit: int = typer.Option(20, "--limit", "-n"),
):
    """列出最近运行记录"""
    asyncio.run(_list_runs(limit))


@app.command()
def logs(
    run_id: str = typer.Argument(..., help="运行 ID"),
):
    """查看指定运行的详细日志"""
    asyncio.run(_show_logs(run_id))


@app.command()
def status(
    run_id: str = typer.Argument(..., help="运行 ID"),
):
    """查看指定运行的状态"""
    asyncio.run(_show_status(run_id))
```

### 9.3 Display 模块（Rich 输出规范）

```python
# src/myflow/display.py —— 终端输出格式化

from rich.console import Console
from rich.table import Table
from rich.panel import Panel
from rich.progress import Progress, SpinnerColumn, TextColumn, TimeElapsedColumn
from rich.syntax import Syntax
from rich.text import Text
from pathlib import Path

from myflow.engine.models import RunResult, StepResult, ValidationReport, WorkflowModel


class Display:
    """所有 CLI 输出格式化集中在此类"""

    def __init__(self, console: Console):
        self.c = console

    # ─── 工作流执行 ───

    def run_progress(self) -> Progress:
        """创建执行进度条"""
        return Progress(
            SpinnerColumn(),
            TextColumn("[progress.description]{task.description}"),
            TimeElapsedColumn(),
            console=self.c,
        )

    def step_status(self, step: StepResult):
        """输出单步执行状态"""
        icon = {"success": "[green]✓[/]", "failed": "[red]✗[/]", "skipped": "[dim]⏭[/]"}
        self.c.print(f"  {icon.get(step.status, '?')} Step {step.step_id} │ {step.step_name} │ {step.action} │ {step.duration_ms}ms")

    def run_result(self, result: RunResult):
        """输出运行结果面板"""
        status_color = {"completed": "green", "failed": "red", "interrupted": "yellow"}
        color = status_color.get(result.status, "white")

        table = Table(show_header=True, header_style="bold", box=None, padding=(0, 1))
        table.add_column("Step", style="dim", width=6)
        table.add_column("Name", min_width=16)
        table.add_column("Action", style="cyan")
        table.add_column("Status", width=8)
        table.add_column("Time", justify="right", width=8)

        for sr in result.step_results:
            status_text = {"success": "[green]✓[/]", "failed": "[red]✗[/]", "skipped": "[dim]⏭[/]"}.get(sr.status, sr.status)
            table.add_row(str(sr.step_id), sr.step_name, sr.action, status_text, f"{sr.duration_ms}ms")

        panel = Panel(
            table,
            title=f"Run {result.run_id[:8]} — {result.workflow_name}",
            subtitle=f"[{color}]{result.status}[/] │ {result.total_duration_ms}ms",
            border_style=color,
        )
        self.c.print(panel)
        if result.error:
            self.c.print(f"\n[red]Error:[/] {result.error}")

    # ─── 工作流生成 ───

    def generation_start(self):
        self.c.print("\n[bold]⠋ 正在生成工作流...[/]\n")

    def generation_result(self, wf: WorkflowModel, path: str):
        self.c.print(f"[green]✓[/] 工作流已生成: [bold]{wf.name}[/] ({len(wf.steps)} 步骤)\n")
        for step in wf.steps:
            self.c.print(f"  {step.id}. {step.name:20s} → {step.action}")
        self.c.print(f"\n已保存至: [cyan]{path}[/]")

    # ─── 校验结果 ───

    def validation_result(self, report: ValidationReport):
        if report.passed:
            total = len(report.warnings)
            self.c.print(f"[green]✓ 校验通过[/] ({total} 条警告)" if total else "[green]✓ 校验通过[/]")
        else:
            self.c.print(f"[red]✗ 校验失败[/] ({len(report.errors)} 条错误)")
            for e in report.errors:
                loc = f"Step {e.step_id}" if e.step_id else "Workflow"
                self.c.print(f"  [red]✗[/] [{e.code}] {loc}: {e.message}")
                if e.suggestion:
                    self.c.print(f"    [dim]建议: {e.suggestion}[/]")
        for w in report.warnings:
            loc = f"Step {w.step_id}" if w.step_id else "Workflow"
            self.c.print(f"  [yellow]⚠[/] [{w.code}] {loc}: {w.message}")

    # ─── 工作流目录（YAML 元数据，阶段二 list-workflows / show） ───

    def workflows_directory_table(self, workflows_dir: str, rows: list[tuple[WorkflowModel, Path]]):
        """列出扫描结果：Name / Description / Steps（Rich Table）"""
        ...

    def workflow_detail(self, wf: WorkflowModel, yaml_rel_path: str):
        """单工作流用法页：标题与版本、描述、inputs/outputs 参数表、步骤列表（含 on_fail 文案）、run 示例"""
        ...

    # ─── 运行列表 ───

    def runs_table(self, runs: list[dict]):
        table = Table(title="运行记录", show_header=True, header_style="bold")
        table.add_column("Run ID", style="cyan", width=10)
        table.add_column("Workflow")
        table.add_column("Status")
        table.add_column("Time", justify="right")
        for r in runs:
            status = {"completed": "[green]completed[/]", "failed": "[red]failed[/]", "running": "[yellow]running[/]"}.get(r["status"], r["status"])
            table.add_row(r["run_id"][:8], r["workflow_name"], status, str(r["updated_at"]))
        self.c.print(table)
```

### 9.4 工作流发现与用法展示（`list-workflows` / `show`）

**目标**：不向 LLM 请求、不查数据库，仅扫描配置的工作流目录（默认 `AppConfig.workflows_dir`，一般为 `workflows/`），解析每个 `.yaml` 为 `WorkflowModel`，在终端输出人类可读的「目录索引」与「单文件说明书」。

**扫描规则**

- 使用 `Path(workflows_dir).glob("**/*.yaml")`（含子目录，如 `workflows/examples/hello_world.yaml`）。
- 解析方式与执行路径一致：优先复用 `workflow_io.load_workflow(path)`（内部 ruamel / Pydantic），保证与 `run` 加载同一套模型；便于后续若增加 YAML 预处理也不会分叉。
- 某一文件解析失败：该行跳过并打印一行 `[yellow]警告[/]`（路径 + 异常摘要），不中断对其他文件的扫描。

**`myflow list-workflows` 输出约定**

- 顶部标题：`可用工作流 ({workflows_dir}/)`。
- Rich `Table` 三列：**Name**（取 `WorkflowModel.name`，与文件名无强制一致但通常相同）、**Description**（`wf.description`，过长可截断并加省略）、**Steps**（`len(wf.steps)`）。
- 行顺序：可按文件路径字典序或按 `name` 排序（实现时固定一种并写入代码注释）。

**`myflow show <name_or_path>` 参数解析**

- 若为现有路径（文件存在）：直接加载该 YAML。
- 否则视为「逻辑名」：在 `workflows_dir` 下查找首个 **stem** 与参数匹配的 `.yaml`（例如 `analyze_csv_trends` → `analyze_csv_trends.yaml`）；若同名多条（多目录），优先最短路径或报错提示用户给出相对路径——实现选定一种策略并写入帮助文案。

**`workflow_detail` 排版要素（对应 Display.workflow_detail）**

1. 标题行：`{wf.name} v{wf.version}` + 一行空行 + `wf.description`。
2. **输入参数**：遍历 `wf.inputs`，列出 `name`、`ParamSpec.type`、必填（`required` → 文案 `(必填)` / `(可选)`）、`description`。
3. **输出**：遍历 `wf.outputs`，同上（无必填语义时可省略红色标记）。
4. **步骤**：按 `step.id` 排序输出；每行 `{id}. {name} → {action}`；若 `step.on_fail is not None`，追加 ` (失败→重试步骤{on_fail}, 最多{max_retries}次)`。
5. **用法**：根据 `wf.inputs` 的键生成 `myflow run <yaml_rel_path> \` 与若干 `--input key=<key>` 行；其中 `<yaml_rel_path>` 为相对仓库根或相对当前工作目录的展示路径（与 `show` 解析到的文件一致即可）。

**示例（终端效果）**

```bash
$ myflow list-workflows

 可用工作流 (workflows/)
┌──────────────────────┬─────────────────────────────────┬─────────┐
│ Name                 │ Description                     │ Steps   │
├──────────────────────┼─────────────────────────────────┼─────────┤
│ hello_world          │ 读取一个文件并把内容写入到另一个文件 │ 2       │
│ analyze_csv_trends   │ …                               │ 4       │
└──────────────────────┴─────────────────────────────────┴─────────┘
```

```bash
$ myflow show analyze_csv_trends

 analyze_csv_trends v1.0
 读取CSV文件，用LLM分析数据趋势，生成摘要报告并写入文件

 输入参数:
   csv_path     string   (必填)  CSV 文件路径
   output_path  string   (必填)  报告输出路径

 输出:
   report_path  string           生成的报告文件路径

 步骤:
   1. 读取CSV文件      → file_reader
   2. 分析数据趋势     → llm_analyze
   3. 生成报告文件     → file_writer
   4. 验证报告质量     → llm_verify   (失败→重试步骤2, 最多3次)

 用法:
   myflow run workflows/analyze_csv_trends.yaml \
     --input csv_path=<csv_path> \
     --input output_path=<output_path>
```

**与阶段划分的关系**：本节的 CLI 与 `Display.workflow_detail` / `workflows_directory_table` 在 **阶段二任务 2.6** 实现；阶段三中的 `myflow list`（运行记录）与本节 **list-workflows** 命名区分，避免混淆。

### 9.5 run 命令结果可见性（约定）

- **架构边界**：Skill 为纯粹的「输入 → Pydantic 输出」映射，**不假定**运行在终端里，也不承担「给用户看」的展示职责；终端是否打印、怎样排版属于 **CLI / Display**。
- **`--verbose`（基本能力，非可有可无）**：每步 **`success`** 且在 `step_status` 之后，将该步 `StepResult.outputs` **全部**按 `key → value` 打出（字符串化；单行过长可截断并标注省略）。**不按技能类型挑选字段**，避免重蹈「只为 LLM 挑主字段」的规则膨胀；用户自行判断是否关注。
- **默认收尾展示**：当 **`run` 总体 `completed`** 且**最后一步**的 `action != file_writer` 时，CLI 在 `run_result` 等汇总输出之后，**自动**追加一节（如标题「结果:」），展示**最后一步**的 `outputs`（可与 `step_output` 共用实现）。若工作流以写文件收尾，则认为「产物已在路径上」，不再重复刷屏。
- **Composer**：**不**为维护上述体验而单独增加「禁止生成 `file_writer`」类 Prompt；合理需求下模型本就不应画蛇添足。若生成的工作流仍需写文件而未提供路径，属于正常使用问题。
- **落地**：列入 **§15 阶段 3 任务 3.0**。

---

## 10. 全链路数据流

以下描述从用户输入到最终输出的完整数据流转路径。每个箭头处标注了数据的 Pydantic 类型。

### 10.1 生成链路

```
用户输入 (str: 自然语言需求)
    │
    ▼  cli.py 接收
requirement: str
    │
    ▼  composer.compose()
    │  ┌─ 构建 System Prompt（注入 SkillCards 文本）
    │  ├─ 构建 User Prompt（需求 + 可选的 prev_errors）
    │  └─ 调用 llm_client.create_structured(response_model=WorkflowModel)
    │       │
    │       ▼  instructor 内部流程
    │       LLM 生成文本 → instructor 自动 parse 为 WorkflowModel
    │       │  如果 parse 失败 → instructor 将 ValidationError 发给 LLM → 自动重试(最多2次)
    │       ▼
WorkflowModel (Pydantic 对象，已保证结构正确)
    │
    ▼  validator.validate(workflow, skill_names)
ValidationReport
    │  ├─ passed=True → 保存为 YAML 文件
    │  └─ passed=False → 错误回流:
    │       errors 格式化为 prev_errors 列表
    │       → composer.compose(requirement, prev_errors, attempt=2)
    │       → 最多重试 3 次
    │
    ▼  yaml.dump(workflow.model_dump())
YAML 文件 (持久化到 workflows/ 目录)
```

### 10.2 执行链路

```
YAML 文件路径 + 用户输入参数
    │
    ▼  加载并解析
WorkflowModel (Pydantic)
    │
    ▼  Runner.run(workflow, initial_context)
    │
    ├─ 校验: validator.validate() → ValidationReport
    │
    ├─ 断点续传: state_store.load_run(run_id) → 恢复 context
    │
    ├─ 主循环 (while i < len(steps)):
    │   │
    │   ├─ 条件求值: simpleeval(step.condition, context) → bool
    │   │
    │   ├─ 输入解析: step.inputs 中 {{var}} → context[var]
    │   │  结果类型: dict[str, Any]
    │   │
    │   ├─ 输入校验: skill.input_model(**resolved) → Pydantic 对象
    │   │  (如果字段缺失或类型错，此处直接报错)
    │   │
    │   ├─ 执行: skill.execute(inputs, context) → skill.output_model
    │   │  (返回 Pydantic 对象，保证输出结构正确)
    │   │
    │   ├─ 写回: context.update(output.model_dump())
    │   │
    │   ├─ 持久化: state_store.save_step(run_id, step_id, output, context)
    │   │
    │   └─ 失败处理:
    │       ├─ on_fail 存在且未超重试上限 → 跳转到目标步骤
    │       └─ 否则 → StepFailedError → 终止主循环
    │
    ▼
RunResult (Pydantic, 包含所有 StepResult)
    │
    ▼  display.run_result(result)
终端输出 (Rich 格式化面板)
```

---

## 11. 幻觉控制体系

系统通过两道防线控制 LLM 幻觉，每道防线独立有效。

### 11.1 第一道防线：instructor 结构化输出（出口拦截）

| 机制 | 防御的幻觉类型 | 实现方式 |
|------|--------------|---------|
| Pydantic Schema 强制 | 字段缺失、类型错误、结构不合法 | instructor 自动将 schema 注入 LLM 请求 |
| field_validator | action 不在白名单 | WorkflowStep 的 action 字段校验器 |
| 自动重试 | 首次生成格式不对 | instructor 将 ValidationError 发给 LLM 重新生成 |
| SkillCard Prompt 注入 | LLM 不知道有哪些技能 | Composer System Prompt 嵌入完整技能清单 |
| few-shot 示例 | LLM 不知道正确格式 | Composer System Prompt 嵌入示例工作流 |

### 11.2 第二道防线：Validator 静态校验（注册前拦截）

| 规则 | 防御的幻觉类型 | 错误回流 |
|------|--------------|---------|
| R03 UNKNOWN_ACTION | 幻觉技能名 | 回流可用技能列表 |
| R05 UNBOUND_VARIABLE | 引用不存在的变量 | 回流当前可用变量集合 |
| R06 INVALID_ON_FAIL | 无效的跳转目标 | 回流正确的跳转规则 |
| R09 TEMPLATE_RESIDUE | 模板语法残留 | 回流具体字段位置 |
| R13 `BLOCKED_URL`（阶段 5） | `http_request` 指向被禁止的字面量 URL | 回流可接受的公网 URL 或使用工作流 `inputs` 注入 |

### 11.3 错误回流机制

当 Validator 检测到错误时，错误信息通过 `ValidationReport.error_summary()` 格式化后注入到 Composer 的下一次调用中:

```
[UNKNOWN_ACTION] step 2: 未知技能 'analyze_data'
  修复建议: 可用技能: ['file_reader', 'file_writer', 'llm_analyze', 'llm_generate', 'llm_verify', 'sub_workflow', 'http_request']
[UNBOUND_VARIABLE] step 3: 变量 'analysis' 在步骤 3 中被引用，但未在前序步骤中产出
  修复建议: 当前可用变量: ['csv_path', 'output_path', 'file_content', 'result', 'confidence']
```

LLM 能据此精确修正。最多重试 3 次，超过则报错并输出最后一次的 ValidationReport。

---

## 12. 安全性与鲁棒性设计

### 12.1 安全措施

| 措施 | 实现位置 | 说明 |
|------|---------|------|
| simpleeval 沙盒 | Runner 条件求值 | 不使用 Python eval()，只允许安全表达式 |
| 危险关键词扫描 | Validator._check_danger_keywords | 检测 rm/rmdir/DROP TABLE 等危险操作 |
| 未知技能硬失败 | SkillRegistry.get() | 抛出 SkillNotFoundError，不软跳过 |
| 非幂等技能不自动重试 | Runner._execute_with_retry | idempotent=False 的技能失败后不自动重试 |
| JSON 序列化 | StateStore | 所有持久化数据用 JSON，不用 pickle |
| **`http_request` URL 静态策略** | Validator **R13**（§4.4、§17.2） | 字面量 URL 禁止内网 / 本地 / `file://` 等模式；防 SSRF 误用 |

### 12.2 鲁棒性措施

| 措施 | 实现位置 | 说明 |
|------|---------|------|
| 断点续传 | Runner._maybe_resume + StateStore | 按 run_id 恢复中断的执行 |
| 每步持久化 | Runner 主循环 | 每个 step 执行前后都写 StateStore |
| on_fail 重试上限 | WorkflowStep.max_retries | 最大 5 次，防止无限循环 |
| tenacity 指数退避 | Runner._execute_with_retry | 幂等技能的瞬时失败自动重试 |
| NameNotDefined 容错 | Runner 条件求值 | 变量未就绪时视为条件不满足，跳过步骤 |
| context 只存可序列化数据 | StateStore.save_* | `json.dumps(default=str)` 兜底 |

---

## 13. 测试策略与质量指标

### 13.1 测试分层

| 层级 | 范围 | 目标 | 依赖 |
|------|------|------|------|
| 单元测试 | 单个模块/函数 | 逻辑正确性 | 无外部依赖（mock LLM、mock DB） |
| 集成测试 | 多模块联动 | 接口兼容性 | SQLite in-memory，mock LLM |
| 端到端测试 | CLI → 引擎 → 输出 | 用户场景可用性 | 真实 LLM 调用（标记为 slow） |

### 13.2 必须覆盖的测试用例

```python
# ─── 单元测试: Validator ───
class TestValidator:
    def test_empty_steps_rejected(self):            # R01
    def test_duplicate_ids_rejected(self):           # R02
    def test_unknown_action_rejected(self):          # R03
    def test_missing_output_rejected(self):          # R04
    def test_unbound_variable_rejected(self):        # R05
    def test_invalid_on_fail_rejected(self):         # R06
    def test_on_fail_target_missing_rejected(self):  # R07
    def test_valid_workflow_passes(self):             # 正向用例
    def test_danger_keywords_warned(self):            # R10

# ─── 单元测试: SkillRegistry ───
class TestSkillRegistry:
    def test_registered_skill_found(self):
    def test_unknown_skill_raises(self):
    def test_skill_cards_generated(self):
    def test_prompt_text_contains_all_skills(self):

# ─── 集成测试: Runner ───
class TestRunner:
    async def test_linear_workflow_completes(self):
    async def test_condition_skips_step(self):
    async def test_on_fail_retries(self):
    async def test_max_retries_stops(self):
    async def test_checkpoint_and_resume(self):
    async def test_unknown_skill_hard_fails(self):

# ─── 端到端测试: Composer ───
@pytest.mark.slow
class TestComposer:
    async def test_generates_valid_workflow(self):
    async def test_uses_only_registered_skills(self):
    async def test_error_feedback_improves_output(self):
```

### 13.3 质量指标

| 指标 | 定义 | 目标值 | 测量方法 |
|------|------|--------|---------|
| **工作流可执行率** | 生成的工作流能通过 Validator 校验的比例 | ≥90% | 对 20 个测试需求各生成 3 次，统计通过率 |
| **技能命中率** | 生成的工作流中 action 全部在白名单内的比例 | ≥95% | 同上，检查是否存在 UNKNOWN_ACTION 错误 |
| **端到端成功率** | 生成的工作流能被 Runner 成功执行的比例 | ≥70% | 对 10 个简单测试需求生成并执行 |
| **重试收敛率** | 首次校验失败后经过错误回流重试最终通过的比例 | ≥80% | 统计 Composer 重试次数和最终结果 |
| **断点续传成功率** | 中断后按 run_id 恢复执行能成功完成的比例 | 100% | Runner 集成测试覆盖 |

### 13.4 测试需求基准集

用于度量上述指标的标准化测试需求（见 `tests/e2e/test_benchmark.py`）。**真实需求批量 20 条**（`requirement_batch_io/batch_manifest.yaml`）跑出的失败形态、占位符产物、与夹具不对齐等问题，已整理为 **`tests/e2e/benchmark_failures.md`**，作为后续 Runner / Skill / Composer / 批量脚本优化的**验收参照**，优先级高于抽象指标。

```python
BENCHMARK_REQUIREMENTS = [
    # 简单（1-2步，单技能）
    "读取 /tmp/test.txt 文件的内容",
    "将文本 'hello world' 写入 /tmp/output.txt",
    # 中等（3-4步，多技能组合）
    "读取 data.csv 文件，用 LLM 分析趋势，生成报告并保存",
    "读取 README.md，用 LLM 翻译为中文，写入 README_CN.md",
    # 复杂（含验证循环）
    "读取项目代码文件，用 LLM 生成 API 文档，验证文档完整性，不完整则重新生成",
    "读取配置文件，用 LLM 检查安全风险，生成安全审计报告",
]
```

---

## 14. 目录结构

```
myflow/
├── pyproject.toml                     # 包管理与依赖声明
├── README.md                          # 项目说明
├── .env.example                       # 环境变量模板
│
├── src/
│   └── myflow/
│       ├── __init__.py
│       ├── cli.py                     # Typer CLI 入口         (~150 行)
│       ├── server.py                  # FastAPI HTTP 服务（阶段 5，§17） (~120 行)
│       ├── display.py                 # Rich 输出格式化         (~200 行)
│       │
│       ├── engine/
│       │   ├── __init__.py
│       │   ├── models.py             # Pydantic 数据模型       (~120 行)
│       │   ├── runner.py             # 步骤循环引擎            (~200 行)
│       │   ├── composer.py           # LLM 工作流生成          (~120 行)
│       │   ├── validator.py          # 确定性规则校验          (~180 行)
│       │   └── skill_registry.py     # Skill 注册表            (~80 行)
│       │
│       ├── skills/
│       │   ├── __init__.py
│       │   ├── base.py              # Skill 抽象基类           (~60 行)
│       │   ├── file_ops.py          # file_reader/file_writer  (~80 行)
│       │   ├── http_request.py      # http_request（阶段 5）   (~80 行)
│       │   ├── llm_call.py          # llm_analyze/generate/verify (~150 行)
│       │   └── sub_workflow.py      # 子工作流调用             (~80 行)
│       │
│       ├── infra/
│       │   ├── __init__.py
│       │   ├── config.py            # pydantic-settings 配置   (~30 行)
│       │   ├── llm_client.py        # instructor + LLM SDK     (~80 行)
│       │   └── state_store.py       # SQLite 状态持久化        (~150 行)
│       │
│       └── prompts/
│           ├── composer_system.md    # Composer System Prompt 模板
│           └── examples/
│               ├── linear_simple.yaml    # few-shot 模式 A：线性 2 步无 LLM
│               ├── linear_with_llm.yaml  # few-shot 模式 B：读 → LLM 分析 → 写
│               ├── retry_loop.yaml       # few-shot 模式 C：读 → 生成 → 验证，on_fail 回生成
│               ├── sub_workflow.yaml     # few-shot 模式 D：sub_workflow 嵌套示例（父）
│               └── format_terminal_tail.yaml # few-shot：仅 DSL——不落盘收尾（最后非 file_writer）
│
├── workflows/                         # 用户工作流存放目录
│   └── examples/
│       ├── hello_world.yaml
│       └── child_linear_simple.yaml # 与 prompts/examples/sub_workflow.yaml 配套子工作流
│
└── tests/
    ├── conftest.py                    # 共享 fixtures
    ├── unit/
    │   ├── test_validator.py
    │   ├── test_skill_registry.py
    │   └── test_models.py
    ├── integration/
    │   ├── test_runner.py
    │   └── test_compose_and_run.py
    └── e2e/
        ├── test_cli.py
        └── benchmark_failures.md   # 真实需求批量失败形态汇总（验收参照）
```

**预估总代码量: ~1,680 行**

---

## 15. 实施阶段划分

### 15.0 总原则：基础设施缺陷 → 质量迭代 → 再谈扩展

**第一类（基础设施，必须先修）**  
不修则批量测试结果**不可信**，也无法度量真实 LLM 行为：

1. **Runner 字符串内插**（§4.2.1、§7.3）：须支持 `step.inputs` 中「整段 `{{var}}`」与「串内多占位」两种语义；否则 Composer 合规则 YAML 仍会系统性产生带 `{{}}` 的落盘产物。  
2. **`step.outputs` 全链路 dict 映射**（§4.2、§5.1、`workflow_io`）：历史若存在 list 形态 YAML，加载层须迁移或拒绝；**多步 `llm_*` 串联**时上下文变量名必须与 `outputs` 的 **key** 一致，否则变量「对不上」。

上述两项完成后，**须同步**：Composer System Prompt（`composer_system.md`）、Validator 规则与错误码、**few-shot 示例 YAML**（全部为 dict `outputs`），再重跑 **`requirement_batch_io` 20 条**（`scripts/requirement_batch_report.py` 或 `batch_requirement_e2e.py`），刷新 **`SUMMARY.md`** 与 **`tests/e2e/benchmark_failures.md`** 作为**新基线**。

**第二类（质量优化，在新基线上迭代）**  
内插与 `outputs` 修完后，一部分原判为「LLM 幻觉 / 占位符」的问题可能消失（根因常为**变量未传入、上下文为空串**）。剩余真实 LLM 行为问题按**一次改一项 → 重跑测试 → 记录指标**推进（见阶段 4 任务表），**禁止**未测先堆叠多项改动。

**阶段 4 的量化完成线（进入阶段 5 的前置条件）**  

| 指标 | 目标 | 说明 |
|------|------|------|
| 工作流可执行率 | ≥ 90% | 见 §13.3 |
| 技能命中率 | ≥ 95% | 见 §13.3 |
| 端到端成功率 | ≥ **70%** | 见 §13.3；真实需求批量可作为主测量集之一 |

若修完第一类后三项已**接近**达标，阶段 4 剩余 Prompt 调优可与阶段 5 **并行探索**（仍以不破坏上述阈值为前提）。若重跑后指标仍明显低于阈值，**冻结阶段 5**，优先引擎质量（§17.1）。

---

### 阶段 1: 骨架与执行（第 1 周）

**目标: `myflow run hello_world.yaml` 成功执行**

| 序号 | 任务 | 产出文件 | 验证方式 |
|------|------|---------|---------|
| 1.1 | 初始化项目: pyproject.toml, 目录结构, uv 安装依赖 | pyproject.toml | `uv sync` 成功 |
| 1.2 | 实现 models.py: 全部 Pydantic 数据模型 | engine/models.py | 单元测试通过 |
| 1.3 | 实现 config.py: pydantic-settings 配置加载 | infra/config.py | .env 读取正确 |
| 1.4 | 实现 Skill 基类和 file_reader/file_writer | skills/base.py, skills/file_ops.py | 单元测试通过 |
| 1.5 | 实现 skill_registry.py | engine/skill_registry.py | 注册/查找/SkillCard 生成测试通过 |
| 1.6 | 实现 validator.py: 全部校验规则（含 R04b/R12/R13 等演进条目，以 §4.4 为准） | engine/validator.py | 正向+反向单元测试全部通过 |
| 1.7 | 实现 state_store.py: SQLite 持久化 | infra/state_store.py | 存取/恢复集成测试通过 |
| 1.8 | 实现 runner.py: 步骤循环、条件求值、on_fail 重试、断点续传；**`_resolve_template_value` 须实现 §4.2.1 三类输入（整段引用保类型 + 字符串内插转 str + 字面量）** | engine/runner.py | 单元测试覆盖内插与整段引用；集成测试通过 |
| 1.9 | 手写 hello_world.yaml；**所有示例 `step.outputs` 均为 dict**（与 §4.3 一致） | workflows/examples/ | YAML 可被加载为 WorkflowModel |
| 1.10 | 实现 cli.py: `run` 命令 + display.py: 基本输出 | cli.py, display.py | `myflow run hello_world.yaml` 成功执行 |

**阶段 1 完成标志:**
```bash
$ myflow run workflows/examples/hello_world.yaml --input file_path=/tmp/test.txt
  ✓ Step 1 │ 读取文件 │ file_reader │ 12ms
  ✓ Step 2 │ 写入文件 │ file_writer │ 8ms
  Run abc123 — hello_world │ completed │ 20ms
```

### 阶段 2: 生成与校验（第 2 周）

**目标: `myflow generate "..."` 能生成有效工作流**

| 序号 | 任务 | 产出文件 | 验证方式 |
|------|------|---------|---------|
| 2.1 | 实现 llm_client.py: instructor 封装 | infra/llm_client.py | 结构化输出测试通过 |
| 2.2 | 编写 Composer System Prompt 和 few-shot 示例；**在 Runner 内插与 outputs-dict 落地后做一次全文对齐**（§4.2.1、§6.6、示例目录） | prompts/ | 人工审核 Prompt 质量；`validate` 对示例 YAML 批量通过 |
| 2.3 | 实现 composer.py: 需求→WorkflowModel | engine/composer.py | 生成结果通过 Validator |
| 2.4 | 实现错误回流: Validator 错误→Composer 重试 | composer.py 内逻辑 | 人为注入错误后重试收敛 |
| 2.5 | 实现 LLM 类 Skill: llm_analyze/llm_generate/llm_verify；**system prompt 须禁止 `{{}}`/`[待填写]` 等占位式输出，可选后置正则检查失败以配合 `on_fail` 重试**（见 `benchmark_failures.md` 问题二） | skills/llm_call.py | 单元测试通过；占位符用例反向测试 |
| 2.6 | 实现 CLI: `generate` / `validate`；`list-workflows` 与 `show`（工作流发现与用法，见 §9.4）；`Display.workflows_directory_table` / `workflow_detail` | cli.py, display.py, engine/workflow_io 或轻量扫描辅助 | `list-workflows` 能列出目录下 YAML 摘要；`show <名或路径>` 能展示输入/输出/步骤/on_fail/ run 示例（与 §9.4 一致） |
| 2.7 | 完善 display.py: 生成结果/校验结果等 Rich 输出（与 2.6 的目录展示互补） | display.py | 生成与校验路径输出格式美观清晰 |

**阶段 2 完成标志:**
```bash
$ myflow generate "读取 data.csv，分析趋势，生成报告"
  ✓ 工作流已生成: analyze_csv (3 步骤)
  ✓ 校验通过
  已保存至: workflows/analyze_csv.yaml

$ myflow validate workflows/analyze_csv.yaml
  ✓ 校验通过

$ myflow list-workflows
  （表格列出 workflows/ 下各 YAML 的 Name / Description / Steps）

$ myflow show analyze_csv
  （展示该工作流的输入输出、步骤与 myflow run … --input … 示例）
```

### 阶段 3: 健壮性与体验（第 3 周）

**目标: 系统可靠运行，CLI 体验完整**

| 序号 | 任务 | 产出文件 | 验证方式 |
|------|------|---------|---------|
| 3.0 | **`run` 执行结果终端可见（基本功能）**：实现 `Display.step_output`；`--verbose` 时每步成功后打印该步全部 `outputs`（值过长截断）；`completed` 且最后一步 `action != file_writer` 时自动打印最后一步 outputs（见 §9.5） | display.py, cli.py | 仅含 `file_reader` + `llm_*`、无写文件收尾的工作流跑完后终端可见结论；`--verbose` 下逐步可见全部 outputs |
| 3.1 | 实现 sub_workflow Skill | skills/sub_workflow.py | 嵌套工作流集成测试通过 |
| 3.1b | 实现 **`multi_file_reader`**：接受路径列表，输出 `path -> content` 映射；`file_reader` SkillCard 强调仅单文件；Validator **R12** 启发式 warning（见 `benchmark_failures.md` 问题四） | skills/file_ops.py, validator.py | 多文件工作流与 13/17 类场景集成测试 |
| 3.2 | 完善断点续传: `myflow run --resume <run_id>` | runner.py, cli.py | 中断恢复测试通过 |
| 3.3 | 实现 CLI: `list` / `logs` / `status` 命令 | cli.py, display.py | 管理命令输出正确 |
| 3.4 | 完善错误处理: 所有异常路径输出友好信息 | 全局 | 人为触发各种错误验证输出 |
| 3.5 | 配置 structlog + Rich logging（**与 3.0 区分**：此处为结构化运行/调试日志链；步骤 `outputs` 展示见 3.0） | cli.py | 人为开关下可观测请求与内部阶段 |
| 3.6 | 编写集成测试: Runner 全路径 | tests/integration/ | 10+ 集成测试通过 |

**阶段 3 完成标志:**
```bash
$ myflow list
┌──────────┬──────────────────┬───────────┬─────────────────────┐
│ Run ID   │ Workflow         │ Status    │ Time                │
├──────────┼──────────────────┼───────────┼─────────────────────┤
│ abc123   │ analyze_csv      │ completed │ 2026-04-20 10:30:00 │
│ def456   │ hello_world      │ failed    │ 2026-04-20 10:25:00 │
└──────────┴──────────────────┴───────────┴─────────────────────┘

$ myflow logs abc123
┌─ Run abc123 — analyze_csv ────────────────────────┐
│ ✓ Step 1 │ 读取CSV    │ file_reader  │ 15ms       │
│ ✓ Step 2 │ 分析趋势   │ llm_analyze  │ 2.1s       │
│ ✓ Step 3 │ 生成报告   │ file_writer  │ 8ms        │
│ Status: completed ✓   Duration: 2.1s              │
└───────────────────────────────────────────────────┘
```

另：**任务 3.0** 完成后，`myflow run …` 在非 `file_writer` 收尾且 `completed` 时须在终端展示最后一步产出；`--verbose` 须逐步打印各步全部 `outputs`（约定见 §9.5）。

### 阶段 4: 质量度量与优化（第 4 周）

**目标: 在可信基线上使 §13.3 指标达标，系统可交付；未达标不进入阶段 5。**

| 序号 | 任务 | 产出文件 | 验证方式 |
|------|------|---------|---------|
| 4.0 | **基线重置（阻塞）**：确认 Runner 内插 + `outputs` dict 全链路已合并主干；重跑 `requirement_batch_io` 20 条；更新 `SUMMARY.md`、`tests/e2e/benchmark_failures.md` 与内部指标表 | 脚本输出、文档 | 与 §15.0「第一类」完成定义一致 |
| 4.1 | 编写/维护基准测试集 | tests/e2e/test_benchmark.py | 标准需求可运行 |
| 4.2 | 每次变更后度量：可执行率 / 技能命中率 / **端到端成功率** | 测试报告、`SUMMARY` | 对照 §13.3；**改一项、测一轮** |
| 4.3 | 实现简化版 Champion 缓存: 按需求 hash 缓存成功产物 | engine/cache.py | 相同需求秒级返回 |
| 4.4 | Prompt 调优（单项）：`llm_*` 禁止占位符、后置 `{{}}` 检查、Composer「基于输入」锚定、`llm_verify` 建议等**每次只合入一类**，合入后即触发 4.2 | prompts/, skills/llm_call.py | 指标对比上一轮基线 |
| 4.5 | 按需合入 **`multi_file_reader`**（若 4.0 后 13/17 类仍失败为主因） | skills/file_ops.py 等 | 定向用例 + 20 条子集重跑 |
| 4.6 | 补充边界 case 测试 | tests/ | 测试覆盖率 ≥80% |
| 4.7 | 编写 README.md: 安装/使用/开发指南 | README.md | 新用户可按文档使用 |

**阶段 4 完成标志（与 §17.1 阶段 5 门禁对齐）:**

- 工作流可执行率 ≥ **90%**
- 技能命中率 ≥ **95%**
- 端到端成功率 ≥ **70%**
- 全部自动化测试通过
- README 完整
- **真实需求 20 条**（或等价主测量集）已在新基线下至少跑通一轮并归档结果

---

## 16. 开发过程疑问区

本节记录在实施与评审过程中出现的疑问、结论与待决事项，便于后续迭代时追溯上下文；**不等同于已定稿的规范**，若与上文正式章节冲突，以正式章节为准。

### 16.1 终端展示 vs 落盘（用户只要 CLI 输出、不写文件）

**背景疑问（2026-04-18）**

若用户在工作流相关的自然语言需求中明确表示：**不需要将执行结果写入文件，只希望将结果（例如 LLM 摘要）直接显示在终端 CLI**，系统应如何处理？这与「run 跑完终端几乎没有任何步骤产物」是否为同一问题？

**结论（两层仍成立，取舍已修正）**

1. **执行侧（CLI）——功能缺口，不是单纯体验优化**  
   Runner 已把技能输出写入 `StepResult.outputs`，但若 CLI 从不展示，对用户而言等同「跑完没有结果」。**规范上**：`--verbose` 下每步成功后须打印该步**全部** `outputs`（键值对展示，单值过长可截断）；**不按技能类型挑选「主字段」**，避免规则膨胀。  
   另：**成功完成**且**最后一步**不是 `file_writer` 时，CLI **默认**在汇总后追加展示**最后一步**的 `outputs`（标题如「结果:」）。写文件收尾则假定产物已在路径上，不重复刷屏。  
   上述约定写入 **§9.5**，实施落在 **§15 阶段 3 任务 3.0**。

2. **架构边界——不做 `cli_print` 一类 Skill**  
   Skill 必须是纯粹的输入→输出；**「打印到终端」不是工作流语义，而是展示层职责**。新增 `cli_print` 会把 CLI 关切泄漏进引擎层，**明确不采纳**。

3. **生成侧（Composer）——不增加专门 Prompt 约束**  
   不为「不落盘」单独加「禁止 `file_writer`」规则；合理需求下好的 Composer 本就不会多余落盘。若生成了写文件步骤而用户未提供路径，按正常使用错误处理即可。

**曾考虑的误区（记录以免反复）**

- 将 `--verbose` 打印 outputs 标为「候选 / 体验项」——已否：**列为基本能力与阶段 3 硬性任务（3.0）**。  
- 用「只为 LLM 步骤挑主文本字段」减少输出——已否：**全量打印 outputs**，由用户筛选。  
- 用 Skill 表达「给用户看」——已否：见上文边界。

**当前实现状态**：仍以代码为准；文档基线见 §9.5 与任务 3.0（待开发完成后可将本段「当前实现」收缩为一句指向版本）。

---

## 17. 阶段 5：外部集成扩展（HTTP 与 Serve）

> **定位**：在核心引擎（Runner / Validator / Skill / Composer）经 **§15.0 第一类修复** 与 **阶段 4 指标**（§15 阶段 4 完成标志）验证稳定后，将系统从「本地批处理 CLI」扩展为**可被外部系统调用的 LLM 处理节点**。  
> **原则**：基础不稳时增加外部集成只会放大调试成本；**未满足 §17.1 不得开始本阶段主线条目（5.1–5.6）**。

### 17.1 进入阶段 5 的前置条件（硬性）

同时满足：

1. §13.3 三项指标：**可执行率 ≥ 90%**、**技能命中率 ≥ 95%**、**端到端成功率 ≥ 70%**（主测量集可为 `requirement_batch_io` 20 条 + `test_benchmark`）。  
2. **第一类基础设施缺陷**已合入主干并完成至少一轮全量或约定子集回归（见 §15.0）。  
3. 团队明确：**阶段 5 功能默认不启用**于不满足上述阈值的发布分支（可选特性开关由实现决定，文档不强制）。

### 17.2 `http_request` 技能

**职责**：向外部 HTTP 服务发起请求并返回状态码与响应体（用于 Webhook、Slack、短信网关、自建 API 等）。

**输入 / 输出模型（设计摘要）**

| 字段 | 方向 | 说明 |
|------|------|------|
| `url` | 输入 | 请求 URL；支持整段 `{{var}}` 或内插后的字符串 |
| `method` | 输入 | `GET` / `POST` / `PUT` / `PATCH` / `DELETE`，默认 `POST` |
| `headers` | 输入 | 请求头，`dict[str, str]`，默认 `{}` |
| `body` | 输入 | 原始请求体（JSON 字符串或纯文本） |
| `timeout` | 输入 | 超时秒数，默认 30 |
| `status_code` | 输出 | 整数 HTTP 状态码 |
| `response_body` | 输出 | 响应正文（文本） |
| `success` | 输出 | `200 <= status_code < 300` 时为 `True` |

**实现约定**

- 文件：`src/myflow/skills/http_request.py`（名称可与仓库惯例对齐）。  
- HTTP 客户端：**httpx** 异步客户端（`httpx.AsyncClient`）。  
- **幂等**：`idempotent = False`（网络写类操作，不依赖 Runner 自动重试盲补）。  
- **依赖**：`pyproject.toml` 增加 `"httpx>=0.27"`（见 §2.3 阶段 5 注释块，实施时取消注释或并入主依赖列表）。

**安全：Validator 规则 R13（§4.4）**

对 `action == "http_request"` 的步骤，当 `url` 为**字面量**（即非「整段仅为 `{{var}}`」形式、可在静态分析中读取的 URL 字符串）时，禁止匹配以下模式（实现可用正则列表）：

- `http(s)://localhost`、`127.0.0.1`、`0.0.0.0`  
- 常见内网段：`192.168.*`、`10.*`（细则实现可调，以「默认拒绝内网字面量」为目标）  
- `file://` 协议  

**变量引用 URL**：静态 Validator **不**解析运行时值；若需运行时策略，可在 Skill 内二次校验或后续迭代补充。

### 17.3 HTTP 触发服务（FastAPI）

**目标**：外部系统通过 HTTP 触发已落盘的 YAML 工作流执行，并查询运行状态。

**建议端点**

| 方法 | 路径 | 行为 |
|------|------|------|
| `POST` | `/run/{workflow_name}` | Body: `{"inputs": { ... }}` 与工作流 `inputs` 对齐；加载 `workflows_dir` 下 `{workflow_name}.yaml`；执行 Runner；返回 `run_id`、`status`、**最后一步** `outputs` 摘要、`error` |
| `GET` | `/workflows` | 扫描 `workflows_dir` 下 `*.yaml`，返回名称、描述、`inputs`/`outputs` 键列表 |
| `GET` | `/runs/{run_id}` | 自 `StateStore` 读取运行记录；不存在则 404 |

**实现约定**

- 文件：`src/myflow/server.py`，`app = FastAPI(...)`。  
- 加载 YAML 使用与 CLI 一致的 `WorkflowModel` 构造路径（避免重复解析逻辑）。  
- **依赖**：`fastapi>=0.115`、`uvicorn>=0.32`（§2.3）。  
- **与 CLI 边界**：服务进程内不重复实现业务规则；仅编排 `Runner` + `StateStore` + `AppConfig`。

### 17.4 CLI：`myflow serve`

```text
myflow serve [--host 0.0.0.0] [--port 8000]
```

以 **uvicorn** 挂载 `myflow.server:app`；启动后在终端打印监听地址与 **OpenAPI 文档** URL（如 `/docs`）。

### 17.5 典型集成场景（验收叙事）

- **CI**：GitHub Action `curl -X POST https://host/run/daily_report -d '{"inputs":{"date":"..."}}'`  
- **Webhook**：订单系统 POST `/run/send_sms`，`inputs` 含手机号、订单号。  
- **下游推送**：工作流末步 `http_request` 调 Slack Incoming Webhook，`body` 可用内插引用 `{{analysis_result}}`；`step.outputs` 须为 dict，例如 `slack_ok: success`。

### 17.6 阶段 5 任务清单（实施顺序）

| 序号 | 任务 | 产出文件 | 验证方式 |
|------|------|---------|---------|
| 5.1 | 实现 `http_request` Skill（httpx） | `skills/http_request.py` | 单元测试：mock HTTP 校验请求/响应 |
| 5.2 | Validator：R13 URL 安全 + 集成注册表技能名 | `validator.py` | 内网字面量 URL 反向用例 |
| 5.3 | `SkillRegistry` 注册 `http_request`，SkillCard 进入 Composer | `skill_registry.py`, `composer_system.md` | Prompt 含 `http_request` 描述 |
| 5.4 | few-shot：`prompts/examples/with_api_call.yaml`（末步 `http_request`，`outputs` dict） | `prompts/examples/` | `myflow validate` 通过 |
| 5.5 | FastAPI：`/run/{workflow_name}`、`/workflows`、`/runs/{run_id}` | `server.py` | `curl` 触发本地工作流成功 |
| 5.6 | CLI：`myflow serve` | `cli.py` | 浏览器打开 `/docs` |
| 5.7 | 集成测试：HTTP → Runner → 响应 | `tests/integration/test_server.py` | CI 可跑（可用 TestClient） |

### 17.7 阶段 5 完成标志（示例）

**标志 A（本地工作流调外部 API）**

```bash
$ myflow run workflows/notify_slack.yaml --input message="部署完成"
  ✓ Step 1 │ 推送到Slack │ http_request │ 320ms
  Run abc123 — notify_slack │ completed │ 320ms
```

**标志 B（外部触发工作流）**

```bash
$ myflow serve
  MyFlow API 服务启动
  地址: http://0.0.0.0:8000
  文档: http://0.0.0.0:8000/docs

$ curl -X POST http://localhost:8000/run/hello_world \
    -H "Content-Type: application/json" \
    -d '{"inputs": {"file_path": "/tmp/test.txt"}}'
  {"run_id":"…","status":"completed","outputs":{…},"error":null}
```

---

## 附录 A: 关键设计决策记录

| 决策 | 选择 | 备选 | 理由 |
|------|------|------|------|
| 工作流格式 | YAML | Markdown DSL / JSON | 人类友好 + 标准解析器 + LLM 生成稳定 |
| LLM 角色数 | 1 (Composer) | 3 (Planner/Generator/Evaluator) | 减少 token 成本和调试复杂度 |
| 结构化输出 | instructor | LangChain / 手动 parse | instructor 自带重试+错误回流，代码最少 |
| 架构层数 | 3 | 8 | 个人开发者可维护的上限 |
| CLI 框架 | Typer + Rich | Click / argparse | 类型提示驱动 + 美观终端输出 |
| 状态存储 | SQLite + JSON | Redis / pickle | 单机够用 + 跨语言 + 安全序列化 |
| 条件求值 | simpleeval | Python eval() | 安全沙盒，防止注入 |
| Skill 与展示层边界 | Skill 仅输入→输出；终端是否展示由 CLI/Display 负责 | `cli_print` 等展示型 Skill | 避免引擎层感知交互形态 |
| 外部集成时机 | **阶段 5**（`http_request` + `serve`）仅在 **§15.0 + 阶段 4 指标**达标后主线实施 | 指标未达标即加 HTTP/FastAPI | 避免在不稳定引擎上叠加分布式调试面 |

---

## 附录 B: 与本设计文档对照的工程变更摘要（增补）

以下内容在**不重写上文既有章节**的前提下，说明交付后已实现、且可能与文中早期表述（例如 §600 附近 `file_reader` / `multi_file_reader`、阶段 3 任务 **3.1b**、Validator **R12**）不一致之处；**以实现代码为准**。

- **`file_reader`（`skills/file_ops.py`）**：在**运行时**区分单文件（原文输出）、目录（递归读取并格式化为若干 `=== 路径 ===` 块）、`.zip`（解压后再遍历）；输入支持 **`path`/`file_path`**、`paths`（列表或逗号分隔）以及 **`path` 中带逗号的多个路径**。统一输出 **`file_content: str`** 与 **`file_count`**，并有总字符数与文件数上限。
- **`multi_file_reader`**：保留注册名作为**别名**，逻辑与 **`file_reader` 同源**；为减少 Composer 误选，默认**不参与技能清单文案注入**（`Skill.include_in_prompt_catalog`）。
- **Validator**：已移除 **R12（MULTI_PATH_SUSPICION）**，因逗号拼接多路径改由 **`file_reader`** 在执行层处理。
- **Runner**：仍保留将 **`dict`** 自适应为可读字符串填入 **`str`** 类型入参的逻辑，作兜底与其它场景兼容。
- **配套文档**：`composer_system.md`（读取步骤叙事）、`tests/e2e/benchmark_failures.md`（§10）已按上述行为同步。

---

*文档结束。实施时按照阶段 **1→2→3→4** 顺序执行；**阶段 5（§17）** 须在阶段 4 完成标志满足后再作为主线排期。开发中的疑问与临时结论见第 16 节。*
