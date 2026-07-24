# 《Autonomous biomedical research with an artificial intelligence agent》项目对照笔记

## 版本说明

- Science 正式论文：Kexin Huang 等，2026 年 7 月 9 日，DOI `10.1126/science.adz4351`。Science 摘要将系统称为 Biomni，并概括了工具发现、检索增强规划、代码执行、多模态分析、蛋白稳定性优化、湿实验仪器编排和可检验协议生成等能力。[Science DOI](https://doi.org/10.1126/science.adz4351)
- 可公开阅读全文的前身版本：`Biomni: A General-Purpose Biomedical AI Agent`，bioRxiv 2025，DOI `10.1101/2025.05.30.656746`。本文中的架构数字和实验细节主要据此核对。[bioRxiv 全文](https://www.biorxiv.org/content/10.1101/2025.05.30.656746v1.full)
- 官方实现：Stanford SNAP 的 Biomni 仓库。仓库会持续更新，不能把当前代码状态完全等同于论文冻结版本。[官方 GitHub](https://github.com/snap-stanford/Biomni)

## 论文核心机制

Biomni 将系统拆成两个主要部分：

1. `Biomni-E1`：统一的生物医学动作空间。
2. `Biomni-A1`：根据用户目标检索动作、制定计划并执行的智能体。

预印本报告，作者从 25 个 bioRxiv 学科、共 2,500 篇近期论文中抽取任务、软件和数据库，经人工筛选、实现和测试后形成 150 个专业工具、105 个软件包和 59 个数据库。关键点不是工具数量，而是每个动作都经过人工审查并有测试用例。

收到用户问题后，Biomni-A1：

1. 用单独的检索机制选出当前任务真正相关的工具、数据库和软件，避免把整个动作空间塞入上下文。
2. 生成编号的分步计划。
3. 用 Python、R 或 Bash 代码组合动作，支持循环、条件和并行，而非固定模板。
4. 执行代码并读取 observation。
5. 根据 observation 调整后续计划，直到形成答案。

论文的消融结果支持“环境接地 + 代码中心规划”的价值：在其八类真实任务基准上，预印本报告 Biomni 相对基础 LLM、普通编码代理和 ReAct 变体的平均相对提升分别为 402.3%、43.0% 和 20.4%。每个任务平均涉及约 6 到 24 个步骤。数字只适用于论文定义的任务和指标，不能直接外推为药物设计成功率。

湿实验方面，公开预印本最明确的验证是 B2M sgRNA 克隆：Biomni 设计 sgRNA、引物、Golden Gate 流程、筛选和测序验证方案；实际实验由科学家按协议执行，两个挑取克隆均获得正确测序结果。因此，“能生成并验证协议”不等于预印本中的系统已经无人值守地完成全部实验。Science 正式版摘要还提到湿实验仪器编排，但其具体边界应以正式正文和补充材料为准。

作者明确承认：覆盖领域仍有限；偏重近期论文会漏掉经典方法；系统在临床判断、原创实验推理、分析方法发明和深层生物学综合方面仍不稳定。官方仓库还明确警告，当前 LLM 生成代码以完整系统权限运行，生产使用必须隔离和保护敏感数据。

## 与本项目的对应关系

本项目已经具有一个较好的“受控计算闭环”骨架：

- `RoundStrategyAgent` 根据项目、工具状态和上一轮摘要生成策略草稿，并要求用户确认。
- `RoundOrchestrator` 运行生成、对接、ADMET、逆合成、排名、自我反驳和报告，并创建下一轮草稿。
- `scientific_execution.py` 区分 L0/L1/L2/L3 证据级别，不把替代计算冒充外部模型或实验结果。
- 能力快照、执行计划、workflow packet、manifest、哈希和来源版本为结果复现提供了比自由代码执行更强的审计基础。
- `Critique`、`ReasoningTrace` 和 `DecisionCard` 已能保存支持证据、反对证据、不确定性和下一步动作。

但现有闭环仍主要是固定计算流水线，不是 Biomni 式观察驱动研究循环：

- `run_round()` 的阶段顺序是硬编码的，不能根据中间观察增删动作或回退重试。
- 下一轮策略上下文主要包含上一轮候选数量、campaign 摘要和前 50 名的 ID/总分/决定，没有输入逐分子的对接、ADMET、合成、结构变化及失败原因。
- 策略 schema 虽然包含 `property_constraints`，确认执行时只转换 `campaign_config` 和 `assessment_config`；这些性质约束没有完整编译进各生成任务。因此一部分策略目前只是“被记录”，并没有真正控制生成。
- `SARAgent` 和 `sar_to_generation_constraints()` 已存在，但没有接入正式 round 主线；而且当前 SAR 主要基于 docking，不是实验活性 SAR。
- 数据模型允许种子配体携带活性值，但还没有规范的 assay/observation 模型来保存单位、实验条件、重复、误差、批次、对照和 QC。
- `requires_approval`、审批表和审批 API 已存在，但执行器没有用审批状态阻断相应阶段；当前阶段级审批还不是强制门。

## 最值得借鉴的改造

### P0：先把策略变成真正可执行的合同

建立 `Strategy -> Validated Action DAG -> Tool Request` 编译层。每个策略字段必须满足以下三选一：

- 被明确映射到某个工具参数或后处理过滤器；
- 被标记为仅供解释、不参与执行；
- 因当前工具无法支持而在预检阶段报 blocker。

优先修复 `property_constraints` 的传递，并为 hERG、Ames、溶解度等模型指标明确区分：生成目标、生成后过滤、排名权重、硬阻断。这样可避免界面看起来在“按 ADMET 优化”，实际只在末端筛选。

### P0：把下一轮输入从排名摘要升级为 observation packet

为每个 parent-child 分子对记录：结构变换、对接变化、各 ADMET 端点变化、路线变化、证据等级和失败原因。下一轮 planner 应读取匹配分子对和 Pareto 前沿，而不仅是 Top N ID。

建议增加结构化对象：

- `Hypothesis`：哪种结构变化预计改善哪个指标，以及为什么。
- `ExperimentProposal`：要生成或测试哪些分子、包含哪些阳性/阴性对照、成功和否证标准。
- `Observation`：计算或实验结果、单位、条件、重复、误差、QC 和来源。
- `HypothesisEvaluation`：支持、反驳或信息不足。

### P1：建立小而精的药物设计 Action Registry

借鉴 Biomni-E1 的动作空间，但不追求数量。把现有 P2Rank、CReM、TargetDiff、AutoGrow4、Vina、GNINA、ADMET-AI 和 AiZynthFinder 注册为带类型的动作。每个动作声明：

- 输入/输出 schema；
- 前置资源和许可证；
- 证据等级上限；
- 时间、GPU 和候选数量预算；
- 可恢复错误与重试策略；
- 产物和 provenance；
- 单元测试/金标准样例。

planner 只从 registry 检索一个小子集，再生成受 schema 限制的 DAG。不要直接照搬 Biomni 的“LLM 生成任意 Python/R/Bash 并以完整权限运行”。

### P1：把 RAG 从文献问答扩展成程序性知识库

当前 RAG 主要服务靶点资料和反证检索。可新增 `know-how` 文档类型，保存：

- 工具适用边界与常见失败；
- 对接/ADMET/逆合成结果的正确解释；
- 实验协议模板和 QC；
- 何时需要补充计算或人工复核。

每份 know-how 需要版本、来源、许可证、适用条件和失效日期。检索结果进入 action planner，同时进入报告的证据引用。

### P1：引入观察驱动的动态重规划，但保留安全边界

允许受控分支，例如：

- 若 GNINA 姿态不稳定，则调整网格或补跑另一种 docking，而不是继续正式排名。
- 若一个 scaffold 系列普遍出现 hERG 风险，则建立“降低碱性/脂溶性”的可检验假设，并在下一轮分配部分预算验证。
- 若 AiZynthFinder 找不到路线，则在保留核心相互作用的前提下启动可合成性导向的 CReM campaign。

动态计划只能调用 allowlist action，且每个分支都要写入 manifest。高成本计算、外部数据发布和实验任务必须等待审批。

### P2：先打通“实验任务单导出 -> 人工执行 -> 结果回传”

不要一开始就连接机器人。先增加标准化 assay work order 和 result import：候选、批次、实验端点、单位、浓度梯度、重复、对照、验收标准和安全说明。导入后将结果标为 L3，并触发假设评价和下一轮建议。

这能获得论文中最重要的真实反馈闭环，同时保留实验人员对条件、风险和异常的控制。

### P2：建立项目自己的端到端基准与消融

不要只测试 API 和适配器是否运行。建立若干冻结任务包，例如 BRAF：

- 已知活性/非活性分子盲测；
- 已知 SAR 的恢复能力；
- 结构诱饵识别；
- 可合成性路线命中；
- 多目标 Pareto 选择；
- 工具缺失和错误输出时是否正确降级。

对比固定流水线、动态 planner、无 RAG、无自我反驳、无实验 observation 等变体。评价科学正确性、校准、成本、可复现性和人工审核时间，而不是只评价 LLM 文本质量。

## 推荐目标架构

```text
用户目标/约束
  -> 检索相关动作与 know-how
  -> 生成带假设和成功标准的 Action DAG
  -> schema 校验、能力预检、预算和审批
  -> 执行 allowlist 工具
  -> 产出 Observation + artifact + manifest
  -> 假设评价/反证/不确定性分析
  -> 人工决定：继续计算、提交实验、停止或修改目标
  -> 实验结果回传为 L3 Observation
  -> 下一轮重规划
```

## 总体判断

本项目不需要变成一个无边界的通用 Biomni。最有价值的路线是：保留现有的领域专用工具链、证据等级和审计能力，引入 Biomni 的“动作检索、可执行计划、观察驱动重规划和系统化基准”。近期最关键的工程工作是把策略约束真正接到执行器，并建立结构化 observation/hypothesis 数据模型；在这两项完成前，增加更多 agent 名称或更多生成模型不会形成更强的科研自主性。
