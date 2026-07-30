# 小分子药物设计 Agent 下一步优化报告

## 项目当前局限性

当前系统会“自动跑流程”，但还不会“像研究人员一样根据结果改变研究计划”。

两者看起来很像，实际差别很大。

自动跑流程像一条工厂流水线：原料进入后，依次经过生成、对接、ADMET、排序和报告。只要每台机器没有报错，系统就认为任务完成。

药物开发智能体更像一个受监督的研究助理：它首先确认研究对象正确，然后解释证据、提出假设、设计对照；如果中途发现靶点错了、评分不可信或候选物过于相似，它会停止原计划并提出更合适的验证动作。

### 当前能力成熟度

| 能力 | 当前水平 | 通俗解释 | 主要缺口 |
| --- | --- | --- | --- |
| 工具串联 | 较好 | 能把多个计算工具接起来跑 | 工具成功不等于科学结论正确 |
| 数据追踪 | 较好 | 能保存分子、分数、文件和轮次 | 缺少假设、结构变换和实验条件的完整谱系 |
| 自动生成 | 已具备 | 能产生很多候选结构 | 搜索容易同质化，可能专门迎合评分函数 |
| 自动排序 | 已具备 | 能把多个指标合成排名 | 固定总分掩盖多目标权衡和不确定性 |
| 报告解释 | 初步具备 | 能生成中文说明和风险提示 | 仍有模板化、语义误判和逐分子差异不足 |
| LLM 推理 | 局部具备 | 能写策略、SAR 和反驳文字 | 推理结果不能稳定编译成受控动作 |
| 科学校准 | 较弱 | 有部分证据等级和字段 | 靶点身份、重对接和富集验证未形成硬门禁 |
| 从结果学习 | 较弱 | 可以把上一轮候选带到下一轮 | 不知道哪个改动造成哪个端点变化 |
| 实验闭环 | 基础模型存在 | 数据库已有 assay/bioactivity 概念 | 缺少条件、误差、QC 和假设评价闭环 |
| 受控自治 | 尚未形成 | 目前按预设顺序执行 | 缺少动态重规划、停止条件和动作注册表 |

### 下一阶段最重要的五件事

1. **先保证研究对象正确**：靶点、结构、链、口袋和对接协议必须能够相互证明一致。
2. **让分数有参照物**：通过共晶配体重对接和已知活性/诱饵测试，为 Vina、GNINA 建立可信度边界。
3. **让 LLM 提出可检验假设**：不再只说“降低风险”，而要说明改哪里、为什么、预期改善什么、如何证明自己错了。
4. **让确定性代码控制执行**：LLM 的提议必须经过化学合法性、证据、预算和审批校验，才能变成真实工具动作。
5. **让每轮真正产生知识**：准确记录父分子、结构变换、各端点变化和实验结果，让下一轮基于已学到的 SAR，而不是重新猜。

### 为什么不能简单地“换更强 LLM”

更强的模型可能写出更像专家的文字，但不会自动修复错误靶点、未校准对接、不精确父子关系或失效的审批门。

如果输入数据没有明确语义，模型只会更流畅地解释错误数据；如果输出没有 schema 和执行约束，模型只会更有说服力地提出无法执行或无法验证的建议。

因此，模型能力和系统约束必须同时升级。最理想的关系不是“LLM 代替规则”，而是“LLM 负责提出研究假设，规则和工具负责验证与执行”。

---

## 1. 现状

可以把当前系统理解成一条很完整的自动化流水线：给它一个受体、一个口袋和一批种子分子，它可以生成候选物、计算性质、做对接、预测风险、排序并生成报告。

但真正的药物研发不是“跑出最高分就结束”。它更像一个不断提出问题和验证问题的循环：

1. 先确认研究对象和实验条件没有错；
2. 根据已有数据提出一个具体、可被推翻的假设；
3. 设计一组能够区分“假设成立”与“假设不成立”的分子或实验；
4. 得到计算或实验结果；
5. 判断结果支持还是反驳了假设；
6. 再决定下一轮该保留什么、探索什么、停止什么。

当前系统主要完成了第 3 步中的一部分计算执行，以及第 4 步中的部分模拟结果收集；第 1、2、5、6 步仍主要依赖用户或固定规则。因此，它应被定位为**药物发现决策支持系统**，而不是可以自主宣布候选药物有效的系统。

---

## 2. 问题分析

### 2.1 “低风险却建议降低风险”不是单纯文案错误

你看到的现象是：页面写着“hERG 风险为 low_risk”“Ames 风险为 low_risk”，下一轮建议却仍然要求“优先降低 hERG 风险”“避开潜在诱变警示片段”。

表面上，这是字符串或枚举值没有统一：报告代码识别 `low`，而模型输出的是 `low_risk`。但它暴露的是更深层的问题：系统没有把“原始事实”“风险解释”“下一步行动”分成不同层。

一个可靠系统至少要区分：

| 层次 | 应该回答的问题 | 示例 |
| --- | --- | --- |
| 原始证据层 | 工具到底输出了什么？ | `hERG = low_risk` |
| 解释层 | 这代表什么可信度和适用范围？ | “模型预测未见明显 hERG 警示，但仅适用于模型训练域内化合物” |
| 决策层 | 是否需要为此改变下一轮设计？ | 低风险通常不触发 hERG 优先优化；高风险才触发 |
| 行动层 | 具体改什么、怎么验证？ | “降低碱性中心 pKa，同时保留关键氢键；重新计算 hERG 和对接姿势” |

当前报告层把这些层次混在了一起：先把低风险文本放进“风险列表”，再靠关键词生成行动建议。只要文本里出现 hERG 或 Ames，模板就会被触发。即使修复 `low_risk` 的识别，这种“先拼句子、再读句子”的机制仍然容易在下一个字段名变化时再次出错。

### 2.2 AutoGrow 的负分不等于可相信的活性

Vina 分数越负，通常表示该打分函数认为姿势更有利。但它不是实验结合活性，也不是跨靶点可直接比较的通用单位。

第二、三轮产生了较低的 Vina 分数，说明搜索器能找到在当前受体和当前盒子里看起来“合适”的分子。它不说明这些分子能结合真实靶点，原因包括：

- 受体是否真的是预期靶点尚未被硬性核验；
- 口袋来自 P2Rank 预测，可能不是功能口袋；
- 没有用已知共晶配体做重对接，无法知道当前参数能否恢复合理姿势；
- 没有活性/诱饵集富集测试，无法判断分数是否能区分已知活性与随机分子；
- Vina-GPU 的低 exhaustiveness 适合快速初筛，不适合把单个分数解释为强结合结论；
- 带电、强极性或化学上不合理的结构，可能利用评分函数的偏好得到虚高分；
- 生成器只看到打分函数，容易学会“讨好 Vina”，而不是寻找真正有药效的结构。

因此，当前 Vina 排名只能作为**同一经校准协议内部的搜索信号**，不能直接作为“活性排序”或“候选药物排序”。

### 2.3 建议同质化，系统把所有分子压成了同一种问题

如果下一轮建议反复出现“降低 hERG”“避免高脂溶性”“避开诱变片段”，通常有三层原因：

1. 报告建议由固定模板和关键词触发，天然缺少结构差异；
2. 排名采用单一固定加权总分，很多不同分子被压缩成一个分数；
3. 生成和选择压力过强，导致候选物本身越来越相似。

AutoGrow 当前后续代的有效种群较小、父体很少、精英保留强，同时多样性种子数为零。这种设置的优点是快速向当前最高分区域收敛，缺点是很容易在一个局部化学空间里反复改同一类片段。再加上排名没有骨架配额、Pareto 前沿或探索预算，系统会不断把“总分最好但结构相近”的分子送到下一轮。

换句话说，文案同质化只是表象；真正的根因是**数据、选择和决策都没有保留足够的差异性**。

### 2.4 用一个完整例子理解“当前流程”和“目标流程”的差异

假设候选分子 A 的信息如下：Vina 为 -9.4，LogP 为 4.3，hERG 为 `low_risk`，Ames 为 `low_risk`；姿势中可能存在一个氢键，但该姿势来自未校准的预测口袋。

