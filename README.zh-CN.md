# 五类材料的载流子迁移率文献检索

[English](README.md) | [简体中文](README.zh-CN.md)

把文献线索、已有 PDF 清单和 agent 提取结果汇入可追溯的数据集，逐步补齐电子、空穴和双极性载流子迁移率。

覆盖五类材料：**COF、MOF、有机小分子／分子半导体、杂化钙钛矿、无机二维材料**。实验测量与理论计算分别记录。

流程：OpenAlex 发现论文 → Semantic Scholar 补充元数据与引文 → Crossref 核对 DOI → 去重与分类 → 匹配 PDF、合并已有提取结果 → 输出候选表和待补清单。

## v1 现在有什么

截至 2026-10-13，合并已有下载清单、五份提取表和新增检索结果后：

| 项目 | 数量 |
|---|---:|
| 去重后的候选论文 | 17,235 篇 |
| 待补数值证据或复核的论文 | 2,303 篇 |
| 已有明确迁移率数值的论文 | 406 篇 |
| 带原提取表核对标记及出处的论文 | 4 篇 |
| 规范化后的提取记录 | 2,144 条 |
| 匹配到本地或服务器 PDF 路径的论文 | 1,644 篇 |

4 篇的核对状态来自原提取表；下一阶段会回到原文复核。完整统计见 [v1 运行总结](V1_RUN_SUMMARY.md)。

仓库提供代码和汇总。明细、缓存和提取记录保存在运行机器的 `data/` 和 `reports/` 中。

## 先看这三个文件

| 文件 | 用途 |
|---|---|
| `reports/coverage_report.md` | 查看各材料类别的覆盖情况、数值证据和检索进度 |
| `data/priority_missing_papers.csv` | 安排下一批全文获取、数据补全与复核 |
| `data/candidate_papers.csv` | 查看全部候选、DOI、来源、分类和证据状态 |

待补清单中的 `local_pdf_paths`、`remote_pdf_paths` 可以帮助找到已有论文；`import_references` 和 `mobility_observations` 保留提取出处与多条数值记录。

## 开始使用

要求 Python 3.10 或更高版本。在项目目录运行：

```powershell
python -m pip install -e .
mobility-literature status
mobility-literature discover --max-results-per-query 100
```

这次运行将每组 OpenAlex 查询限制为最多 100 条。响应缓存和查询游标保存在 `data/cache/`、`data/checkpoints/`，日志使用 JSON 格式。提高上限后可以从已有进度继续：

```powershell
mobility-literature discover --max-results-per-query 500
```

需要配置 API 时，在当前终端设置环境变量：

```powershell
$env:OPENALEX_API_KEY = "your-openalex-key"
$env:SEMANTIC_SCHOLAR_API_KEY = "your-semantic-scholar-key"
$env:CROSSREF_MAILTO = "you@example.org"
```

程序从环境变量读取这些配置，API 请求支持重试。`--enrich-limit` 控制 Semantic Scholar 种子数量，`--neighbors-per-seed` 控制每个种子每种引文关系的扩展数量，`--crossref-limit` 控制 DOI 校验数量。

## 导入已有提取结果

把已有 CSV 导入一个新的规范化文件，再更新候选表：

```powershell
mobility-literature import "path/to/extracted-results.csv" --output "data/imported/batch_01.csv"
mobility-literature discover --max-results-per-query 0 --enrich-limit 0 --crossref-limit 0
```

第二条命令使用已有数据重建输出。`data/imported/` 中的规范化结果会自动合并；其他位置可通过 `--imports file1.csv file2.jsonl` 指定。

每批使用一个新的输出文件名。导入器保留原始字段和出处，一篇论文中的多次测量或计算分别保存。常用字段包括数值、单位、载流子类型、实验／理论、方法、温度、方向、材料、样品条件、原文摘录和页码／表图位置。

## 匹配已有 PDF

用已有下载清单补充候选，并在指定目录匹配 PDF 文件名：

```powershell
mobility-literature discover --max-results-per-query 100 --inventory "path/to/download-inventory.csv" --pdf-root "path/to/papers"
```

多个论文目录可重复传入 `--pdf-root`；服务器文件清单使用 `--remote-pdf-manifest "path/to/pdf-manifest.jsonl"`。路径匹配用于找到全文，数值证据由提取记录和原文核对提供。

## 四个证据状态

| 状态 | 含义 |
|---|---|
| `candidate` | 发现了论文线索，等待筛选 |
| `likely_contains_mobility` | 标题或摘要等元数据出现相关迁移率线索 |
| `confirmed_numeric_mobility` | 提取记录中有明确的电子、空穴或双极性迁移率数值及单位 |
| `verified_evidence` | 数值、上下文和原文位置带有核对记录，并保留核对来源 |

缺失字段留空。电导率、离子／质子迁移率和扩散系数作为排除项处理。材料类别由元数据筛选，不明确或混合类别的记录进入复核。

## 下一步怎么推进

1. **确定优先材料与数据类型。** 现有明确数值中，COF 有 13 篇、MOF 有 29 篇，可以先补这两类；按近期论文或模型需求选择实验、理论或两者。
2. **先完成一小批原文核对。** 从待补清单选 20 篇已有 PDF 的论文，逐条记录材料、数值、单位、方法、温度、方向和页码／表图位置，再导入。
3. **继续扩大文献覆盖。** 首轮 45 组查询中有 40 组达到 100 条上限。提高检索上限，并从已确认的论文扩展参考文献和引用论文。
4. **整理研究用数据表。** 将实验和理论记录分开，保留测量／计算条件及出处，按材料和方法检查可比性。

项目状态见 [PROJECT_STATUS.md](PROJECT_STATUS.md)，数据结构和实现安排见 [IMPLEMENTATION_PLAN.md](IMPLEMENTATION_PLAN.md)，检索策略见 [QUERY_STRATEGY.md](QUERY_STRATEGY.md)。
