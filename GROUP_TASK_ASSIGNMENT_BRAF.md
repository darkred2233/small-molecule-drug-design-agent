# 小分子药物设计 Agent 项目组员任务分配包

项目负责人：陈智泓

项目当前状态：BRAF 药物设计项目第一轮流程已跑通，系统已经完成分子生成、结构验证、规则过滤、候选评估、外部对接/逆合成细筛、排序、决策卡和报告导出。后续组员任务以“实验验证、结果复核、资料扩展”为主，不直接改动核心代码。

## 当前可用项目数据

项目 ID：`PROJ-8A2756E8CB`

靶点：`TGT-BRAF`

项目状态：`pipeline_completed`

报告文件：`C:\Users\zhihong\Downloads\BRAF_药物设计_PROJ-8A2756E8CB_report.json`

### 当前 Top10 候选物摘要

| Rank | Molecule ID | SMILES | Final decision | Score | Docking | ADMET | Synthesis |
|---:|---|---|---|---:|---|---|---|
| 1 | MOL-D87CC67DED | O=C(NCCO)c1ccccc1 | watch | 69.34 | GNINA, Vina -3.41, docking weak | hERG low, Ames low, risk 0.22 | AiZynthFinder route found, 1 step, confidence 0.99 |
| 2 | MOL-450DC51730 | CCCS(=O)(=O)Nc1ccc(F)c(C(=O)c2c[nH]c3ncc(SCC(=O)O)cc23)c1F | watch | 59.461 | GNINA, Vina -3.52, docking weak | hERG medium, Ames medium, risk 0.415 | AiZynthFinder route found, 3 steps, confidence 0.987 |
| 3 | MOL-14EA0E2E97 | NC(=O)c1ccccc1 | deprioritize | 37.521 | RDKit surrogate, Vina -5.77 | hERG low, Ames low, risk 0.22 | surrogate route found, 2 steps, confidence 0.862 |
| 4 | MOL-74243C4ADE | O=C(O)c1ccccc1 | deprioritize | 37.521 | RDKit surrogate, Vina -5.77 | hERG low, Ames low, risk 0.22 | surrogate route found, 2 steps, confidence 0.862 |
| 5 | MOL-657EB271C8 | CCOC(=O)c1ccc(F)cc1 | deprioritize | 37.006 | RDKit surrogate, Vina -5.95 | hERG low, Ames low, risk 0.22 | surrogate route found, 3 steps, confidence 0.837 |
| 6 | MOL-1294D2A393 | CCNc1ccc(F)cc1 | deprioritize | 36.598 | RDKit surrogate, Vina -5.85 | hERG low, Ames low, risk 0.22 | surrogate route found, 2 steps, confidence 0.856 |
| 7 | MOL-1484D1B68C | CCNc1ccccc1 | deprioritize | 36.271 | RDKit surrogate, Vina -5.77 | hERG low, Ames low, risk 0.22 | surrogate route found, 2 steps, confidence 0.87 |
| 8 | MOL-2E79BDA8AA | CCN(CC)C(=O)c1ccccc1 | deprioritize | 35.116 | RDKit surrogate, Vina -5.91 | hERG low, Ames low, risk 0.22 | surrogate route found, 3 steps, confidence 0.84 |
| 9 | MOL-9F0D6669C1 | COc1ccccc1 | deprioritize | 34.732 | RDKit surrogate, Vina -5.51 | hERG low, Ames low, risk 0.22 | surrogate route found, 2 steps, confidence 0.875 |
| 10 | MOL-908DD17F4D | CCOc1ccc(F)cc1 | deprioritize | 34.136 | RDKit surrogate, Vina -5.67 | hERG low, Ames low, risk 0.22 | surrogate route found, 2 steps, confidence 0.856 |

说明：当前 Top1/Top2 已有外部 GNINA 和 AiZynthFinder 结果，其余多数候选仍属于 RDKit surrogate 粗筛结果，可作为后续复核和对照组。

## 组员 A：BRAF 对接姿态复核与可视化实验

任务定位：计算实验验证 / docking pose analysis

难度：低到中等，主要是查资料、截图、整理结论。

### 任务目标

围绕当前 BRAF 项目 Top 候选物，复核系统给出的对接结果是否合理，重点解释为什么 Top1 虽然综合排序第一，但决策仍是 `watch` 而不是直接推进。

### 具体工作

1. 选取当前 Top1 和 Top2：
   - `MOL-D87CC67DED`
   - `MOL-450DC51730`

2. 收集 BRAF 活性口袋背景资料：
   - BRAF 典型 PDB 结构，例如 3OG7 或其他 BRAF-inhibitor 共晶结构。
   - 关键结合口袋残基。
   - 已知 BRAF 抑制剂常见相互作用类型，例如氢键、疏水作用、hinge binding、DFG 区域相关作用。

3. 用可视化工具查看对接姿态：
   - 推荐工具：PyMOL、UCSF ChimeraX、Discovery Studio Visualizer 任一即可。
   - 截图内容：配体在口袋中的位置、关键残基、可能氢键或疏水相互作用。

