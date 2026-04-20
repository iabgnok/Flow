# 真实需求批量测试：失败与形态汇总（验收参照）

> 来源：`requirement_batch_io/batch_manifest.yaml` 中 20 条需求，`myflow generate` 得到 `workflows/requirement_batch_20/rb20_r*.yaml`，经 `run_specs.yaml` + `scripts/requirement_batch_report.py` 或手工执行后的**真实产物**与 `runs/*_last_run.json`。  
> 用途：作为 Runner / Validator / Skill / Composer / 批量脚本的**回归清单**；优先级高于抽象 KPI。设计文档对应修订见 `MyFlow_完整设计文档.md` v1.1+、`src/myflow/prompts/composer_system.md`。**Composer 提示词修订与再生效果**见 **§9**。

---

## 1. 按问题形态分类（根因归属）

| ID | 现象摘要 | 主要根因 | 次要/诱发因素 | 建议修复阶段 |
|----|----------|----------|----------------|--------------|
| P1 | `step.inputs` 中含**字符串内插**（如 `"翻译为{{lang}}：{{text}}"`）时，占位符原样进入技能或落盘，产物大量 `{{...}}` | **Runner**：仅支持「整段 = `{{var}}`」一种解析，属设计缺陷 | Composer 按人类直觉生成合法 YAML | **阶段 1**：`_resolve_template_value` 区分整段引用（保类型）与内插（`str` 替换），见设计 §4.2.1、§7.3 |
| P2 | LLM 产出**正文级模板**（如 `甲方：{{签约方信息}}`、`<待填写>`），非 YAML 模板 | **Skill / Prompt**：`llm_analyze` / `llm_generate` 未禁止占位式交付 | 无结构化字段强制「填实」 | **阶段 2**：加强 system prompt + 可选正则后置失败触发 `on_fail` 重试 |
| P3 | 给定极简代码夹具，输出变为**完全无关**的长代码（如 rb20_r10） | **LLM**：未锚定输入；成功判定仅看流程未跑 pytest | 夹具过简、链路过长 | **阶段 4**：Composer 建议加「与输入相关」`llm_verify`；**阶段 2** prompt 强调必须基于 `content` |
| P4 | 多文件路径被拼成 `a.txt,b.txt` 传入 `file_reader`，运行期 ENOENT（rb20_r13 / r17） | **技能能力缺口** + **批量推断**：`file_reader` 仅单文件；`batch_requirement_e2e` 用逗号拼多路径 | Composer 生成 `news_file_paths` 等单字段多路径 | **阶段 3**：`multi_file_reader`；Composer 清单与 SkillCard 写明边界；批量脚本可对已知多文件键改推断 |
| P5 | 课程本地化：对**目录**走 `file_reader` → Permission denied（rb20_r19） | **工作流设计** + **批量推断**：目录应用列举/多文件或专用技能 | 引擎未自动区分文件/目录 | **阶段 3/4**：Composer 规则 + 推断避免把 `_dir` 当单文件读 |
| P6 | `product_name` / `core_selling_point` 被填成**文件路径**而非正文（rb20_r04） | **批量脚本** `_infer_inputs` 语义分类错误 | 工作流把名称当 string 而非 path | **批量脚本**（已加夹具解析范例）；设计文档提示「文本型业务字段勿走 file 推断」 |
| P7 | `SUMMARY.md` 在带 `--from-id` / `--skip-ids` 跑报告后，**执行列**与全量历史不一致 | **报告脚本语义**：单次运行覆盖写 SUMMARY | 用户误读为全量 E2E | 文档/脚本说明（非引擎）；可选「合并历史」模式 |
| P8 | `rb20_r10` 单测文件无 `import` 被测模块仍标「成功」 | **成功定义过松**；无执行 pytest 的步骤 | LLM 惯例 | **阶段 2/4**：可选 `shell`/pytest 技能或 verify 要求「可导入」 |
| P8b | 代码重构/补测后更换模块名或导入路径（如把输入 `r10_code.py` 改写成 `sample_module`，测试导入 `sample_module`） | **LLM**：未锚定“文件名/模块名必须保持”约束；verify 条件过松 | 夹具过简、生成步未给出明确锚点 | **阶段 4**：generate instruction 明确“保留原函数名/文件名/导入路径”；verify 只检查客观模式（不得出现新的模块名、导入必须指向输入文件） |
| P9 | Composer 产出 **多步同 action + 同主输入**（例：rb20_r18 三步 `llm_analyze` 均 `content: '{{zip_content}}'`） | **Composer / Prompt**：步骤粒度规则在长需求、多维度枚举下易被覆盖 | 与 `composer_system.md` 已有合并条文并存 | **Prompt** 见 **§7**；**确定性兜底** 见 **§8**（`MERGEABLE_LLM_ANALYZE`） |
| P10 | 产物中含「示例代码/打印语句不完整」导致不可直接运行（典型：f-string 未插入变量、`print` 未打印异常对象） | **LLM**：示例拼装易漏变量；verify 若仅做结构检查可能放过 | 文档类产物缺少“可复制运行”门禁 | **阶段 2/4**：在 generate instruction 中写死“示例代码必须可运行/打印变量值”；verify 仅检查客观模式（如 `f\"...{var}...\"` 中含 `{}`）或后续引入确定性 lint/执行技能 |