**当前流程可能这样处理：**

1. 因为 Vina 很低，A 进入前列；
2. 报告文本中出现 hERG 和 Ames；
3. 关键词规则生成“降低 hERG、避开诱变片段”；
4. 下一轮继续从 A 附近生成类似分子；
5. 新分子继续依赖 Vina 排序；
6. 如果 Vina 进一步降到 -10，系统可能认为优化成功。

这条路径的问题是：hERG/Ames 实际是低风险，建议与证据矛盾；口袋未校准，Vina 改善未必有意义；继续围绕 A 生成，会放大同质化和评分函数偏差。

**目标流程应该这样处理：**

1. 先读取协议状态，发现口袋和 docking 未校准，因此把 Vina 标为探索性证据；
2. 正确解释 `low_risk`，不触发 hERG/Ames 优化任务；
3. 识别真正需要处理的是高 LogP 和对接不确定性；
4. LLM 提出假设：“A 的某个疏水芳环可能贡献占位，也推高 LogP”；
5. 设计三类分子：保守替换、极性替换和不改变该位置的对照；
6. Strategy Compiler 校验结构、价态、变换可执行性和预算；
7. 使用同一协议复评，并比较父子分子的 LogP、姿势相互作用和分数变化；
8. 如果更极性的替换改善 LogP 但姿势全部丢失，则假设被部分反驳；
9. 下一轮不再盲目追求更负 Vina，而是根据假设评价决定继续、换位点或先校准口袋。

这个例子说明：真正的智能不体现在报告更长，而体现在系统能否识别“当前最该解决的问题是什么”。

---

## 3. 当前系统已经具备的基础

优化不应该否定已有工作。项目已经有几项非常重要的基础能力：

- 有正式轮次、策略快照、执行计划和 artifact hash，具备可追溯性；
- 能区分部分计算证据、外部证据和 surrogate 结果；
- 已有分子、对接、ADMET、合成可行性、排名和报告等主要数据通路；
- 分子详情页有来源、证据和 pose 状态的基础展示；
- 数据模型中已经存在 `Assay`、`Bioactivity`、`ApprovalEvent`、`ScientificPolicy` 等未来闭环可复用的对象；
- 已经具备初排、自反驳、重排的雏形，说明系统知道“不能只看一个分数”。

因此，下一步不是推倒重来，而是把这些已有能力接成一个更严格的科学决策闭环。

---

## 4. 当前局限性、形成原因和修改方向

### 4.1 靶点身份、受体结构和口袋身份没有形成硬门禁

**当前表现**

系统可以检查项目是否有 target ID、受体、口袋和文件哈希，但没有强制证明“用户说的靶点”和“上传 PDB 中的蛋白”是同一个对象。结构文件、链、物种、UniProt ID、构建体范围、突变和口袋之间缺少完整的身份校验。预测口袋和准备好的受体存在时，流程就可以进入对接。

相关实现主要位于：`src/medagent/services/scientific_execution.py`、`src/medagent/services/strategy_validator.py`、`src/medagent/services/target_resource_packages.py`。

**为什么会这样**

系统早期把“文件可用”视为“科学对象正确”。这对工作流编排足够，但对药物研发不够。文件存在、格式正确、可以被 Vina 读取，只能说明工具能跑，不能说明研究对象正确。

**风险**

一旦靶点、构建体或口袋错了，后面所有生成、对接、筛选和 LLM 推理都会建立在错误前提上。分数再好也没有药理学意义。

**下一步怎么改**

建立 `TargetIdentityGate` 和 `DockingProtocolGate`：

1. 为每个项目保存规范化靶点信息：基因名、蛋白名、UniProt accession、物种、目标链、构建体残基范围、突变、结构来源；
2. 从受体文件提取序列或链注释，与 UniProt/PDB 元数据比对；
3. 让口袋对象明确记录来源：共晶配体、实验位点、文献位点或预测位点；
4. 若是预测口袋，界面必须显示“探索性口袋”，不能与共晶位点同等对待；
5. 对每个对接协议记录受体准备方式、质子化、盒子坐标、软件版本、参数和参考配体；
6. 任何身份信息不匹配时，正式轮次进入 `blocked`，而不是继续产生排名。

**为什么这样改**

这是最低成本、最高价值的错误预防。它不让模型变聪明，但能避免整个系统在错误靶点上非常高效地工作。

**验收标准**

- 把 METTL4 结构登记为 BRAF 时，正式对接必须被阻断并显示具体不一致字段；
- 每一次正式 docking run 都能追溯到唯一的 target identity、receptor hash 和 pocket definition；
- 预测口袋不能被显示为已验证结合位点。

### 4.2 没有对接校准，Vina/GNINA 分数缺少解释尺度

**当前表现**

数据模型有 `redock_rmsd` 的位置，但没有真正把重对接、RMSD、构象恢复和富集能力做成执行门。当前协议可在没有参考配体的情况下运行。

**为什么会这样**

对接工具已经接入，但“工具能运行”与“工具在这个靶点上可靠”被当成了同一件事。它们其实完全不同。

**下一步怎么改**

为每个靶点 - 结构 - 口袋建立 `DockingCalibration`：

- 输入共晶配体或可信参考配体；
- 在完全相同的受体、盒子、质子化和参数下重对接；
- 保存 RMSD、关键相互作用恢复、姿势可视化和失败原因；
- 在有公开活性数据时，增加 actives vs decoys 的 enrichment、ROC-AUC、EF1% 等指标；
- 为每种评分方法单独建立校准，不把 Vina 与 GNINA CNN 分数混合解释；
- 未通过最低校准要求时，结果标记为探索性，禁止进入“高置信候选”路径。

**为什么这样改**

校准会给分数一个上下文。它不能证明候选物有效，但能回答“这个协议在已知事实面前是否表现合理”。没有校准，-9.9 只是一个没有单位的漂亮数字。

**验收标准**

- 每个正式协议都能显示校准状态：通过、探索性、失败或不适用；
- 报告中不能把未校准 Vina 分数写成强活性证据；
- 排名会因校准状态降低或提高对接证据的权重。

### 4.3 当前是固定流水线，不是观察驱动的研究循环

**当前表现**

`round_orchestrator.py` 中的正式轮次顺序基本固定：生成、评估、初排、自反驳、重排、报告和下一轮。中途即使发现目标不一致、姿势不合理、所有候选同骨架或 ADMET 模型超出适用域，系统也缺少标准机制来改变动作。

**为什么会这样**

固定流水线容易开发、容易测试，也利于演示；但科学研究不是固定的。不同观察结果应该触发不同后续动作。

**下一步怎么改**

新增四个一等数据对象：

| 对象 | 含义 | 必填内容 |
| --- | --- | --- |
| `Hypothesis` | 可被数据支持或反驳的判断 | 主张、证据、适用范围、成功/失败条件 |
| `ExperimentProposal` | 为检验假设而设计的计算或实验 | 动作、对照、预算、预期观察、审批要求 |
| `Observation` | 一次工具运行或实验得到的结构化结果 | 来源、方法、条件、值、单位、不确定性、artifact |
| `HypothesisEvaluation` | 新观察对旧假设的影响 | 支持、反驳、不确定、理由和证据 ID |

示例：

> 假设：某个芳环上的疏水取代基主要贡献结合，但也推高 LogP；将其替换为含氮杂环可保留疏水占位并降低 LogP，且不破坏与残基 X 的相互作用。

这不是一句泛泛的“降低 LogP”。它必须包含父分子、原子映射、具体替换、要保留的相互作用、预期变化、反证条件和复评方法。

**为什么这样改**

有了假设对象，系统才知道某次生成不是“多造一些分子”，而是在检验一个明确主张。即使结果不好，也能成为下一轮的知识，而不是被总分掩盖。

### 4.4 LLM 目前主要写解释，不能可靠地控制科学动作

**当前表现**