4. 对照系统结果解释：
   - Top1：GNINA Vina score = -3.41，标记为 docking weak。
   - Top2：GNINA Vina score = -3.52，标记为 docking weak。
   - 说明为什么系统把它们放入观察列表，而不是直接推荐实验推进。

### 交付物

文件名建议：`BRAF_docking_pose_review_组员A.pptx` 或 `BRAF_docking_pose_review_组员A.docx`

必须包含：

- BRAF 靶点口袋简介。
- Top1/Top2 分子结构和 SMILES。
- 每个分子的对接结果截图。
- 关键残基标注。
- 1 张对比表：分子、Vina score、pose 观察、优势、风险、是否建议继续优化。
- 结论：当前结果更适合进入局部优化，而不是直接作为最终候选物。

### 看起来高级的标题

“基于 BRAF 结合口袋的候选分子对接姿态复核与可视化分析”

## 组员 B：候选分子药物化学与可合成性复核实验

任务定位：Medicinal chemistry review / synthetic feasibility analysis

难度：低到中等，主要是查资料、画路线、解释结构风险。

### 任务目标

从药物化学角度复核当前 Top 候选物是否适合作为下一轮局部优化母核，并指出系统合成路线模块目前能说明什么、不能说明什么。

### 具体工作

1. 选取 4 个代表分子：
   - Top1：`MOL-D87CC67DED`
   - Top2：`MOL-450DC51730`
   - 对照分子 1：`MOL-14EA0E2E97`
   - 对照分子 2：`MOL-657EB271C8`

2. 做药物化学结构点评：
   - 分子大小是否合理。
   - 极性是否过高或过低。
   - 是否有明显可优化位点。
   - 是否存在潜在 PAINS、反应性基团或结构警示。
   - Top1 是否过于简单，是否可能缺少足够 BRAF 特异性相互作用。

3. 复核合成可行性：
   - 系统显示 Top1 AiZynthFinder route found，1 step，confidence 0.99。
   - 但当前 UI 展示更像“合成可行性摘要”，不是完整实验合成路线。
   - 需要人工补充至少 1 条可能的真实合成思路，例如从苯甲酰氯/苯甲酸衍生物与乙醇胺形成酰胺的路线。

4. 给出局部优化建议：
   - 保留酰胺连接基或芳香核心时，可以尝试哪些取代基。
   - 如何增强 BRAF 口袋结合。
   - 如何避免 ADMET 风险上升。
   - 哪些结构不建议继续扩展。

### 交付物

文件名建议：`BRAF_medicinal_chemistry_synthesis_review_组员B.docx`

必须包含：

- 4 个分子的结构表。
- 每个分子的药物化学优缺点。
- Top1 的可能合成思路图或文字路线。
- 对系统“合成路线”模块的评价：它目前是可合成性判断，不等于完整实验步骤。
- 下一轮局部优化建议 5-10 条。

### 看起来高级的标题

“BRAF 候选分子的药物化学可优化性与合成可行性复核”

## 组员 C：RAG 靶点资料与证据库扩展

任务定位：Knowledge base expansion / RAG evidence curation

说明：这部分已经安排给负责 RAG 的同学，可以继续做。

### 任务目标

继续扩充 BRAF 以及其他肿瘤靶点的高质量文献、专利、活性分子和结构证据。

### 交付物

- 每个靶点一个 `target_profile.md`。
- 每个靶点一个 `known_ligands.csv`。
- 每个靶点一个 `structures.csv`。
- 每个靶点 10 篇核心论文 metadata。
- 每个靶点 5-10 个专利 metadata。

## 推荐给老师看的分工描述

本项目由陈智泓完成 Agent 主体系统搭建与端到端流程实现，其他组员围绕系统输出开展独立验证与证据补充：

- 组员 A 负责 BRAF 候选分子的对接姿态复核与可视化验证。
- 组员 B 负责候选分子的药物化学可优化性和合成可行性复核。
- 组员 C 负责靶点知识库和 RAG 证据库扩展。

这样的分工可以体现：

- 系统开发已经完成。
- 组员参与了结果验证、证据扩展和药物化学解释。
- 每个人都有独立交付物。
- 不需要让组员改动核心代码，避免影响已完成系统。

## 建议时间安排

| 时间 | 组员 A | 组员 B | 组员 C |
|---|---|---|---|
| 第 1 天 | 收集 BRAF 结构和口袋资料 | 整理 Top 候选结构和性质 | 确定靶点扩展清单 |
| 第 2 天 | 完成对接姿态截图 | 完成药物化学点评 | 收集论文和专利 metadata |
| 第 3 天 | 写对接复核结论 | 补充合成可行性分析 | 整理 RAG 导入文件 |
| 第 4 天 | 做 PPT 或报告 | 做 Word 报告 | 提交资料包 |

## 最终汇总到总报告时的写法

可以写成：

“在 Agent 完成自动化候选生成与排序后，项目组进一步开展了三类人工复核工作：其一，对 BRAF 结合口袋中的 Top 候选物进行对接姿态可视化分析；其二，从药物化学角度复核候选分子的可优化性与合成可行性；其三，扩展靶点相关文献、专利和结构证据，用于增强 RAG 知识库。上述工作用于验证系统输出的可靠性，并为下一轮局部优化提供依据。”