---

## 2. 与设计文档章节映射

| 问题 | 设计文档位置 |
|------|----------------|
| P1 字符串内插 | §4.2.1、`MyFlow_完整设计文档.md` §7.3 Runner |
| P2 占位式 LLM 输出 | §15 阶段 2 任务 2.5；实现落在 `skills/llm_call.py` |
| P3 换题 / 输入锚定 | `composer_system.md` 需求规则；§15 阶段 4 任务 4.4 |
| P4 多文件 | §6.3 `multi_file_reader`；§4.4 规则 R12；§15 阶段 3 任务 3.1b |
| P5 目录读取 | 同 P4 + Composer 路径规则 §7.2 |
| P6 批量语义 | `scripts/batch_requirement_e2e.py`（实现），设计 §13.4 指向本文档 |
| P9 步骤合并 | `composer_system.md`「步骤粒度规则」；Prompt 备忘 **§7**；校验兜底 **§8** |
| P10 示例代码可运行性 | `llm_generate` instruction/verify 的客观门禁；可选引入确定性 lint/执行能力（后续阶段） |

---

## 3. 典型产物路径（便于人工对照）

| 类型 | 路径模式 |
|------|-----------|
| 单次运行快照 | `requirement_batch_io/runs/XX_last_run.json` |
| 工作流产出 | `requirement_batch_io/runs/XX/wf_out_*.{txt,md}` |
| 工作流定义 | `workflows/requirement_batch_20/rb20_rXX.yaml` |

**示例（历史观测）**

- **04**：`runs/04/wf_out_0.txt` 曾出现未替换的 `{{product_name}}`（P1 + P6 叠加）。
- **10**：`runs/10/wf_out_0.txt`、`wf_out_1.txt` 存在但与 `fixtures/r10_code.py` 主题不对齐（P3）。
- **12**：`runs/12/wf_out_0.txt` 含大量正文内 `{{...}}` 中文占位（P2）。
- **13 / 17**：`*_last_run.json` 中 Step 1 读取失败，路径为逗号拼接串（P4）。
- **18**：`runs/18/wf_out_0.md` 的 API 文档示例中出现 `print(f\"…\")` 未插入变量值（P10）。

---

## 4. 修复优先级建议（执行顺序）

1. **阶段 1（阻塞）**：Runner 字符串内插（P1）— 否则 Composer 合规则 YAML 仍系统性产出坏结果。  
2. **阶段 2**：LLM Skill 反占位 prompt + 可选硬检查（P2、辅助 P3）。  
3. **阶段 3**：`multi_file_reader` + Validator 启发式 R12（P4）。  
4. **阶段 4**：Composer 对「基于输入修改」类加 verify 建议（P3）；指标上再收敛 rb20 批量。

---

## 5. 维护约定

- 每轮 `requirement_batch_report` 或批量 E2E 后，若出现**新失败形态**，在本文件 **§1** 增行，并在 `MyFlow_完整设计文档.md` §13.4 保持「本文档为真源」的指向。  
- **不**用本文档替代 `SUMMARY.md`：`SUMMARY.md` 仍为脚本自动生成的一览表；本文档为**根因级**备注。  
- Composer **步骤合并类**回归（**P9**）：Prompt 演进记在 **§7**、**§9**；校验机制记在 **§8**；**§9** 含提示词修订清单与新 prompt 下批量 YAML 再生效果。

## 6. 与阶段 5（外部集成）的关系

`http_request`、`myflow serve`、FastAPI 触发端点等 **§17 阶段 5** 能力，**仅**在 `MyFlow_完整设计文档.md` §15.0 / 阶段 4 完成标志（可执行率、技能命中率、端到端成功率）达标后再主线实施。本文档中的失败项应先在**本地引擎**上收敛；否则外部集成会把「变量未传入 / 内插失败」放大为分布式调试问题。

---

## 7. Prompt 调优（rb20_r18：同类 LLM 步骤未合并）

本章记录 **Composer 系统提示**（`src/myflow/prompts/composer_system.md`）与历史上 **rb20_r18** 违反「步骤粒度 / 同类 LLM 合并」的形态、原因假设与条文迭代。**当前 rb20_r18 生成物是否仍违规**请以仓库内 YAML 及 **§8** 为准。