策略 LLM、SAR LLM、对话 LLM 和 critique LLM 已经存在，但它们的输出多为策略文本、自由 JSON 或报告文字。策略中的性质约束大多只影响 MW、LogP、TPSA、HBD、HBA 等后处理筛选；hERG、Ames、反应性片段、关键相互作用等信息没有稳定映射到生成、过滤、排序和复评。

**为什么会这样**

自然语言非常适合表达药化直觉，但程序不能直接安全执行自然语言。项目目前缺少一个把语言判断翻译成受限、可验证动作的中间层。

**下一步怎么改：建立 Strategy Compiler**

把 LLM 的职责限定为提出结构化设计意图；再由确定性代码编译和拒绝不支持的内容。

LLM 可以输出：

```json
{
  "hypothesis_id": "H-012",
  "parent_molecule_id": "M-104",
  "transformation": {
    "mapped_atoms": [12, 13, 14],
    "replace": "phenyl",
    "with": "pyridyl"
  },
  "objectives": [
    {"endpoint": "logp", "direction": "decrease", "target_delta": -0.6},
    {"endpoint": "docking_interaction", "retain": "H-bond: residue-123"}
  ],
  "evidence_ids": ["EV-81", "EV-94"],
  "success_criteria": ["logp <= 3.0", "pose_interaction_retained"],
  "failure_criteria": ["docking_pose_invalid", "herg_risk == high_risk"],
  "uncertainty": "medium"
}
```

`StrategyCompiler` 负责：

- 验证引用的 evidence ID 是否存在且属于当前项目；
- 检查原子映射、SMARTS、价态、质子化和禁用结构；
- 判断 CReM、AutoGrow 或其他生成器是否真正支持该动作；
- 把可执行部分编译成生成约束、硬过滤器、排序目标和复评任务；
- 对不支持或证据不足的内容明确返回 `blocked` 或 `report_only`；
- 保存编译后的动作和版本，而不是只保存 LLM 的原话。

**为什么这样改**

这会让 LLM 真正参与研发设计，同时不会让它绕过化学规则、预算、审批或证据边界。LLM 的价值在于提出高质量、跨证据的假设；确定性系统的价值在于确保这些假设不会被错误执行。

### 4.5 LLM 自反驳不应通过自由文本直接改变排名

**当前表现**

`self_refutation.py` 会从模型返回文本中用正则提取 JSON，然后根据模型列出的风险数量或强度影响 `con_score`。自动路径和手动 critique 路径也不完全一致。

**为什么会这样**

系统希望避免“只看正面分数”，因此引入了反驳机制。但目前把“LLM 写了几条担忧”直接变成数值扣分，相当于让语言长度和表达风格影响排名。

**风险**

同一事实在一次回答中被拆成三条、另一次回答中被合成一条，排名就可能不同。模型也可能提出输入中不存在证据支持的专利、毒性或类比风险。

**下一步怎么改**

统一自动和手动 critique，使用严格 schema：

| 字段 | 说明 |
| --- | --- |
| `claim` | 明确的风险或反驳主张 |
| `evidence_ids` | 支撑主张的已存在证据 |
| `epistemic_status` | observed / predicted / inferred / unsupported |
| `severity` | 受限枚举，不允许任意数值 |
| `proposed_action` | 复算、过滤、实验或人工审阅 |
| `confidence` | 用于是否进入人工复核，不直接当分数 |

LLM 只能提出主张。规则引擎根据证据类型、端点阈值和校准状态决定是否形成真实 penalty、warning 或 review task。

**为什么这样改**

这样保留 LLM 的批判性，同时让排名建立在可复现规则上，而不是建立在某次语言生成的长度和措辞上。

### 4.6 父子谱系不精确，SAR 无法真正学习

**当前表现**

分子记录有父体概念，但生成物可能被关联到整组输入种子，而不是实际参与生成的具体父体。系统也没有系统保存“哪个原子被替换、替换前后端点变化多少、姿势相互作用如何变化”。

**为什么会这样**

早期目标是得到候选物，而不是建立可复用 SAR 知识库。生成器输出通常也不天然提供完整 transformation lineage，需要项目自己记录。

**下一步怎么改**

新增 `MolecularTransformation` 和 `EndpointDelta`：

- `MolecularTransformation`：parent ID、child ID、原子映射、反应/片段替换、生成器、参数、可信度；
- `EndpointDelta`：父子分子在 docking、GNINA、LogP、TPSA、hERG、Ames、合成性、实验活性等端点上的差值；
- `PoseInteractionDelta`：关键氢键、疏水占位、盐桥、clash 是否保留或损失；
- `MatchedMolecularPair`：可比较的局部变换集合。

之后 LLM 不再从一串 SMILES 猜 SAR，而是阅读“在同一骨架、同一变换、同一协议下发生了什么”。

**为什么这样改**

真正有价值的 SAR 不只是“带氮的分子好一些”，而是“在这个系列中，把位置 4 的苯环换成吡啶，实验活性基本保留，LogP 降低 0.7，但 hERG 预测改善；该结论对哪些类似骨架有效、对哪些无效”。这需要精确谱系和端点差值。

### 4.7 排名是单一总分，不能代表多目标决策

**当前表现**

当前候选排序主要将对接、ADMET、合成性、证据等压缩为固定加权总分。

**为什么会这样**

总分便于展示，也便于自动选 Top N；但药物发现不是单目标优化。一个分子可能对接略差但可合成性和安全性好得多，另一个分子可能需要保留为机制对照。

**下一步怎么改**

采用“硬门槛 + Pareto 前沿 + 多样性配额”的三层选择：

1. **硬门槛**：化学无效、严重反应性、高风险或协议失败的分子不能进入优先队列；
2. **Pareto 前沿**：不强行把 affinity、ADMET、合成性和不确定性压成一个数，而是保留各目标之间没有被完全支配的候选；
3. **多样性配额**：每个 Bemis-Murcko scaffold 或化学簇最多保留若干个；为新颖骨架、反例和不确定但信息价值高的分子预留席位。

排名页面应同时显示“为什么入选”：高结合证据、低风险、骨架代表性、探索价值或验证对照，而不是只显示总分。

**为什么这样改**

这能让系统保留真正值得研究的不同方向，避免全部资源押在一个可能是评分函数假阳性的局部最优点上。

### 4.8 AutoGrow 搜索设置会推动早熟收敛

**当前表现**

后续代候选数量较少，父体选择集中，精英保留强，`diversity_mols_to_seed_first_generation=0`，同时使用未校准的 Vina 信号。该配置会让少量高分结构不断繁殖。

**为什么会这样**

这是典型的“利用优先”设置：它假设当前分数是可靠方向，因此快速围绕最高分做局部优化。但在未校准 docking 和弱种子条件下，这个假设不成立。

**下一步怎么改**

- 将后续代划分为 exploitation 和 exploration 两个预算池；
- 为 exploration 保留多个不同骨架和不同物化性质区域；
- 使用骨架相似度阈值限制同类子代数量；
- 保留参考配体、已知活性物或可靠先导物作为锚点；
- 使用 `use_docked_source_compounds` 和 parent provenance，但只有在协议校准后才允许强依赖；
- 对异常电荷、反应性、不可解释价态和不合理质子化做生成前或生成后过滤；
- 不以 Vina 一项作为遗传适应度，至少使用校准后的 docking、化学有效性、ADMET 硬门槛和多样性共同决定选择。

**为什么这样改**

搜索的目标不是把一个打分函数压到最低，而是在有限预算内找到多个可解释、可复核、可继续优化的化学起点。

### 4.9 RAG 和外部文献目前不能证明某个主张成立

**当前表现**

项目能保存文档、chunk 和 evidence ID，这是很好的开始。但“检索到相关文本”与“文本支持当前结论”还没有被严格区分；部分路径只要存在 RAG 关联就提升置信度。

**下一步怎么改**

- 为每一条文献引用记录 `supports`、`contradicts`、`background_only` 或 `unverified`；
- 要求 LLM 为 claim 标出精确引用片段，而不是只给文档 ID；
- 将文献级别与计算级别分开：文献可支持靶点机制，不可自动证明新分子的活性；
- 对每条关键 claim 运行 entailment/人工复核队列；
- 排名只能因“经验证支持的具体 claim”得到加分，不能因“有文献”笼统加分。

