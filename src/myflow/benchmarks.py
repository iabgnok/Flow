"""§13.4 基准需求与 §13.3 质量抽样需求（供基准测试与指标统计）。"""

from __future__ import annotations

# 与《MyFlow_完整设计文档》§13.4 一致：6 条标准需求
BENCHMARK_REQUIREMENTS: tuple[str, ...] = (
    "读取 /tmp/test.txt 文件的内容",
    "将文本 'hello world' 写入 /tmp/output.txt",
    "读取 data.csv 文件，用 LLM 分析趋势，生成报告并保存",
    "读取 README.md，用 LLM 翻译为中文，写入 README_CN.md",
    "读取项目代码文件，用 LLM 生成 API 文档，验证文档完整性，不完整则重新生成",
    "读取配置文件，用 LLM 检查安全风险，生成安全审计报告",
)

# §13.3 测量方法约定「约 20 条需求」：在 6 条标准集上补充短句变体，凑满 20 条且可独立生成
_QUALITY_EXTRA: tuple[str, ...] = (
    "读取单个文本文件并打印其内容到分析结果中",
    "把字符串内容写入用户指定的输出文件",
    "读取 CSV，总结列名与行数后用 LLM 写一段摘要",
    "读取 Markdown 文件并用 LLM 生成要点列表",
    "对日志文本做 LLM 异常模式检测并输出结论",
    "读取 JSON 配置并用 LLM 解释各字段含义",
    "读取多行文本，用 LLM 翻译成英文并保存到新文件",
    "读取源代码目录中的一个 .py 文件并生成函数列表说明",
    "读取环境变量说明文件并用 LLM 标出敏感项",
    "读取数据文件，用 LLM 判断是否存在明显离群值",
    "将用户提供的模板文本中的占位符替换后写入文件",
    "读取 README，提取安装步骤段落并写入 install_steps.txt",
    "读取小型配置文件，用 LLM 建议更安全的默认值",
    "读取文本，用 LLM 生成不超过 200 字的执行摘要",
)

QUALITY_SAMPLE_REQUIREMENTS: tuple[str, ...] = BENCHMARK_REQUIREMENTS + _QUALITY_EXTRA

assert len(QUALITY_SAMPLE_REQUIREMENTS) == 20