### 7.1 案例：rb20_r18

#### 标注

| 项 | 内容 |
|----|------|
| **问题工作流路径** | `workflows/requirement_batch_20/rb20_r18.yaml` |
| **问题名称** | `project_technical_review` |
| **问题区域** | **`steps` 中 `id: 2`、`id: 3`、`id: 4`**（三步均为 `action: llm_analyze`，且 `inputs.content` 均为 `'{{zip_content}}'`） |
| **触发规则（引擎侧文案）** | `composer_system.md` →「### 步骤粒度规则」→「合并判定（机械规则）」：同 `action` 且 `content`/`context` 结构同引用 → 必须合并 |

#### 问题摘录（仅问题区域）

三步重复消费同一份 `zip_content`，维度拆在三个 `instruction` 里，本应合并为单次 `llm_analyze`（或拆成不同 **action**，但此处 action 相同）：

```yaml
# workflows/requirement_batch_20/rb20_r18.yaml — 问题区域：步骤 2–4
- id: 2
  name: 分析项目架构概览
  action: llm_analyze
  inputs:
    content: '{{zip_content}}'
    instruction: 分析这个代码仓库的文件结构，生成项目架构概览。包括：...
  outputs:
    architecture_overview: analysis_result
- id: 3
  name: 分析模块职责和依赖
  action: llm_analyze
  inputs:
    content: '{{zip_content}}'
    instruction: 按模块分析各文件的职责和依赖关系。包括：...
  outputs:
    module_analysis: analysis_result
- id: 4
  name: 检测代码质量和安全漏洞
  action: llm_analyze
  inputs:
    content: '{{zip_content}}'
    instruction: 检测代码质量问题和安全漏洞。包括：...
  outputs:
    quality_security_issues: analysis_result
```

**连带影响：** 后续 `id: 5`、`id: 7` 的 `context` 仍拼接三项分析结果；若前三步合并为单一结构化分析产物，下游应改为引用该单一结果，而不是三次重复读 ZIP 正文。

### 7.2 与当前 Prompt 的对照

- **已定稿策略**：合并约束改为 **纯结构「合并判定（机械规则）」**（步骤对扫描、`llm_analyze`/`content` 与 `llm_generate`/`context`）；内联 YAML 仅用 **`{{X}}` 级抽象占位**，并用**两行跨领域一句话**提示普适性，**避免**用 `zip_content`/代码审查长例导致规则退化为单一场景的模式匹配。
- **few-shot 分工**：条文负责对错；**few-shot**（`composer.py` 加载的 `prompts/examples/`）负责完整形态，且要求**至少一条合并正例**、**不得**含「同 action + 同主输入拆多步」反例（详见 `composer_system.md`「few-shot 说明」）。
- **仍可能出现 r18 类结构**：长需求枚举维度时模型仍可能拆步；后续可加码 **Validator 机检** 与本条机械规则对齐。

### 7.3 对「原因假设」与「修改建议」的合理性分析

下列对应常见复盘思路，**不等同**于已全部验证的根因实验结论。

#### 7.3.1 规则位置与语气偏「解释」而非「硬约束」

**合理性：高。**  
「步骤粒度规则」嵌在「需求理解规则」下，模型容易先按需求字面拆成「架构一步、模块一步、质量一步」。把合并约束提升为 **输出前必经的规划/自检**，或单独成章并冠以「违反即错误」，通常能提高遵从率。

#### 7.3.2 Few-shot「反向示范」压制文字规则

**合理性：对本仓库需区分事实与风险。**  

当前 Composer 注入的 few-shot 列表见 `src/myflow/engine/composer.py` → `_load_examples`，固定顺序包含 `multi_analysis_assembly.yaml`。该文件以**中性材料审阅**叙事示范「多维度分析合并为一步」`llm_analyze`，注释强调同类合并与 `file_writer` 组装。**因此：rb20_r18 并非由「仓库内 few-shot 正例缺失」必然导致；更可能是长需求下的结构偏好覆盖了文字规则与正例。**  

**风险仍存在：** 若将来在 `prompts/examples/` 中加入多段同 `content` 的 `llm_analyze`，或在外部自定义示例目录引入类似 r18 的结构，示范效应会迅速压过条文——**维护 few-shot 为「合并后的干净形态」仍是最高优先的工程纪律**。

#### 7.3.3 判断标准需交叉对比，与自回归生成冲突

**合理性：高。**  
「两两比对步骤」对模型不友好；先生成步 2 再生成步 3 时，缺少强制回溯。**补充「生成前规划」或「生成后扫描 content 是否重复」的自检话术**，与 Validator 能否机检（若未来增加启发式）是两条线：Prompt 侧先发制人，引擎侧兜底更稳。