### 4.10 审批、模型版本和 LLM 运行记录不完整

**当前表现**

系统中已有 `ApprovalEvent`，部分 StagePlan 也标记 `requires_approval`，但执行器未必真正查询与计划哈希、动作版本匹配的批准记录。LLM 也没有统一记录 prompt 模板版本、采样参数、工具调用、检索证据和 schema 版本。

**为什么会这样**

审批和审计对象已经设计出来，但还没有贯穿到所有执行入口。LLM 接入也来自多个历史模块，配置和日志格式不完全统一。

**下一步怎么改**

建立统一 `LLMGateway` 和 `ActionRegistry`：

- 每个 action 声明输入 schema、输出 schema、能力边界、成本、预算、所需证据、审批要求和 artifact；
- 每次 LLM 调用记录 model/provider revision、prompt hash、模板版本、temperature、token、延迟、成本、输入 evidence IDs、输出 schema version、验证结果；
- 未获批准的高成本或高影响 action 必须在执行层返回 `blocked`；
- 审批绑定 action version 和 plan hash，避免“批准了旧计划却执行新计划”。

这不是行政负担。它是未来解释“为什么系统当时提出这个建议、用了哪些证据、能否复现”的基础。

### 4.11 缺少实验反馈和科学 benchmark

**当前表现**

项目有 `Assay` 和 `Bioactivity` 基础模型，但尚未形成包含实验条件、单位、重复、误差、批次和 QC 的真实 observation 闭环。现有测试更多验证接口、schema 和 fallback，较少验证科学任务质量。

**下一步怎么改**

建立两类 benchmark：

1. **计算 benchmark**：冻结的 BRAF、EGFR 等已知任务，测量重对接 RMSD、active/decoy enrichment、已知 SAR 恢复、化学有效率和建议多样性；
2. **智能体 benchmark**：比较固定流水线与动态 planner，在相同预算下谁更能保留正确骨架、避免无效复评、引用真实证据、提出可执行建议。

对于实验数据，至少记录 assay protocol、endpoint、单位、检测下限、重复数、均值、方差、批次、对照和 QC 状态。没有这些信息的实验数值不能被当作与其他 assay 可直接比较的真值。

### 4.12 前端 Agent 还没有真正读取当前页面的科学上下文

**当前表现**

目前前端 Agent 在策略页面具备有限的修改能力，但在排名页、分子详情页等位置询问“为什么这个分子排第一”“A 和 B 有什么关键差异”时，仍可能返回固定提示或缺少当前页面证据的回答。

**为什么会这样**

聊天组件和科学数据视图之间缺少统一的 `PageContext`。界面知道用户正在看哪个分子，LLM 调用却未必拿到该分子的姿势、证据、排名分解、父子变换和校准状态。

**下一步怎么改**

每个可调用 Agent 的页面生成结构化上下文：

```json
{
  "page": "molecule_detail",
  "project_id": "P-01",
  "round_id": "R-03",
  "selected_molecule_ids": ["M-104", "M-118"],
  "visible_evidence_ids": ["EV-81", "EV-94"],
  "ranking_version": "rank-v4",
  "calibration_status": "exploratory"
}
```

后端根据这个上下文构建允许访问的 Observation Packet。LLM 回答中的每个关键结论都要引用当前页面可访问的 evidence ID。

排名页还应增加：分数分解、Pareto 状态、scaffold cluster、协议可信度、模型适用域和“入选原因”。分子详情页应展示父子变换和端点变化，而不仅是静态属性。

**验收标准**

- 在 A/B 对比时，回答必须引用 A 和 B 的真实不同证据；
- 当前页面没有姿势数据时，Agent 不得声称存在某个氢键；
- 未校准结果在 UI 和 Agent 回答中始终显示为探索性。

### 4.13 不确定性没有成为决策的一等数据

**当前表现**

系统主要展示预测值和风险标签，但较少展示模型适用域、预测方差、不同工具是否一致，以及数据缺失究竟表示“低风险”还是“没有证据”。

**为什么会这样**

单个数值最容易进入数据库和排名公式，而不确定性往往来自多个来源：模型本身、输入结构、质子化状态、受体构象、实验误差和不同软件之间的分歧。

**下一步怎么改**

为每个 Observation 增加：

- `value` 与 `unit`；
- `uncertainty` 或置信区间；
- `applicability_domain`；
- `method_version`；
- `replicate_count`；
- `quality_status`；
- `missing_reason`；
- `epistemic_level`，区分实验观察、计算预测和 Agent 推断。

排名和 planner 需要把不确定性当作一个独立维度。高分但高度不确定的分子可以进入“值得验证”队列，却不应自动进入“最有希望”队列。

### 4.14 缺少明确的停止条件，系统容易把“继续生成”当成默认答案

**当前表现**

当几代候选物结构越来越相似、分数没有实质改善或模型不断超出适用域时，系统仍可能自动生成下一轮建议和候选物。

**为什么会这样**

固定流水线天然有一个隐含目标：把当前轮跑完并进入下一轮。它没有明确表示“什么情况下继续计算已经不再产生信息”。

**下一步怎么改**

定义可配置的停止和转向条件，例如：

- 连续两轮 Pareto 前沿没有新增候选；
- scaffold 多样性低于阈值；
- Top 候选变化仅来自未校准 docking；
- 有效子代率低于阈值；
- 超过一定比例的 ADMET 预测处于域外；
- 所有关键假设均缺少可区分的验证动作；
- 预算已达到上限；
- 新候选相对父体没有达到最小有意义变化。

触发后，planner 的合法动作应包括：停止该分支、请求人工审阅、补做校准、导入更好的种子、换口袋假设或设计实验，而不是只有“继续生成”。

### 4.15 当前系统缺少明确的“不能回答”机制

**当前表现**

当证据缺失时，报告或 LLM 仍可能给出听起来完整的解释。比如没有真实 pose 时推断相互作用，没有实验数据时讨论活性，没有专利检索时讨论侵权风险。

**下一步怎么改**

把 `insufficient_evidence`、`out_of_scope`、`unsupported_by_tool` 和 `needs_human_review` 设为正式结果，而不是错误状态。

每类 claim 都应定义最低证据要求。例如：

| Claim | 最低证据要求 |
| --- | --- |
| “存在某个口袋相互作用” | 可追溯的三维 pose 和相互作用计算 |
| “预测 hERG 风险较高” | 指定模型、版本、适用域和预测结果 |
| “可能提高实验活性” | 至少是明确标注为推断的 SAR 假设，不能写成事实 |
| “存在专利风险” | 专利检索结果和 claim mapping，普通 RAG 不足 |
| “适合进入实验” | 科学门禁、预算、合成和人工审批均通过 |

一个成熟智能体的能力不仅是会回答，也包括知道什么时候不该回答。

---

## 5. 建议的目标架构

建议将未来系统组织成下面的受控闭环：

```text
项目与靶点身份门
        ↓
结构化 Observation Packet
        ↓
LLM 提出可证伪假设与候选动作
        ↓
Strategy Compiler（化学、证据、预算、审批校验）
        ↓
Action Registry 执行生成/对接/复评/实验准备
        ↓
结构化 Observation（含条件、来源、误差、artifact）
        ↓
规则引擎 + LLM 评价假设
        ↓
Pareto/多样性选择与受控重规划
```

其中最关键的原则是：

| LLM 应负责 | 确定性代码必须负责 |
| --- | --- |
| 跨证据总结、发现矛盾、提出可证伪假设 | 化学合法性、结构解析、价态和质子化校验 |
| 提出结构变换和对照设计 | action 是否可执行、工具参数编译、预算控制 |
| 解释为什么某方向值得验证 | 数值计算、分数阈值、硬门槛和最终状态迁移 |
| 根据 observation 建议下一步 | evidence ID 存在性、审批检查、版本追踪 |
| 生成面向人的报告 | 排名规则、artifact 完整性和审计日志 |

