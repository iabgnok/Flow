# 需求批量测试汇总（20 条）
本文件由 `scripts/requirement_batch_report.py` 自动生成。**技能命中率**与明细列一致：单条为「所有步骤 `action` 是否均属于引擎已注册技能」（与 `myflow.quality_metrics.all_actions_whitelisted` 相同）；总体比率为可评估工作流中命中条数 / 可评估条数（已成功加载为模型的工作流）。
## 目录约定
- **夹具与元数据**：`requirement_batch_io/fixtures/`、`batch_manifest.yaml`、`run_specs.yaml`
- **工作流定义**：`workflows/requirement_batch_20/rb20_rXX.yaml`（由 `myflow generate` 生成）
- **单次执行快照**：`requirement_batch_io/runs/XX_last_run.json`
## 生成工作流（示例）
在项目根执行，将 `requirement` 换为 `batch_manifest.yaml` 中对应 `requirement` 字段：
```bash
uv run myflow generate "……需求原文……" -o workflows/requirement_batch_20/rb20_r01.yaml
```
## 指标（可执行率由脚本计算）
- 已生成工作流文件数：**20** / 20
- 校验通过数：**20** / 20（分母为已生成文件数；当前已生成 20 个）
- 已配置非空 inputs 并尝试执行：**20** 条
- 执行成功数：**13** / 20
- **可执行率（对全体 20 条）**：13/20 = **65.0%**（未配置 inputs 的条目计为未执行）
- **可执行率（对已生成文件）**：13/20 = **65.0%**（当 n_gen=0 时为 0）
- **可执行率（对已配置执行用例）**：13/20 = **65.0%**（当未配置时为 0）
- **技能命中率（可评估子集）**：20/20 = **100.0%**（分母为「文件存在且 YAML 可解析为工作流」的条数；解析失败不计入）
- **技能命中率（对全体 20 条，缺失计未命中）**：20/20 = **100.0%**

## 明细表
| ID | 档位 | 名称 | 工作流 | 已生成 | 校验 | 执行 | 执行摘要 | 技能命中 |
| --- | --- | --- | --- | --- | --- | --- | --- | --- |
| 01 | 简单 | 论文翻译与摘要 | `workflows/requirement_batch_20/rb20_r01…` | 是 | 通过 | 失败 | Step 4 (验证翻译质量) 失败: 待检查内容存在以下问题： 1. 翻译不忠实于原文：原文是英文学术论文的替代品，但中文翻译中出现了"英文学术论文正文的替… | 是(5步) |
| 02 | 简单 | 客户评价情感分析 | `workflows/requirement_batch_20/rb20_r02…` | 是 | 通过 | 成功 | context_keys=['input_csv_path', 'output_csv_path', 'csv_content', 'analyzed_csv… | 是(4步) |
| 03 | 简单 | 会议纪要待办 | `workflows/requirement_batch_20/rb20_r03…` | 是 | 通过 | 成功 | context_keys=['transcript_path', 'transcript', 'action_items', 'confidence'] | 是(2步) |
| 04 | 简单 | 多平台营销文案 | `workflows/requirement_batch_20/rb20_r04…` | 是 | 通过 | 失败 | Step 2 (验证文案质量) 失败: 不通过。待检查内容存在以下问题：  1. **产品名称缺失**：所有文案中都没有提及具体的产品名称，只是用"这款产品"… | 是(3步) |
| 05 | 简单 | 访谈需求提取 | `workflows/requirement_batch_20/rb20_r05…` | 是 | 通过 | 成功 | context_keys=['interview_path', 'interview_content', 'analysis_result', 'confid… | 是(2步) |
| 06 | 中等 | 简历与 JD 匹配评估 | `workflows/requirement_batch_20/rb20_r06…` | 是 | 通过 | 成功 | context_keys=['resume_confidence', 'matching_analysis', 'matching_confidence', … | 是(7步) |
| 07 | 中等 | 电商文案 SEO 优化 | `workflows/requirement_batch_20/rb20_r07…` | 是 | 通过 | 成功 | context_keys=['seo_analysis', 'confidence', 'optimized_titles', 'selling_points… | 是(6步) |
| 08 | 中等 | 研报章节摘要与要点 | `workflows/requirement_batch_20/rb20_r08…` | 是 | 通过 | 成功 | context_keys=['output_path', 'report_content', 'structured_analysis', 'summary_… | 是(5步) |
| 09 | 中等 | 竞品分析报告 | `workflows/requirement_batch_20/rb20_r09…` | 是 | 通过 | 成功 | context_keys=['report_path', 'competitor_content', 'extracted_info', 'confidenc… | 是(5步) |
| 10 | 中等 | Python 代码审查与测试 | `workflows/requirement_batch_20/rb20_r10…` | 是 | 通过 | 失败 | Step 6 (验证测试质量) 失败: 不通过。原因： 1. 测试代码中引用了未定义的函数（add、multiply_by_two、clamp），这些函数没有… | 是(8步) |
| 11 | 中等 | 工单意图与实体分析 | `workflows/requirement_batch_20/rb20_r11…` | 是 | 通过 | 成功 | context_keys=['report_path', 'tickets_json', 'analysis_result', 'confidence', '… | 是(5步) |
| 12 | 中等 | 合同审查备忘录 | `workflows/requirement_batch_20/rb20_r12…` | 是 | 通过 | 成功 | context_keys=['contract_text', 'analysis_result', 'confidence', 'memo_content',… | 是(5步) |
| 13 | 中等 | 多源新闻综合简报 | `workflows/requirement_batch_20/rb20_r13…` | 是 | 通过 | 失败 | Step 2 (交叉比对分析) 失败: 1 validation error for LLMAnalyzeInput content   Input shou… | 是(5步) |
| 14 | 中等 | 问卷开放题主题聚类 | `workflows/requirement_batch_20/rb20_r14…` | 是 | 通过 | 成功 | context_keys=['survey_data', 'clustering_analysis', 'confidence', 'key_insights… | 是(6步) |
| 15 | 中等 | PRD 拆解与排期 | `workflows/requirement_batch_20/rb20_r15…` | 是 | 通过 | 成功 | context_keys=['tech_complexity', 'complexity_confidence', 'priority_recommendat… | 是(8步) |
| 16 | 复杂 | 电子书读书笔记 | `workflows/requirement_batch_20/rb20_r16…` | 是 | 通过 | 成功 | context_keys=['ebook_path', 'output_path', 'ebook_content', 'full_analysis', 'v… | 是(4步) |
| 17 | 复杂 | 行业年报研究 | `workflows/requirement_batch_20/rb20_r17…` | 是 | 通过 | 失败 | Step 2 (提取财务摘要和战略描述) 失败: 1 validation error for LLMAnalyzeInput content   Input… | 是(9步) |
| 18 | 复杂 | 代码仓库技术审查 | `workflows/requirement_batch_20/rb20_r18…` | 是 | 通过 | 失败 | 未知的 --input 参数: report_path。本工作流接受的参数名为: output_path, zip_path | 是(7步) |
| 19 | 复杂 | 课程本地化 | `workflows/requirement_batch_20/rb20_r19…` | 是 | 通过 | 失败 | Step 1 (读取课程素材) 失败: 读取文件失败: E:/项目/workflow3.0/requirement_batch_io/fixtures/r19… | 是(10步) |
| 20 | 复杂 | 用户增长分析 | `workflows/requirement_batch_20/rb20_r20…` | 是 | 通过 | 成功 | context_keys=['strategy_recommendations', 'strategy_verify', 'strategy_passed',… | 是(11步) |

## 校验失败详情（如有）