#### 7.3.4 建议修改条目（精炼评估）

| 建议 | 评估 | 说明 |
|------|------|------|
| **生成前规划阶段**（先列动作再写 YAML） | **已纳入** | 见 `composer_system.md`「生成流程（输出 `steps` 之前）」。 |
| **合并规则机械化 +  pairwise 自检** | **已纳入** | 「合并判定（机械规则）」覆盖 `content`/`context` 及 `context` 字面完全相同的情形。 |
| **内联示例用抽象占位 + 少量跨领域一句** | **采纳（替代 zip 贴近例）** | **不**再用「zip + 架构/模块/安全」长例：过拟合风险高于收益；改用 `{{X}}` 与短文/翻译两句提示普适性。 |
| **条文 vs few-shot 分工 + few-shot 门禁** | **已纳入** | 系统提示「few-shot 说明」表格 + 禁止反向示范；正向长流程仍以 `multi_analysis_assembly.yaml` 等为样板。 |

### 7.4 已在 `composer_system.md` 落实的要点（摘要）

1. **生成流程**：写出 `steps` 前先内化合并判定，禁止依赖「生成后再改」。  
2. **合并判定**：全步骤对 `(i,j)` + `action` 相同 + 主输入字段结构相同 → 必须合并；不写业务语义条件。  
3. **内联示例**：仅用 `{{{{X}}}}`→`{{X}}` 抽象片段 + 一行跨领域提示；**刻意**不用 r18 / zip 专用长例。  
4. **few-shot 说明**：条文定义对错，few-shot 示范完整 Workflow；至少一条合并正例、禁止同主输入拆步反例。

### 7.5 后续仍可加强（执行顺序）

| 优先级 | 事项 |
|--------|------|
| ~~**中高**~~ | ~~Validator 机检~~ → **已落地**，见 **§8**（`llm_analyze` + 同 `content`）。 |
| **中** | 扩展：是否对 **`llm_generate`** 在「同 `context` 整段引用」下做类似分组（边界更多，待观察）。 |
| **低** | few-shot 列表若要增删，保持「有一条合并正向完整例」且无拆步反例。 |

### 7.6 维护说明

- 若在 `requirement_batch_io/batch_manifest.yaml` 中调整 **第 18 条需求** 或重跑 `myflow generate`，更新工作流后请对照 **§8** 的收敛情况。  
- **P9**（§1 表）与 **§7 / §8** 互参。

---

## 8. 校验机制：`llm_analyze` 同主输入合并（确定性兜底）

本节说明引擎侧与 **P9** 配套的 **确定性** 规则：弥补「仅靠 Prompt 时模型仍可能按枚举拆步」的概率性缺陷，并与 **`compose_until_valid`** 重试闭环衔接。

### 8.1 行为摘要

| 项 | 说明 |
|----|------|
| **触发条件** | 工作流中存在 **多于一个** `action: llm_analyze` 的步骤，其 `inputs.content` 为字符串且 **`strip()` 后完全相同**（例如均为 `'{{zip_content}}'`）。含内插的长模板与整段 `'{{var}}'` **不会**与彼此误判为同一组。 |
| **报错形态** | `ValidationReport.add_warning`，代码 **`MERGEABLE_LLM_ANALYZE`**；**不**调用 `add_error`，故 **`report.passed` 仍为 True**（与非阻塞类 warning 区分）。 |
| **阻塞语义** | 该代码列入 **`BLOCKING_WARNING_CODES`**（`src/myflow/engine/models.py`）。**`execution_ready()`** = `passed` 且 **无阻塞级 warning**。未就绪时 **`myflow generate` / `validate` / `run`** 均视为未通过严格校验；**Composer** 用 **`compose_feedback_summary()`** 把此类 warning 与 error 一并回流给下一轮 LLM。 |
| **实现位置** | `WorkflowValidator._check_mergeable_llm_analyze_steps`（`src/myflow/engine/validator.py`）。 |
| **刻意未覆盖** | **`llm_generate`** 的 `context` 暂不纳入同一分组（避免「同上下文、完全不同产出」的合理拆步被误杀）；后续可再观测迭代。 |

### 8.2 与 Composer 的闭环

```
生成 YAML → validate → 若存在 MERGEABLE_LLM_ANALYZE → execution_ready() 为假
    → 不写入 Champion 缓存、不把最后一次结果当成功
    → 将 compose_feedback_summary() 注入下一轮 user 消息 → 直至消除违规或用尽 composer_max_attempts
```

### 8.3 生成效果观测（batch 第 18 条 / `rb20_r18.yaml`）