这不是限制 LLM，而是把它放在最有价值的位置：负责科研推理，而不是负责未经验证的数值裁决。

### 5.1 目标架构中的八个核心组件

#### A. Scientific Object Registry

负责定义“正在研究什么”。它管理靶点、蛋白结构、链、口袋、参考配体、assay 和所有版本关系。

它解决的问题是：项目名、数据库 ID 和实际文件不能各说各话。

#### B. Observation Store

负责保存工具和实验产生的事实。每条 Observation 都带方法、条件、单位、版本、不确定性、证据等级和 artifact。

它解决的问题是：同一个 -9.0 到底来自哪个受体、哪个盒子、哪个软件版本，能否与另一个 -9.0 比较。

#### C. Hypothesis Workspace

负责保存 Agent 或研究人员提出的假设、支持证据、反面证据、成功条件和失败条件。

它解决的问题是：每一轮为什么要做这些分子，以及失败后学到了什么。

#### D. Strategy Compiler

负责把自然语言研究意图转成有限的机器动作，例如“在指定位置做片段替换”“执行 GNINA 复评”“计算某组 ADMET 端点”。

它解决的问题是：LLM 建议听起来合理，但生成器和工具究竟能不能执行。

#### E. Action Registry

负责列出系统允许执行的动作。每个动作声明输入、输出、预算、超时、重试、证据上限、审批要求和产生的 artifact。

它解决的问题是：LLM 不能任意执行命令，只能从经过工程和科学审核的动作集合中选择。

#### F. Deterministic Scientific Gates

负责靶点身份、化学合法性、对接校准、模型适用域、审批、预算和硬风险检查。

它解决的问题是：有些判断必须可重复、可测试，不能交给语言模型临场发挥。

#### G. Planner and Hypothesis Evaluator

Planner 阅读当前研究状态，提出下一组动作；Evaluator 在结果回来后判断假设得到支持、反驳还是仍不确定。

它解决的问题是：流程需要根据 observation 变化，而不是永远按同样顺序跑到底。

#### H. Human Review Workbench

负责向研究人员展示原始证据、Agent 推理、编译结果、冲突、成本和待审批动作。

它解决的问题是：人类审批不应只有“同意/拒绝”按钮，而要能看懂系统为什么提出这个动作。

### 5.2 一条建议从产生到执行的完整生命周期

建议状态可以设计为：

```text
drafted
  → schema_validated
  → evidence_validated
  → chemically_validated
  → compiled
  → awaiting_approval（如需要）
  → scheduled
  → running
  → observed
  → hypothesis_evaluated
```

任何阶段都可以进入 `rejected`、`blocked`、`failed` 或 `needs_review`，且必须记录原因。

这样可以清楚区分：LLM 提过一个想法、系统认为它可执行、用户批准了它、工具真的执行了它，以及结果是否支持原假设。这些不是同一件事。

### 5.3 为什么不建议让 LLM 直接操作任意工具

任意工具调用看起来更“自主”，实际会带来三个问题：不可复现、难以控制成本、难以保证科学语义一致。

例如 LLM 临时决定改变 docking box，可能得到更好分数，但新分数已不能与上一轮比较。Action Registry 可以允许“新建口袋假设”，却必须把它作为新协议，而不是悄悄覆盖旧参数。

---

## 6. 如何让 LLM 真正参与分子开发，而不是生成模板文案

### 6.1 给 LLM 的输入必须是结构化观察包

不要只给它 Top N 的 SMILES 和总分。一个 `ObservationPacket` 至少应包含：

- 靶点身份、结构和口袋的校准状态；
- 每个候选的精确 parent-child lineage；
- 结构描述、scaffold cluster 和关键官能团；
- docking 分数、姿势质量、关键相互作用和协议可信度；
- ADMET 原始端点、模型适用域和风险枚举；
- 合成可行性、反应性和化学有效性；
- 历史变换及每个 endpoint delta；
- 已验证和未验证的文献/实验 evidence；
- 当前轮次的目标、预算、禁用操作和待回答问题。

这样 LLM 看到的不是一堆零散分数，而是一个有上下文的研究状态。

### 6.2 要求 LLM 输出“可证伪设计”，而不是“优化建议”

不合格输出：

> 建议降低 hERG 风险，避免过度脂溶。

合格输出：

> 对 parent M-104，在原子 12-14 对应的苯环位置尝试替换为 3-吡啶基。依据：该系列中该区域主要提供疏水占位，而分子 LogP 为 4.1 且存在可疑碱性中心；预期 LogP 降低至少 0.5，保留与残基 123 的氢键。失败条件：姿势丢失该氢键、hERG 升至 high_risk、或合成路线复杂度超过阈值。需要以同一 docking protocol 和 hERG 模型复评，并保留未替换 parent 作为对照。

前者是通用百科建议；后者可以被生成器、过滤器、对接工具和人工化学家逐项检查。

### 6.3 LLM 输出必须经过两次验证

第一层是 schema 验证：字段齐全、枚举合法、ID 存在、数值在范围内。

第二层是语义验证：证据是否真的支持 claim、结构变换是否可执行、端点是否处于模型适用域、动作是否被批准、目标之间是否冲突。

任何一个验证失败，都应保留 LLM 原始提议供审计，但状态必须是 `rejected`、`needs_review` 或 `report_only`，不能悄悄落入下一轮。

### 6.4 LLM 应评价假设，而不是直接改总分

每轮结束后，LLM 可回答：

- 哪个假设得到了支持？
- 哪个假设被反驳？
- 哪些结果因 docking 未校准或 ADMET 超出适用域而无法解释？
- 哪个骨架值得继续，哪个方向应该停止？
- 下一轮需要补哪一种证据，而不是再生成更多相似分子？

但它的结论要进入 `HypothesisEvaluation`，而非直接对 `final_score` 加减分。最终排序仍由可版本化的规则、Pareto 选择和人工审批共同控制。

### 6.5 LLM 需要按角色分工，而不是多个模块各写一套结论

建议保留有限的逻辑角色，并让它们共享同一套证据对象和 schema：

| 角色 | 主要任务 | 不允许做的事 |
| --- | --- | --- |
| Evidence Analyst | 汇总证据、识别冲突和缺失 | 不生成分子、不改分 |
| Medicinal Chemistry Planner | 提出 SAR 假设、变换和对照 | 不把预测写成实验事实 |
| Critic | 寻找反例、域外问题和替代解释 | 不按风险条数直接扣分 |
| Experiment Planner | 选择验证动作、成功条件和预算 | 不绕过 Action Registry |
| Hypothesis Evaluator | 根据新 observation 评价旧假设 | 不修改原始 observation |
| Report Writer | 面向人解释已验证状态 | 不引入没有 evidence ID 的新结论 |

这些角色可以由同一个模型在不同受限 prompt 下完成，也可以由不同模型完成。关键不在模型数量，而在输入、输出和权限边界统一。

### 6.6 提示词应该围绕证据和反证设计

一个合格的 planner prompt 不应只写“你是一名资深药物化学家，请给出建议”。它还应明确：

- 只能引用输入中的 evidence ID；
- 必须区分 observed、predicted 和 inferred；
- 每个假设必须给出至少一个失败条件；
- 必须设计 parent/control，不能只给最优候选；
- 不能把不同 docking protocol 的分数直接比较；
- 遇到未校准协议或域外预测时，优先提出补证据动作；
- 输出必须匹配指定 JSON schema；
- 不支持的判断必须返回 `insufficient_evidence`。

这能降低幻觉，但不能取代后端验证。提示词是第一道软约束，schema、编译器和执行门才是硬约束。

### 6.7 LLM 需要看到失败样本，而不只是 Top 分子

如果只把 Top 20 输入 LLM，它会看到一个被排名系统筛选过的偏置样本，很难判断哪些结构变化其实失败了。

Observation Packet 应包含：

- 同系列成功和失败的 parent-child 对；
- 被硬门槛淘汰但有信息价值的分子；
- 相同变换在不同骨架上的正反结果；
- docking 好但 ADMET 差的冲突样本；
- docking 差但实验活性好的校准反例；
- 模型域外或计算失败样本。

研究推理的价值往往来自比较“为什么这个改动在 A 上有效、在 B 上无效”，而不是只总结排名最高的共同特征。

### 6.8 应采用双层记忆，而不是把全部历史塞进上下文

第一层是结构化长期记忆：项目事实、假设、变换、Observation、证据和评价，保存在数据库中。

第二层是当前任务上下文：根据当前问题从长期记忆中检索最相关、可引用的证据，生成大小受控的 Observation Packet。

这样既避免上下文无限增长，也避免 LLM 根据旧报告文字反复转述。长期记忆存事实和关系，当前上下文只存这次决策真正需要的信息。

---

## 7. 解决“下一轮建议同质化”的具体设计

### 7.1 先修复语义，再生成建议

所有风险端点使用统一枚举，例如：

```text
not_available | out_of_domain | low_risk | medium_risk | high_risk | inconclusive
```

报告层不得通过字符串包含关系判断风险。它必须读取结构化端点和阈值。`low_risk` 可以成为“当前未见明显警示”的正面或中性证据，但不能进入风险行动队列。

### 7.2 建议必须由“触发原因”驱动

每个建议对象应保存：

- `trigger_type`：高风险、证据缺失、模型域外、姿势冲突、谱系机会或探索需要；
- `trigger_evidence_ids`：具体触发证据；
- `affected_substructure`：涉及的原子、SMARTS 或片段；
- `recommended_transformation`：可执行替换或明确的人工研究任务；
- `expected_tradeoff`：预计改善和可能损失；
- `validation_plan`：应重跑的计算或实验；
- `novelty_key`：用于去重，避免同一建议重复出现。

当没有分子特异证据时，系统应显示“未形成可执行建议”，而不是硬生成一句泛化建议。

### 7.3 排名和展示都要保留多样性

- 每个 scaffold cluster 至少保留一个代表物，不让前三名都来自同一骨架；
- 每轮固定保留一部分 exploration 候选，即使它们不是总分最高；
- 选择至少一个反例或对照分子，用于判断局部变换是否真的有效；
- 报告按“系列”展示共同规律，再按“分子”展示特异变化；
- 对重复建议进行 cluster-level 汇总，不要在十个相似分子下重复十次同一句话。

### 7.4 三个分子不应该得到同一句建议

下面是目标报告应呈现的差异化程度：

| 分子 | 主要证据 | 不应给出的模板建议 | 应给出的下一步 |
| --- | --- | --- | --- |
| A | hERG/Ames 低风险，LogP 高，姿势可信度低 | “降低 hERG、避免诱变” | 先校准/复核姿势；围绕高 LogP 位点设计保守极性替换 |
| B | docking 中等，hERG 高风险，存在强碱性中心 | “继续提高结合分数” | 以降低碱性/pKa 为主，保留关键氢键；设置 hERG 硬门槛 |
| C | docking 较好，性质均衡，但与 A 同骨架且高度相似 | “综合表现良好，继续优化” | 作为该骨架代表物保留；将生成预算转移到新骨架和对照 |

注意，C 可能没有明显风险，但仍不代表应该从 C 周围再生成 50 个类似物。它的下一步价值可能是“作为代表物停止局部扩张”。

### 7.5 建议生成的确定性前置流程

建议在调用 LLM 前先完成以下计算：

1. 标准化风险枚举和缺失原因；
2. 检查所有端点的模型适用域；
3. 计算 scaffold cluster 和候选间相似度；
4. 计算 parent-child endpoint delta；
5. 标记当前协议是否校准；
6. 提取姿势相互作用和 clash；
7. 识别互相冲突的证据；
8. 生成每个分子的 `decision_gaps`。

LLM 的任务是解释这些结构化差异并设计验证，不是替代上述计算。

### 7.6 用信息价值分配下一轮预算

下一轮候选不应全部围绕最高分分子。可以把预算分成：

| 预算池 | 建议比例 | 用途 |
| --- | --- | --- |
| Exploitation | 40% | 围绕有校准证据的先导做局部优化 |
| Exploration | 30% | 保留不同骨架和未探索物化区域 |
| Hypothesis tests | 20% | 设计能区分两种解释的 parent/control 对 |
| Calibration/controls | 10% | 参考配体、阴性对照和协议复核 |

比例应可配置，且根据项目阶段变化。早期命中发现更重视 exploration；进入 lead optimization 后可以增加 exploitation，但不能把探索和对照降到零。

---

## 8. 分阶段实施路线图

以下按依赖关系排序，而不是按“看起来最酷”的功能排序。

### M0：科学可信性和安全边界

**目标**：防止系统在错误靶点、未校准协议或未批准动作上给出过度自信的结论。

**工作项**

1. 统一 hERG、Ames、ADMET、自反驳等风险枚举和阈值；
2. 将报告建议改为读取结构化端点，不再从文本关键词反推风险；
3. 建立 TargetIdentityGate；
4. 建立 DockingCalibration 和共晶配体重对接流程；
5. 让 `requires_approval` 在执行器中真正阻断动作；
6. 合并自动/手动 critique，禁止自由文本直接修改分数；
7. 明确报告中的证据等级：计算预测、文献支持、实验观察、Agent 推断。

**完成标志**

- “low_risk 却建议降低风险”类矛盾有回归测试；
- 靶点或链不匹配时正式轮次被阻断；
- 未校准 docking 只能产生探索性结果；
- 未审批的 GNINA/高成本动作无法执行；
- LLM 不能仅凭多写几条风险就改变最终排名。

### M1：把 LLM 接入真实的研究设计闭环

**目标**：使 LLM 从报告生成器升级为受控的假设和实验设计助手。

**工作项**

1. 新增 `Hypothesis`、`ExperimentProposal`、`Observation`、`HypothesisEvaluation`；
2. 新增 `MolecularTransformation`、`EndpointDelta`、`PoseInteractionDelta`；
3. 建立 `ObservationPacket`；
4. 实现 `StrategyCompiler`；
5. 建立 `ActionRegistry`，使每个工具动作有能力声明、schema、预算和审批；
6. 建立统一 `LLMGateway` 和完整 trace。

**完成标志**

- 每个进入下一轮的分子都能回答：来自谁、改了什么、为了检验什么假设、用了哪些证据；
- 每条 LLM 建议都能被编译为 action、被拒绝，或被标记为仅供报告；
- 任意一轮可以重放其策略输入、模型版本、证据和编译结果。

### M2：多目标选择、SAR 学习和动态重规划

**目标**：解决同质化，避免单一评分函数主导搜索。

**工作项**

1. 实现 scaffold clustering、骨架配额和 novelty budget；
2. 用 Pareto 前沿替代单一总分的唯一决策权；
3. 为 AutoGrow/CReM 设置 exploitation 与 exploration 预算；
4. 建立 parent-child MMP 和 endpoint delta 分析；
5. 让 planner 根据停滞、有效子代率、证据冲突、模型域外和多样性缺口选择下一动作；
6. 将 SAR Agent 接入正式编排，但仅通过 StrategyCompiler 影响执行。

**完成标志**

- Top 候选不再被单一 scaffold 垄断；
- 每轮包含代表性先导、探索性骨架和验证对照；
- 下一轮建议能够指向具体结构差异，而不是重复 hERG/Ames 模板；
- 系统能在“对接无校准”“生成有效率过低”等观察出现时自动建议补证据或停止该路径。

### M3：实验反馈、基准和受控自治

**目标**：证明系统的建议比固定流水线更可靠，并让真实实验结果进入学习闭环。

**工作项**

1. 建立 assay work order 和实验数据导入规范；
2. 保存单位、重复、误差、批次、对照和 QC；
3. 建立 BRAF/EGFR 等冻结 benchmark；
4. 增加动态 planner 与固定流程的消融实验；
5. 建立人工复核工作台，展示假设、证据、动作、风险和批准状态；
6. 对模型、prompt、工具版本和策略规则做发布管理。