**条件（便于复现）：** 关闭 Champion 缓存，避免沿用旧 YAML：`MYFLOW_CHAMPION_CACHE_ENABLED=false`；需求全文同 `requirement_batch_io/batch_manifest.yaml` 中 **id `"18"`** 的 `requirement` 字段。

**一次实测（DeepSeek，约 2 次 HTTP 请求）：** 首轮生成仍出现多步同 `content` 的 `llm_analyze` → 校验命中 **`MERGEABLE_LLM_ANALYZE`** → 第二轮收敛；最终 **`execution_ready()` 通过**，工作流 **7 步**。

**步骤骨架（与「合并分析 + 生成 + 验证 + 落盘」一致）：**

| id | 名称（摘要） | action |
|----|----------------|--------|
| 1 | 读取压缩包内容 | `file_reader` |
| 2 | 综合分析代码仓库（**唯一** `llm_analyze`，`content: '{{zip_content}}'` 仅出现一次） | `llm_analyze` |
| 3 | 生成测试用例 | `llm_generate`（`context: '{{full_analysis}}'`） |
| 4 | 生成 API 接口文档 | `llm_generate`（同上） |
| 5–6 | 验证测试 / 验证 API 文档 | `llm_verify` |
| 7 | 生成技术审查报告 | `file_writer`（章节内插 `full_analysis`、`test_cases`、`api_docs`） |

**合并步摘录（步骤 2，示意）：**

```yaml
- id: 2
  name: 综合分析代码仓库
  action: llm_analyze
  inputs:
    content: '{{zip_content}}'
    instruction: "分析以下代码仓库压缩包内容，一次性完成以下所有维度的分析并分段输出：\n1. 项目文件结构概览和整体架构\n2. …"
  outputs:
    full_analysis: analysis_result
```

完整文件见：`workflows/requirement_batch_20/rb20_r18.yaml`。

#### 8.3.1 端到端执行：`myflow run`（batch 18 / `rb20_r18`）失败复盘

本节记录 **工作流 YAML 已通过校验、实际 `myflow run`** 时的失败形态（与 **§8.3** 侧重「Composer 合并 / `MERGEABLE_LLM_ANALYZE`」互补）。复现条件与批量一致：`requirement_batch_io/run_specs.yaml` 中 id **`18`** 的 `inputs`（`zip_path`、`output_path`），夹具 **`requirement_batch_io/fixtures/r18_repo_sample.zip`**，模型 **DeepSeek**（`api.deepseek.com`）。

**失败落点：** 在 **「测试用例质量」** 对应的 **`llm_verify`** 步多次 **`passed: false`**，触发 `on_fail` 回跳与 `max_retries` 用尽后整次 run **`failed`**；若始终卡在该 verify，后续 **API 文档 verify** 等步可能未轮到或同样进入重试链。（具体 **step id** 以仓库内当时版本的 `rb20_r18.yaml` 为准；**§8.3** 表格为骨架示意。）

**`verify_result` 多轮比对结论：**

| 观察 | 含义 |
|------|------|
| **各轮主旨高度一致** | 不是「每轮换一个完全不同的扣分点」式的质检漂移；核心矛盾集中在同一类合规叙述上。 |
| **高频扣分点** | ① 待检内容**难以被认定**已针对「分析报告中点名的、测试覆盖不足的模块」；② 生成侧易出现 **`add()` 等偏通用**的测试示例，被判与仓库语境/报告绑定不足；③ `criteria` 若强依赖「分析报告中的点名」，而质检侧对 **artifact 的可见信息量** 不足时，易落成「正文里必须出现报告措辞/引用」的**偏严**解读。 |

**归因（引擎 / 编排 / 提示）：**

| 类型 | 说明 |
|------|------|
| **反馈回路（主因）** | Runner 在 `on_fail` 时会写入 `context["_prev_error"]`，但 **`llm_generate` 默认不会读取**；若 YAML 未在 `instruction`/`context` 中显式内插 `{{_prev_error}}`（及可选 `{{_attempt}}`），重试近似**盲改**，与「每轮报同类问题却改不动」的形态一致。 |
| **判据与信息量（次因）** | 若 `criteria` 要求「必须针对分析报告指出的模块」，建议在 **`artifact` 中同时附上**可对照的分析摘要/片段（或收紧 `criteria` 为仅凭测试代码与已给材料可检查的条目），否则 verify 模型容易**过度依赖**「待检字符串里是否像抄了报告」。 |
| **线性步骤编排** | `on_fail` 仅将执行指针跳回较早步骤 **id**；其后仍按步骤 **id 递增**执行中间步。若「仅测试 verify」失败而中间仍夹 **「生成 API 文档」** 等步，会**无谓重复生成**并带来内容漂移成本。缓解：让 **verify 紧挨**对应 **generate**，或拆 **子工作流** 使失败回跳范围局部化。 |
| **引擎层（已修）** | 技能级 `AsyncRetrying` 曾对**所有**异常重试，导致 `SkillExecutionError`（含 verify 业务失败）在同一轮内**多次调用模型**、日志条数放大；现对 **`SkillExecutionError` 不再做 tenacity 重试**（`src/myflow/engine/runner.py`）。 |

**建议（落地优先级）：**

1. **YAML**：为处于 `on_fail` 环内的 **`llm_generate`** 增加对 `{{_prev_error}}` / `{{_attempt}}` 的引用；并调整步骤顺序或子工作流，避免「修测试却反复重跑 API 生成」。  
2. **`llm_verify`**：保证 `artifact`（及 `criteria`）与「须引用分析报告」类要求**信息量匹配**（例如 artifact 内结构化拼接「分析报告摘要 + 测试正文」——仓库内 YAML 若已演进，以当前文件为准）。  
3. **Composer / `composer_system.md`**：在「verify + `on_fail`」few-shot 中显式示范 **`_prev_error` 回流**写法，降低漏配率。

### 8.4 边界情况：`condition`、语义拆步与校验的关系

| 问题 | 当前行为 |
|------|----------|
| **是否「新的阻塞级」？** | 是。`MERGEABLE_LLM_ANALYZE` 在 **`BLOCKING_WARNING_CODES`** 中，与 error 一样会阻止 **`execution_ready()`**，并驱动 Composer 重试。 |
| **带 `condition` 的两步、主输入仍相同** | 校验**不**解析、**不**豁免 `condition`。只要两步的 `content` 字符串 strip 后相同，仍会报警。 |
| **用户要求「先做 A、再看结果是否做 B」** | 若两步仍都对同一变量整段 `"{{原始正文}}"`，会被要求合并。**合理建模**：第二步 `content` 改为引用 **A 的产物**（如 `{{analysis_a}}`），或 **一步合并**并在 instruction 写清顺序；必要时用**不同拼接模板**使 `content` 字面不等（不推荐首选）。 |
| **下游需要两个不同变量名引用** | 校验不关心下游。合并后通常仍是一个 `analysis_result`，靠 **instruction 分段标题** + **`file_writer` 内插**；若业务强依赖两个上下文 key，应通过 **不同主输入字面量**（引用前序片段）实现拆步，而非两次相同 `"{{zip}}"`。 |

设计文档与 **`composer_system.md`** 中「校验器落地与合理拆步」小节与此一致；若未来引擎支持「有条件豁免」，再以实现为准更新本节。

---

## 9. Composer 提示词修订摘要与新 prompt 下生成效果

### 9.1 `composer_system.md` 修订要点（相对「仅有合并文字说明」的早期版本）

以下条文均已在仓库 `src/myflow/prompts/composer_system.md` 落库；与 **§7** 案例讨论、**§8** 校验互补。

| 主题 | 内容摘要 |
|------|----------|
| **合并判定（机械规则）** | 与业务无关：同 `action` + `llm_analyze`/`content` 或 `llm_generate`/`context` 的结构同等价即须合并；内联示例仅用 **`{{X}}` 级占位**，避免 zip/代码审查长例过拟合。 |
| **校验器与合理拆步** | 说明 **`MERGEABLE_LLM_ANALYZE` 不看 `condition`/语义**；分支需求通过「第二步 `content` 引用 A 的产物」或「一步合并 + instruction 顺序」建模（与 **§8.4** 一致）。 |
| **递进分析链** | 长链路中避免每一步把原始 CSV/日志全文重拼进 `content`；后续步优先绑定 **`{{前序结构化产物}}`**。 |
| **同类短变体（多平台文案等）** | 优先 **单次 `llm_generate`** + instruction 分段编号，或 **`file_writer` 章节内插**；避免多步 **`context` 字面完全相同** 仅换 instruction。 |
| **双花括号规范（对齐 P1）** | **禁止**用单花括号 `{var}` 引用工作流/步骤上下文变量；必须用 **`{{var}}`**（见条文「禁止用单花括号引用上下文变量」）。 |
| **few-shot 说明** | 条文管对错，few-shot 管完整形态；须保留合并正例、禁止拆步反例（`multi_analysis_assembly.yaml` 已中性化叙事）。 |

**维护注意（避免生成时报错）：** 系统提示文件经 Python **`str.format(skill_cards=…, examples=…)`** 注入；若在文中需要向模型展示字面量 **`{{variable}}`**，在 `.md` 源文件中须写成 **`{{{{variable}}}}`**，否则裸 `{name}` 会触发 `KeyError`。

### 9.2 配套引擎改动（便于对照）