**完成标志**

- 系统可区分计算预测和实验 observation，并据实验结果更新假设；
- 在冻结 benchmark 上能报告 docking 校准、富集、SAR 恢复、建议多样性和证据准确率；
- 可以量化地回答“开启 LLM 后是否比固定规则更好”，而不是只展示更长的报告。

### 8.1 推荐的首批实施顺序

为了避免一次改动过大，建议把第一阶段拆成小而可验证的提交或 PR。

**批次 A：统一语义，不改变主流程**

1. 定义统一风险枚举和 parser；
2. 为 hERG、Ames、ADMET、自反驳补充语义测试；
3. narrative 只消费结构化风险对象；
4. UI 区分低风险、无数据、域外和高风险。

这一批解决最直接的自相矛盾，风险较低，也为后续 schema 统一打基础。

**批次 B：让科学门禁真正阻断**

1. 实现 target identity snapshot；
2. 将 approval lookup 接入执行器；
3. 为 docking protocol 增加 calibration status；
4. 未通过 gate 的 round 返回结构化 blocked reason。

这一批会改变正式执行行为，需要 API、后端和前端一起验收。

**批次 C：统一 LLM critique**

1. 定义严格 critique schema；
2. 自动和手动 critique 共用同一服务；
3. evidence ID validator 拦截无依据 claim；
4. 移除“按 LLM 风险条数扣分”；
5. 将有效 critique 转成 flag 或 evaluation task。

这一批首先降低 LLM 对排名的不可复现影响。

**批次 D：建立最小假设闭环**

先不要一次实现全部自治。选择一个简单场景，例如“降低 LogP 且保留 docking interaction”，打通：

```text
parent → transformation proposal → compile → generate
       → reassess → endpoint delta → hypothesis evaluation
```

只要这条 tracer bullet 可追溯、可复现、可被反驳，后续 hERG、Ames、选择性和实验任务都可以沿同一模式扩展。

### 8.2 依赖关系

实施顺序不能随意交换：

```text
统一语义
  ├─→ narrative 可信
  └─→ Observation schema
          ├─→ Strategy Compiler
          ├─→ Hypothesis Evaluation
          └─→ Pareto / SAR delta

Target / Protocol Gate
  └─→ docking calibration confidence
          └─→ ranking 和 planner 才能正确使用 docking

Action Registry + Approval
  └─→ 动态 planner 才能安全上线
```

如果在 Observation schema、Action Registry 和科学门禁之前上线动态 planner，它只会自动化现有的不一致。

---

## 9. 模块级改造清单

这一节把前面的架构建议映射到代码。文件名是建议方向，最终拆分应结合现有依赖和迁移成本。

### 9.1 数据模型层

主要位置：`src/medagent/db/models.py` 和 `migrations/`。

建议新增或扩展：

| 对象 | 关键字段 | 用途 |
| --- | --- | --- |
| `TargetIdentity` | UniProt、物种、链、序列哈希、构建体、突变 | 证明研究对象一致 |
| `DockingProtocol` | receptor/pocket hash、软件版本、参数、质子化 | 定义哪些分数可比较 |
| `DockingCalibration` | reference ligand、RMSD、interaction recovery、状态 | 给 docking 证据定级 |
| `Hypothesis` | claim、scope、evidence、success/failure criteria | 保存可证伪科学判断 |
| `ExperimentProposal` | action、control、budget、approval、expected observation | 保存验证设计 |
| `Observation` | method、condition、value、unit、uncertainty、artifact | 统一计算和实验结果 |
| `HypothesisEvaluation` | supported/refuted/inconclusive、evidence、reason | 从结果中学习 |
| `MolecularTransformation` | parent、child、atom map、transformation | 建立精确分子谱系 |
| `EndpointDelta` | endpoint、parent value、child value、delta、comparability | 建立 SAR 变化记录 |
| `ActionDefinition` | schema、capability、approval、cost、version | 约束可执行动作 |
| `LLMTrace` | model、prompt hash、evidence IDs、schema、tokens、cost | 复现 LLM 推理路径 |

数据库约束也很重要。例如 Observation 不应只存一个 `value`；如果没有 `method_version` 和 `condition_hash`，系统无法判断两个值是否可比较。

### 9.2 靶点与协议门禁

建议新增：

- `services/target_identity.py`：解析受体链和序列，执行 target identity 检查；
- `services/docking_calibration.py`：重对接、RMSD、相互作用恢复和富集评估；
- `services/scientific_gates.py`：汇总 target、protocol、chemistry、approval 和 budget gate。

修改 `scientific_execution.py`：

- 每个 StagePlan 保存 `protocol_id` 和 `gate_snapshot_hash`；
- 执行前重新验证硬门，而不是只相信计划生成时的状态；
- `requires_approval` 必须查询有效 ApprovalEvent；
- 结果必须关联实际使用的软件和 artifact hash。

### 9.3 LLM 统一入口

建议新增 `services/llm_gateway.py`，逐步替代各 Agent 自己拼 prompt、请求模型和解析 JSON 的方式。

统一入口负责：

1. 选择模型和 provider；
2. 加载版本化 prompt；
3. 注入允许访问的 evidence；
4. 请求结构化输出；
5. 执行 schema 验证；
6. 保存完整 trace；
7. 对超时、限流和解析失败执行统一 fallback；
8. 明确返回 `llm`、`deterministic_fallback` 或 `human_authored` 来源。

这样可以解决 `qwen-max`、`qwen-plus` 和配置模型散落在不同模块的问题，也能让测试针对统一边界编写。

### 9.4 Strategy Compiler

建议新增 `services/strategy_compiler.py`。

编译器应把每个策略字段分类为：

| 类型 | 含义 | 示例 |
| --- | --- | --- |
| `generation_objective` | 真正影响生成 | 指定位置替换、保留 scaffold |
| `hard_filter` | 不满足即淘汰 | 高反应性、非法价态、high-risk hERG |
| `ranking_objective` | 进入 Pareto 或评分 | 降低 LogP、保留关键相互作用 |
| `evaluation_task` | 生成后必须复评 | GNINA、pose check、特定 ADMET |
| `report_only` | 只能提示，不能执行 | 证据不足的机制猜测 |
| `unsupported` | 当前工具链不支持 | 需要自由能计算但未注册该 action |

如果一个 LLM 字段没有 consumer，系统不得假装策略已经生效。它必须在 UI 中显示“仅记录，未影响本轮执行”或“当前工具不支持”。

### 9.5 编排器改造

`round_orchestrator.py` 不应一次性硬编码完整路线，而应执行有限状态机：

```text
prepare → validate → propose → compile → approve → execute
        → observe → evaluate → select → replan/stop
```

这不是让 LLM 任意跳转。每个状态只允许有限动作，转移由确定性条件控制；LLM 只能在允许的候选动作中说明优先级和理由。

例如：

- 校准失败后，只允许“调整协议、换结构、人工审阅或停止”，不能进入正式排名；
- scaffold 同质化后，允许增加 exploration 配额或停止该系列扩张；
- 发现高 hERG 风险后，允许提出针对性结构变换和复评，不允许直接声称风险已解决。

### 9.6 排名和候选选择

修改 `candidate_ranking.py`：

- 保留原始端点和计算过程，不只保存 final score；
- 增加 calibration-aware confidence；
- 增加 Pareto front 和支配关系；
- 增加 scaffold cluster、novelty 和 information value；
- 将 LLM critique 从直接 penalty 改为经过验证的 flag/action；
- 区分“推进候选”“探索候选”“对照候选”和“停止候选”。

固定总分仍可作为排序视图之一，但不再拥有唯一决策权。

### 9.7 AutoGrow 和生成适配器

修改 `autogrow4_adapter.py` 及其他生成适配器：

- 保存真实 parent provenance 和 transformation；
- 接收编译后的结构约束，而不是自然语言；
- 支持 scaffold quota 和 diversity seeds；
- 分离 exploration/exploitation 子群；
- 报告每代有效率、去重率、scaffold 数和早熟收敛指标；
- 生成前后都执行结构标准化、价态、异常电荷和反应性检查；
- 当工具不支持原子级变换时，明确返回 unsupported，不要近似执行后不说明。