| 组件 | 说明 |
|------|------|
| **`MERGEABLE_LLM_ANALYZE`** | `WorkflowValidator._check_mergeable_llm_analyze_steps`：多步 `llm_analyze` 且 `inputs.content` 字符串 strip 后完全相同 → 阻塞级 warning（见 **§8**）。 |
| **`execution_ready()` / `compose_feedback_summary()`** | `ValidationReport`（`src/myflow/engine/models.py`）：阻塞级 warning 阻止生成成功闭环，并把说明回流 Composer。 |

### 9.3 新 prompt + 校验下的工作流再生效果（抽样）

**共同条件：** `MYFLOW_CHAMPION_CACHE_ENABLED=false`（避免 Champion 沿用旧 YAML）；需求全文与 `requirement_batch_io/batch_manifest.yaml` 对应 id 的 **`requirement`** 字段一致；模型以一次实测为准（日志为 **DeepSeek** `api.deepseek.com`）。先 **删除** 目标 `rb20_r*.yaml` 再 **`myflow generate -o …`**，避免失败时旧文件残留。

| batch id | 输出文件 | 步数 | HTTP 次数（观测） | 效果摘要 |
|----------|-----------|------|-------------------|----------|
| **04** | `rb20_r04.yaml` | 3 | 1 | **一步** `llm_generate` 产出三平台文案（instruction 分段）；`context` 使用 **`{{product_name}}` / `{{core_selling_points}}`**（对照旧版单花括号 `{product_name}`）。 |
| **11** | `rb20_r11.yaml` | 5 | 1 | `file_reader` → **一步** `llm_analyze`（分类+实体）→ `llm_generate` → `llm_verify` → `file_writer`；路径与引用为 **`{{tickets_file}}`** 形式。 |
| **16** | `rb20_r16.yaml` | 4 | 2 | **首轮若多段同 `{{ebook_content}}` 则命中合并校验 → 第二轮收敛**；最终 **一步「全书多维度分析」** `llm_analyze`，`full_analysis` → verify → 落盘。 |
| **17** | `rb20_r17.yaml` | 9 | 1 | 三步 `llm_analyze` 的 **`content` 依次为** `pdf_contents` → `extracted_data` → `comparison_analysis`（字面**不相同**，不触发 `MERGEABLE_LLM_ANALYZE`，属「递进引用前序产物」类合规拆步）。 |
| **18** | `rb20_r18.yaml` | 7 | 2 | 见 **§8.3**（合并分析 + 后续基于 `full_analysis`）。 |
| **20** | `rb20_r20.yaml` | 11 | 2 | 多步分析；各步 `content` 为**不同拼接模板**（校验不按「递进偏好」拦）；含叙事报告、`file_writer` 组装报告包。 |

**解读：** **P9 / 合并规则**在 **同字符串 `content` 重复** 的场景下由 **§8** 硬性兜底；**§9.1** 中递进链、双花括号、短变体合并等条文主要改善 **04 / 11 / 16 / 18** 及 **17** 的建模方式；**20** 仍依赖条文自律（当前未对 `llm_generate` 做同构校验）。

### 9.4 维护说明

- 更新 **`composer_system.md`** 若改变合并或变量引用约定，请同步检视 **§7 / §8 / §9** 与本表 **§9.3**。  
- 再生对照样例时优先 **删 YAML → 关 Champion → generate**，并在 §9.3 更新 **步数 / HTTP 次数 / 摘要**（注明模型提供方若有变更）。

---

## 10. 批量执行（20 条）失败类型、建议与修复优先级

以下对应一次全量跑 **`scripts/requirement_batch_report.py`** 后的失败归类（含 **01 / 10 / 13 / 17 / 18 / 19**）。修复成本按**低到高**排序如下。

### 10.1 第 3、4 类：配置 / 夹具数据（优先直接修）

| ID | 现象概要 | 根因与建议 |
|----|-----------|------------|
| **18** | CLI 报未知 `--input` | **`run_specs.yaml` 与工作流契约不同步**：`rb20_r18.yaml` 声明的是 **`output_path`**，若 run_specs 写 **`report_path`** 会报错。**修复**：改 run_specs 或改工作流 YAML，使**键名一致**即可（通常改一行）。 |
| **19** | （历史）目录被当单文件读 | **已解决**：`file_reader` 在运行时识别**目录**并递归读取（及 `.zip`、逗号多路径）；夹具可继续用目录。 |

### 10.2 第 2 类：`multi_file_reader` → `llm_analyze` 类型不匹配（13、17）

**历史链路：** 旧版 `multi_file_reader` 曾输出 **`file_contents: dict`**，`{{var}}` 传到 `llm_analyze.content`（`str`）会校验失败。

**当前：** **`file_reader`**（与别名 **`multi_file_reader`**）统一输出 **`file_content: str`**；Runner 仍可对其它来源的 **`dict`** 向 `str` 字段做可读序列化（兜底）。见 `src/myflow/skills/file_ops.py`、`src/myflow/engine/runner.py`。

### 10.3 第 1 类：`llm_verify` 与生成质量（01、10）

| ID | 说明 | 建议 |
|----|------|------|
| **01**（翻译验证） | 验证模型主观认为「不够论文体」等，与夹具是否像真论文有关，**忠实原文**也难写成机械标准 | **夹具**：换更接近目标的英文材料；**流程**：翻译类任务可考虑**不做 verify** 或把 criteria **限定为可客观检查的条件**（如长度下限、章节标题不删）；**Composer**：可建议弱主观场景少配 verify。 |
| **10**（测试代码） | 生成测试 **import 了夹具中不存在的符号**——属 **生成步**问题，而非 verify 逻辑假阳性 | 在 **`llm_generate`** 系统提示中强调：测试代码的 **import 须与参考资料中真实模块/符号一致**（见 `llm_call.py`）；Composer 也可在生成测试的步骤 instruction 里显式绑定源路径对应的模块名。 |
| **18**（代码仓审查） | **`llm_verify`（测试用例质量）** 多轮不通过：多轮 `verify_result` 主旨一致，扣分集中在「未显式绑定分析报告中的低覆盖模块 / 测试偏通用」等；若未回流 `_prev_error` 则重试偏盲；线性编排可致 **API 文档被连带重生成** | 见 **§8.3.1**；YAML 补 `{{_prev_error}}`、调整 verify 与 generate 的邻接/子工作流、`artifact` 与 `criteria` 信息量对齐；引擎侧 **`SkillExecutionError` 不再技能级三连重试** 已减轻噪声与成本 |

### 10.4 推荐执行顺序（与成本一致）

1. **18**：对齐 `run_specs` 与工作流输入名（**零架构风险**）。  
2. **13 / 17**：已由统一 **`file_reader`** 字符串输出 + Runner 兜底覆盖。  
3. **10**：补强 **`llm_generate`**（及按需 Composer instruction）。  
4. **19**：已由 **`file_reader` 目录识别**处理；若仍失败再查路径权限与体量限制。  
5. **01**：换夹具或放宽 verify / criteria，**优先级最低**（随机性与主观性较大）。

### 10.5 读取技能与批量配置修正后的 20 条通过率复盘

**数据来源说明：** 修正前数字来自当时仓库内的 **`requirement_batch_io/SUMMARY.md`**（脚本全量跑统计，约 **13/20 = 65.0%** 端到端成功）。此后按**读盘/配置修复**与**复测**分次累加；**`myflow run` 使用 `requirement_batch_io/run_specs.yaml` 中同 id 的 `inputs` 与路径**；模型为 **DeepSeek**（`api.deepseek.com`）。

| 口径 | 结果 |
|------|------|
| **修正前（SUMMARY 快照）端到端成功** | **13 / 20（65.0%）** |
| **原已成功、且复测未重跑但视为仍成立** | 02, 03, 05, 06, 07, 08, 09, 11, 12, 14, 15, 16, 20（**13 条**） |
| **原失败、因统一 `file_reader` / `run_specs` / 夹具而新转成功** | **13**、**17**、**19**（**+3**） |
| **原 SUMMARY 记失败、复测整条 completed** | **04**（与 `run_specs` 一致的三项 `--input`，**2026-04-19 重跑成功**；旧汇总表将 **04** 判失败属过时或当次随机未过 verify）（**+1**） |
| **当前通过率（合并）** | **17 / 20 = 85.0%** |
| **仍端到端失败（截至复测）** | **3 条：01, 10, 18** |

**复测记录（2026-04-19）：**

- **01**：仍失败——**Step 4 `llm_verify`（验证翻译质量）**，多次重试后不通过（术语/忠实度等主观核验）。读盘正常。  
- **04**：**completed**——Step 1～3 均 OK，全程约 21s。

**仍不通过条目的原因（与「读盘」关系）：**

| ID | 与读取技能修正的关系 | 当前主要失败面 |
|----|----------------------|----------------|
| **01** | 无关 | **`llm_verify`（翻译质量）**，见 **§10.3** |
| **10** | 无关 | **`llm_verify`（测试质量）**，见 **§10.3** |
| **18** | **读入与 CLI 已通**（`output_path` + zip 夹具） | **测试用例相关 `llm_verify`** 多轮不通过与编排/反馈问题，见 **§8.3.1**（非 `file_reader`） |

**维护：** 若需与 `SUMMARY.md` 中分条「成功/失败」及 `XX_last_run.json` **完全一致**，请在项目根重跑并覆写汇总：

`uv run python scripts/requirement_batch_report.py`