### 9.8 SAR 和 narrative

修改 `agents/sar.py`、`services/sar_bridge.py` 和 `services/narrative.py`：

- SAR 输入改为 transformation + endpoint delta + pose delta；
- 移除从自由文本正则猜 SMARTS 的主路径；
- narrative 从结构化 `DecisionExplanation` 渲染，不再通过风险文本反向触发建议；
- 相同 scaffold 的共同结论在系列级汇总；
- 分子级只展示真正不同的触发证据、结构位点和验证动作；
- 如果没有足够证据，输出“暂无分子特异性建议”。

### 9.9 前端改造

主要位置：`apps/web/src/components/AgentPanel.tsx`、`RankingPage.tsx`、`StrategyPage.tsx`、`MoleculeDetailPage.tsx` 和 `RoundReportPage.tsx`。

建议新增界面元素：

- target identity 和 docking calibration 状态条；
- LLM / deterministic fallback / human 来源标记；
- claim 级 evidence badge；
- 分数分解、Pareto 状态和 scaffold cluster；
- parent-child transformation 对比；
- 假设、反证条件和评价状态；
- action 编译结果、成本和审批状态；
- “为什么没有建议”或“为什么停止该方向”的明确解释。

用户需要看到的不只是 Agent 的最终一句话，而是这句话建立在哪些事实之上、哪些部分仍是推断。

### 9.10 API 建议

可以逐步增加以下资源式接口：

```text
GET  /projects/{id}/scientific-state
GET  /rounds/{id}/observation-packet
POST /rounds/{id}/hypotheses
POST /hypotheses/{id}/experiment-proposals
POST /experiment-proposals/{id}/compile
POST /compiled-actions/{id}/approve
POST /compiled-actions/{id}/execute
GET  /hypotheses/{id}/evaluations
GET  /molecules/{id}/transformations
GET  /rounds/{id}/pareto-front
```

每个写接口都应有幂等键、版本字段和审计主体。关键状态变化不允许仅靠前端文案表示。

---

## 10. 建议的验收指标

不要只以“模型调用成功率”或“生成分子数”衡量成功。建议同时追踪以下指标：

| 维度 | 指标 |
| --- | --- |
| 靶点正确性 | target/structure/pocket identity gate 拦截率与误拦截率 |
| 对接可信度 | 重对接 RMSD、关键相互作用恢复、EF1%、ROC-AUC |
| 化学质量 | valid molecule rate、异常电荷/反应性过滤率、合成可行率 |
| 多样性 | scaffold 数、Top N 的最大单骨架占比、平均 Tanimoto 距离 |
| SAR 学习 | 可解析 parent-child 比例、MMP 覆盖率、endpoint delta 完整率 |
| LLM 质量 | schema 通过率、证据引用准确率、不可执行提议率、人工接受率 |
| 决策质量 | Pareto 候选保留率、反例/对照覆盖率、重复建议率 |
| 可复现性 | action 重放成功率、prompt/model/tool trace 完整率 |
| 实验价值 | 建议进入实验后的命中率、假设支持/反驳比例、每个有效线索的计算成本 |

对 LLM 特别重要的不是“回答是否流畅”，而是：它提出的假设是否有证据、是否可执行、是否经得起结果反驳，以及是否比固定模板带来更好的下一步选择。

### 10.1 必须覆盖的端到端验收场景

**场景一：错误靶点**

项目声明 BRAF，上传 METTL4 结构。预期结果是 identity gate 阻断正式对接，显示序列/UniProt 不匹配，不生成活性排名。

**场景二：低风险语义**

hERG 和 Ames 都为 `low_risk`。预期结果是两者不会进入风险行动队列，报告可说明当前未见明显警示，但保留模型适用域提示。

**场景三：未校准 docking**

候选 Vina 为 -10.2，但没有参考配体校准。预期结果是分数只作为探索性证据，不允许报告“高亲和力候选”。

**场景四：LLM 幻觉证据**

LLM 引用不存在的 evidence ID 或声称存在未计算的氢键。预期结果是 schema/evidence validator 拒绝该 claim，不能进入报告事实层或排名。

**场景五：同质化**

Top 20 中 18 个属于同一 scaffold。预期结果是候选选择应用骨架配额，并为 exploration 和对照保留预算。

**场景六：不可执行建议**

LLM 提出当前生成器不支持的原子级变换。预期结果是 Strategy Compiler 返回 `unsupported`，UI 清楚说明原因，不生成一个近似结构冒充执行成功。

**场景七：审批门**

GNINA action 标记需要审批，但没有匹配 plan hash 的 ApprovalEvent。预期结果是执行器返回 `blocked`，即使用户直接调用 API 也不能绕过。

**场景八：假设被反驳**

目标变换改善 LogP，但所有子代都丢失关键姿势且实验活性下降。预期结果是 HypothesisEvaluation 标为 refuted/partially_refuted，planner 不继续重复该变换。

**场景九：数据不可比较**

两个 docking 分数来自不同 receptor 或 box。预期结果是 comparability check 阻止直接计算 delta，报告明确说明协议不同。

**场景十：没有足够证据**

分子没有 pose、没有实验数据且 ADMET 处于域外。预期结果是 Agent 返回 `insufficient_evidence` 和建议补充的证据，而不是生成确定性 SAR 结论。

---

## 11. 当前不应该优先做的事

在完成 M0 和 M1 前，不建议优先投入以下方向：

- 单纯增加更多分子生成模型；
- 单纯把 AutoGrow 代数从 10 增加到 20 或更高；
- 单纯提高 Vina 计算量并把更负分数当作成功；
- 让 LLM 自由调用任意工具或直接改排名；
- 在没有校准和 benchmark 前宣传系统能自主发现候选药物；
- 只优化报告页面视觉效果，而不修复其证据和决策来源。

这些工作不是永远不做，而是应该排在“对象正确、证据可信、动作受控、能从结果学习”之后。否则系统会更快地产生更多看似合理但难以验证的结论。

---

## 12. 最终定位和下一步决策建议

短期内，建议把产品定位为：

> 面向药物化学与计算化学团队的、可审计的候选设计与证据整合平台。系统可自动执行受控计算流程、提出需要验证的结构化假设，并由人类研究者审批关键动作和解释关键结论。

这个定位既不会贬低已有成果，也不会超出当前证据能力。真正成熟的药物开发智能体不应以“能生成多少分子”定义，而应以四件事定义：

1. 它是否知道自己研究的对象是否正确；
2. 它是否能把建议变成可执行、可审计、可反驳的动作；
3. 它是否能从失败和成功中积累 SAR，而不是每轮重新猜；
4. 它是否能在不确定时承认不确定，并请求校准、更多数据或人工审批。

如果先完成 M0 和 M1，项目就会从“自动跑工具并写报告”跨到“LLM 受控参与科研决策”。完成 M2 后，才能较有把握地解决下一轮建议和候选结构的同质化。完成 M3 后，才有资格用 benchmark 和真实实验反馈评估它是否真正提高了药物发现效率。

---

## 附录：当前审查涉及的主要模块

- 正式轮次编排：`src/medagent/pipeline/round_orchestrator.py`
- 科学执行与 stage 计划：`src/medagent/services/scientific_execution.py`
- 靶点/策略验证：`src/medagent/services/strategy_validator.py`
- 轮次策略 LLM：`src/medagent/agents/round_strategy.py`
- 自反驳逻辑：`src/medagent/services/self_refutation.py`
- 候选评估与排名：`src/medagent/services/candidate_assessment.py`、`src/medagent/services/candidate_ranking.py`
- AutoGrow 适配器：`src/medagent/services/autogrow4_adapter.py`
- 叙事报告与下一轮建议：`src/medagent/services/narrative.py`
- SAR 与自然语言桥接：`src/medagent/agents/sar.py`、`src/medagent/services/sar_bridge.py`
- 数据模型：`src/medagent/db/models.py`
