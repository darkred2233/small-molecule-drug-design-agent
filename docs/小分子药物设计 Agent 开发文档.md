# 小分子药物设计 Agent 开发文档

版本：v2.2  
日期：2026-07-07  
范围：只开发智能体系统，不包含人工药化审核、实验室验证、实验数据闭环。  

## 1. 一句话目标

这个系统要做的事是：

给定一个靶点、结合口袋、1-3 个已知活性分子和设计约束，智能体自动完成资料检索、RAG 建库、候选分子生成、规则过滤、SAR 分析、docking 分析、ADMET 预测、合成可及性评估、自我反驳和最终排序，输出 20-50 个“最值得继续推进”的候选分子。

同时，系统必须支持自然语言对话：

- 用户可以用自然语言指定优化方向，例如“降低 hERG 风险，但尽量保留活性”“优先提高溶解度”“保留母核，只改 R6 位”。
- Agent 可以基于当前分析结果给出指导和建议，例如“这一轮主要失败在 cLogP 偏高，下一轮建议增加极性取代基并限制芳香环数量”。
- Agent 必须提供“可解释推理轨迹”，帮助用户判断每个结论为什么成立、证据来自哪里、有哪些反对意见、下一步应该怎么取舍。
- 用户可以上传靶点资料、药物资料、论文、专利、CSV/SDF/SMILES 文件，系统自动解析、入库、向量化并用于后续设计。

它不是实验室，也不替代真实药化专家。它的定位是“自动生成和筛掉大量不靠谱分子，并给出可追踪理由的药物设计智能体”。

说明：这里的“思维链”在产品中不展示模型内部原始隐式推理文本，而展示经过结构化整理的判断轨迹，包括任务目标、关键证据、计算结果、支持理由、反对理由、不确定性和下一步建议。这样既能辅助用户判断，又能避免把未校验的模型内心推演当作事实。

## 2. 最推荐的固定模型栈

为了避免模型选择过多，第一版固定使用下面这一套：

| 模型                | 中文作用     | 用在什么地方                                         | 为什么选它                                                   |
| ------------------- | ------------ | ---------------------------------------------------- | ------------------------------------------------------------ |
| `qwen3.7-max`       | 中枢推理模型 | Central Host Agent、最终排序、复杂决策               | 千问 3.7 Max 是当前百炼最强推理档，支持 1M 上下文，适合长流程 Agent 编排 |
| `qwen3.7-plus`      | 普通任务模型 | 对话理解、文献摘要、字段抽取、报告整理、低风险 Agent | 成本低于 Max，工具调用和长上下文能力完整，适合批量工作       |
| `deepseek-v4-pro`   | 独立反驳模型 | Self-Refutation Agent                                | 作为不同模型家族的“反方审稿人”，降低同一个模型自说自话的风险 |
| `text-embedding-v4` | 向量化模型   | RAG 文档入库、查询向量化                             | 把文本变成向量，便于语义检索；推荐 2048 维                   |
| `qwen3-rerank`      | 重排序模型   | RAG 召回后的精排                                     | 对召回结果重新排序，提升证据相关性                           |

固定原则：

- 中枢只用 `qwen3.7-max`，不让多个中枢抢控制权。
- 对话理解、批量抽取和摘要用 `qwen3.7-plus`，降低成本。
- 自我反驳用 `deepseek-v4-pro`，让它站在反方视角挑战 Qwen 的结论。
- RAG 不让大模型凭记忆回答，必须经过 `text-embedding-v4` 检索和 `qwen3-rerank` 精排。

官方依据：

- 百炼模型文档推荐 Agent 开发使用 `qwen3.7-plus`，最强推理可选 `qwen3.7-max`。
- 百炼文本生成 API 支持 OpenAI 兼容 Chat Completions、Responses、Anthropic 兼容和 DashScope。
- 百炼向量与重排序文档推荐 `text-embedding-v4` 与 `qwen3-rerank` 组合用于 RAG。
- DeepSeek 官方文档说明 `deepseek-v4-pro` 支持 1M 上下文、JSON 输出、工具调用和 thinking mode。

## 3. 系统总体流程

通俗理解：

这个智能体像一个项目经理带着一组专业助手工作。

1. Conversation Agent 理解用户自然语言，把它变成结构化任务和约束。
2. Knowledge Ingestion Agent 导入内置靶点-药物知识库和用户上传资料。
3. 中枢 Agent 读懂任务，拆成多个步骤。
4. RAG Agent 去找资料，不让系统凭空猜。
5. Target Agent 分析靶点和口袋。
6. SAR Agent 分析已知活性分子。
7. Generator Agent 生成候选分子。
8. Filter Agent 先砍掉明显不合理的分子。
9. Docking Agent 看分子是否能合理放进口袋。
10. ADMET Agent 看分子是否可能有成药性风险。
11. Synthesis Agent 看分子是否可能合成。
12. Self-Refutation Agent 专门挑毛病。
13. Ranker Agent 综合所有证据打分。
14. Advisor Agent 根据结果给下一轮优化建议。
15. Report Agent 输出可追踪报告。

主流程：

```text
自然语言输入 / 文件上传 / 内置知识库选择
  -> 对话理解
  -> 用户资料导入
  -> 项目解析
  -> RAG 建库
  -> 靶点与口袋分析
  -> 已知配体和 SAR 分析
  -> 候选分子生成
  -> 基础过滤
  -> RAG + SAR 初筛
  -> Docking 分析
  -> ADMET 预测
  -> 合成可及性评估
  -> 自我反驳
  -> 综合排序
  -> 自然语言建议
  -> 输出候选分子报告
```

## 4. 哪些用 RAG，哪些用关系数据库

很多系统会把所有东西都塞进向量库，这是错的。这里必须分清：

### 4.1 需要 RAG 的内容

RAG 适合“非结构化知识”，例如文字、论文、专利、报告。

需要 RAG 的内容：

- 论文 PDF
- 专利文本
- 靶点综述
- 数据库网页说明
- assay 描述
- SAR 讨论文字
- 毒性风险解释
- 文献里的结论性描述
- 用户上传的项目说明、靶点背景、内部总结文档
- 内置靶点-药物知识库中的文字说明

RAG 的作用：

- 回答“为什么这个靶点可做？”
- 找“这个 scaffold 有没有类似文献？”
- 找“这个靶点已知关键残基是什么？”
- 找“类似结构有没有 hERG、CYP、Ames 风险？”
- 找“这个结构是否可能被专利覆盖？”
- 回答用户自然语言问题，例如“为什么这批分子被淘汰得多？”

### 4.2 需要关系数据库的内容

关系数据库适合“结构化数据”，例如分子、分数、任务状态、文件路径。

需要关系数据库的内容：

- 项目表
- 靶点表
- 内置靶点-药物映射表
- 用户上传文件表
- 对话消息表
- 用户优化约束表
- 分子表
- 分子性质表
- docking 结果表
- ADMET 结果表
- 合成路线表
- Agent 调用日志
- Agent 可解释推理轨迹
- 用户可见判断卡片
- 分子评分表
- 证据引用关系表
- 自我反驳记录表
- Advisor 建议表

关系数据库的作用：

- 记录每个分子从哪里来。
- 记录每个分子为什么被保留或淘汰。
- 记录每个 Agent 的输入输出。
- 记录每个关键判断的支持证据、反对证据、置信度和下一步建议。
- 支持按分数、性质、scaffold、风险筛选。
- 保证报告里的每个结论都能追溯到数据库记录。

### 4.3 两者如何配合

例子：

一个分子 `MOL-000123` docking score 很好，但 Self-Refutation Agent 怀疑它有 hERG 风险。

- 关系数据库保存：`MOL-000123` 的 SMILES、docking score、ADMET score、最终排名。
- RAG 保存：文献里关于类似 scaffold 导致 hERG 风险的文字证据。
- evidence_links 表把这个分子和这段文献证据连起来。

这样最终报告才能说：

“该分子 docking pose 合理，但类似二芳香环阳离子 scaffold 在文献 DOC-0088 中被提示存在 hERG 风险，因此 Con Score 提高。”

## 5. 数据库设计

推荐：PostgreSQL + pgvector + RDKit cartridge。

### 5.1 核心表

| 表名                       | 中文含义        | 存什么                                     | 是否需要向量 |
| -------------------------- | --------------- | ------------------------------------------ | ------------ |
| `projects`                 | 项目表          | 项目名称、靶点、目标、约束                 | 否           |
| `targets`                  | 靶点表          | UniProt、PDB、物种、口袋信息               | 否           |
| `target_drug_library`      | 内置靶点-药物库 | 靶点、已上市药物、临床候选物、机制、适应症 | 部分需要     |
| `binding_sites`            | 结合口袋表      | 口袋坐标、关键残基、grid box               | 否           |
| `seed_ligands`             | 种子配体表      | 已知活性分子、活性值、来源                 | 否           |
| `uploaded_files`           | 用户上传文件表  | 文件路径、文件类型、解析状态、所属项目     | 否           |
| `conversation_messages`    | 对话消息表      | 用户和 Agent 的自然语言消息                | 否           |
| `optimization_constraints` | 优化约束表      | 用户自然语言转成的结构化优化方向           | 否           |
| `molecules`                | 候选分子表      | SMILES、InChIKey、来源、状态               | 否           |
| `molecule_properties`      | 分子性质表      | MW、LogP、TPSA、HBD、HBA、SA Score         | 否           |
| `docking_results`          | 对接结果表      | docking score、pose 文件、相互作用         | 否           |
| `admet_results`            | ADMET 结果表    | hERG、Ames、CYP、DILI、溶解度等            | 否           |
| `synthesis_routes`         | 合成路线表      | retrosynthesis 结果、步数、可买砌块        | 否           |
| `rag_documents`            | RAG 文档表      | 文档元信息、标题、来源、类型               | 是           |
| `rag_chunks`               | RAG 片段表      | 文本切片、页码、章节、chunk 内容           | 是           |
| `evidence_links`           | 证据链接表      | 分子结论和证据 chunk 的关系                | 否           |
| `agent_runs`               | Agent 运行表    | 每次 Agent 调用的输入输出和状态            | 否           |
| `reasoning_traces`         | 推理轨迹表      | 用户可见的判断步骤、证据、取舍和置信度     | 否           |
| `decision_cards`           | 判断卡片表      | 面向前端展示的结论卡、风险卡、建议卡       | 否           |
| `critiques`                | 反驳记录表      | 反对理由、风险等级、证据                   | 否           |
| `advisor_suggestions`      | 智能体建议表    | 当前结果总结、下一轮优化建议、建议参数     | 否           |
| `rankings`                 | 排名表          | 综合评分、排名、推荐等级                   | 否           |

### 5.2 关键字段中文含义

| 字段                  | 中文含义           | 示例                          |
| --------------------- | ------------------ | ----------------------------- |
| `project_id`          | 项目编号           | `PROJ-0001`                   |
| `target_id`           | 靶点编号           | `TGT-EGFR`                    |
| `molecule_id`         | 候选分子编号       | `MOL-000123`                  |
| `smiles`              | 分子线性表达式     | `CCOc1ccc...`                 |
| `inchi_key`           | 分子唯一结构指纹   | `BSYNRYMUTXBXSQ-UHFFFAOYSA-N` |
| `scaffold`            | 核心骨架           | `quinazoline`                 |
| `source_agent`        | 生成该结果的 Agent | `generator_agent`             |
| `status`              | 分子当前状态       | `passed_filter`               |
| `evidence_id`         | 证据编号           | `EVD-0098`                    |
| `chunk_id`            | RAG 文本片段编号   | `CHK-000882`                  |
| `tool_run_id`         | 工具运行编号       | `TOOL-GNINA-0007`             |
| `file_id`             | 用户上传文件编号   | `FILE-0007`                   |
| `message_id`          | 对话消息编号       | `MSG-0009`                    |
| `constraint_id`       | 优化约束编号       | `CONS-0012`                   |
| `drug_name`           | 药物名称           | `osimertinib`                 |
| `mechanism`           | 作用机制           | `EGFR T790M inhibitor`        |
| `indication`          | 适应症             | `non-small cell lung cancer`  |
| `pro_score`           | 支持分数           | `82`                          |
| `con_score`           | 反对分数           | `35`                          |
| `evidence_confidence` | 证据可信度         | `78`                          |
| `overall_score`       | 综合评分           | `80.4`                        |
| `trace_id`            | 推理轨迹编号       | `TRACE-000123`                |
| `decision_id`         | 判断卡片编号       | `DEC-000045`                  |
| `claim`               | 当前判断结论       | `该分子建议进入 Top 50`       |
| `supporting_factors`  | 支持因素           | `docking 合理、TPSA 合格`     |
| `opposing_factors`    | 反对因素           | `hERG 风险偏高`               |
| `uncertainty`         | 不确定性说明       | `缺少真实 ADMET 实验数据`     |

### 5.3 分子状态标签

| 标签                | 中文含义     | 说明                               |
| ------------------- | ------------ | ---------------------------------- |
| `generated`         | 已生成       | Generator Agent 生成，尚未过滤     |
| `invalid_structure` | 结构非法     | RDKit 无法解析或价态错误           |
| `failed_filter`     | 规则过滤失败 | PAINS、Brenk、性质阈值不合格       |
| `passed_filter`     | 通过规则过滤 | 可以进入 SAR/RAG 初筛              |
| `sar_supported`     | SAR 支持     | 与已知活性结构或机制有合理关联     |
| `sar_conflict`      | SAR 冲突     | 与已知 SAR 规则矛盾                |
| `docking_passed`    | 对接通过     | pose 与相互作用合理                |
| `docking_failed`    | 对接失败     | pose 不合理或 score 太差           |
| `admet_risky`       | ADMET 高风险 | 预测出现明显成药性风险             |
| `synthesis_risky`   | 合成高风险   | 路线过长、砌块不可买或反应危险     |
| `critic_rejected`   | 反驳淘汰     | Self-Refutation Agent 判定风险过高 |
| `recommended`       | 推荐候选     | 进入最终 Top 20-50                 |
| `reserve`           | 备选候选     | 有潜力，但证据或性质不足           |

### 5.4 对话意图标签

| 标签                  | 中文含义       | 示例                              |
| --------------------- | -------------- | --------------------------------- |
| `create_project`      | 创建项目       | “我要做 EGFR 的先导优化”          |
| `upload_knowledge`    | 上传知识       | “我上传了几篇论文和一个 SDF 文件” |
| `set_constraint`      | 设置约束       | “cLogP 控制在 3 以下”             |
| `relax_constraint`    | 放宽约束       | “SA score 可以放宽到 5”           |
| `prioritize_property` | 优先优化某性质 | “优先提高溶解度”                  |
| `avoid_risk`          | 避免某风险     | “尽量降低 hERG 风险”              |
| `keep_scaffold`       | 保留骨架       | “保留 quinazoline 母核”           |
| `modify_region`       | 指定改造位置   | “主要改 R6 位”                    |
| `ask_explanation`     | 请求解释       | “为什么这个分子被淘汰？”          |
| `ask_suggestion`      | 请求建议       | “下一轮我该怎么优化？”            |
| `run_pipeline`        | 启动流程       | “按这个方向跑一轮”                |
| `compare_results`     | 对比结果       | “比较第一轮和第二轮差异”          |

### 5.5 优化约束标签

| 标签                     | 中文含义         | 示例                    |
| ------------------------ | ---------------- | ----------------------- |
| `hard_constraint`        | 硬约束，必须满足 | `MW <= 550`             |
| `soft_constraint`        | 软约束，尽量满足 | “优先降低 cLogP”        |
| `objective`              | 优化目标         | `maximize_solubility`   |
| `penalty`                | 扣分项           | `hERG_high_risk`        |
| `protected_motif`        | 保护结构         | “保留 hinge binder”     |
| `editable_region`        | 可编辑区域       | `R6`, `R7`              |
| `forbidden_substructure` | 禁止子结构       | “避免 Michael acceptor” |

## 6. RAG 技术细节

### 6.1 知识来源

第一版知识来源分两类：系统内置知识库和用户上传资料。

系统内置知识库：

系统启动时预先存入一批常见靶点和对应药物信息，让用户不上传资料也能启动项目。

| 靶点      | 中文说明                       | 推荐存入的对应药物或代表分子                  |
| --------- | ------------------------------ | --------------------------------------------- |
| EGFR      | 表皮生长因子受体，常见肺癌靶点 | gefitinib、erlotinib、afatinib、osimertinib   |
| ALK       | 间变性淋巴瘤激酶               | crizotinib、alectinib、brigatinib、lorlatinib |
| BRAF      | RAF 家族激酶，V600E 突变常见   | vemurafenib、dabrafenib、encorafenib          |
| KRAS G12C | KRAS 突变靶点                  | sotorasib、adagrasib                          |
| JAK2      | Janus kinase 2                 | ruxolitinib、fedratinib、pacritinib           |
| BTK       | Bruton's tyrosine kinase       | ibrutinib、acalabrutinib、zanubrutinib        |
| CDK4/6    | 细胞周期蛋白依赖激酶           | palbociclib、ribociclib、abemaciclib          |
| PARP1     | DNA 修复相关靶点               | olaparib、niraparib、rucaparib、talazoparib   |
| PI3K      | 磷脂酰肌醇 3 激酶              | alpelisib、idelalisib、duvelisib              |
| HDAC      | 组蛋白去乙酰化酶               | vorinostat、romidepsin、panobinostat          |

每个内置靶点建议预先存：

- 靶点名称、别名、UniProt ID。
- 代表 PDB 结构和共晶配体。
- 已上市药物和代表候选药物。
- 药物 SMILES、InChIKey、作用机制、适应症。
- 已知关键残基、结合口袋、常见 SAR 规则。
- 已知 ADMET 或安全性风险。
- 参考文献和数据来源。

用户上传资料：

- PDF 论文、专利、综述。
- Word/Markdown/TXT 项目说明。
- CSV/Excel 活性数据表。
- SDF/MOL2/SMILES 分子文件。
- PDB 蛋白结构文件。
- 用户自己整理的靶点和药物说明。

不建议第一版直接做全网任意搜索，因为噪声太大。需要联网时应优先限定 PubMed、ChEMBL、BindingDB、PDB、UniProt、专利库等来源。

### 6.2 内置靶点-药物库如何入库

内置知识库要同时写入关系数据库和 RAG。

进入关系数据库的内容：

- 靶点基础信息 -> `targets`
- 药物结构信息 -> `seed_ligands` 或 `reference_drugs`
- 靶点-药物关系 -> `target_drug_library`
- PDB 和口袋坐标 -> `binding_sites`
- 活性数据 -> `seed_ligands`

进入 RAG 的内容：

- 靶点背景说明。
- 药物机制说明。
- SAR 规则文字。
- 文献摘要。
- 专利或综述中的解释性段落。

示例结构化记录：

```json
{
  "target_id": "TGT-EGFR",
  "target_name": "EGFR",
  "uniprot_id": "P00533",
  "drug_name": "osimertinib",
  "drug_status": "approved",
  "mechanism": "EGFR T790M inhibitor",
  "smiles": "COc1cc(N(C)CCN(C)C)c(NC(=O)C=C)c2ncnc(Nc3ccc(F)c(Cl)c3)c12",
  "indication": "non-small cell lung cancer",
  "evidence_source": "ChEMBL / DrugBank / literature"
}
```

字段中文含义：

- `drug_status`：药物状态，例如已上市、临床、工具分子。
- `mechanism`：作用机制。
- `indication`：适应症。
- `evidence_source`：数据来源。

### 6.3 用户上传资料如何处理

用户上传文件后，系统按文件类型走不同流程：

| 文件类型          | 处理方式                             | 入关系库                             | 入 RAG                        |
| ----------------- | ------------------------------------ | ------------------------------------ | ----------------------------- |
| PDF               | 解析正文、标题、表格、页码           | `uploaded_files`                     | `rag_documents`, `rag_chunks` |
| DOCX/Markdown/TXT | 解析为文本 chunk                     | `uploaded_files`                     | `rag_documents`, `rag_chunks` |
| CSV/Excel         | 识别 SMILES、活性值、靶点、assay     | `seed_ligands`, `molecules`          | 表格说明可入 RAG              |
| SDF/MOL2/SMILES   | 解析分子结构、标准化、去重           | `seed_ligands`, `molecules`          | 不直接入 RAG                  |
| PDB               | 解析蛋白结构、链、配体、坐标         | `targets`, `binding_sites`           | 结构说明可入 RAG              |
| 专利 PDF          | 按 claim/example/compound table 切分 | `uploaded_files`，化合物表入结构化表 | `rag_documents`, `rag_chunks` |

上传流程：

```text
用户上传文件
  -> 文件类型识别
  -> 格式和大小检查
  -> 内容解析
  -> 结构化字段抽取
  -> 写入关系数据库
  -> 文本 chunk 切分
  -> text-embedding-v4 向量化
  -> 写入 rag_chunks
  -> 返回可用知识摘要
```

上传后，Agent 要主动告诉用户：

- 成功解析了多少个文件。
- 抽取了多少个分子。
- 抽取了多少条活性数据。
- 建立了多少个 RAG chunk。
- 哪些文件无法解析。
- 是否发现靶点、口袋或药物名称与当前项目不一致。

### 6.4 文档切分

论文：

- 按标题、摘要、Introduction、Methods、Results、Figure caption、Table caption 切分。
- 每个 chunk 控制在 500-900 中文字或 300-600 英文词。
- 保留 `paper_title`、`doi`、`year`、`page`、`section`。

专利：

- 按 claim、example、compound table、assay table 切分。
- compound table 要单独抽取到结构化表，不只放进向量库。
- 保留 `patent_id`、`claim_number`、`example_id`。

数据库网页：

- 按靶点介绍、assay 描述、活性表、参考文献切分。

### 6.5 向量化

模型：`text-embedding-v4`  
维度：2048  

入库时：

```json
{
  "model": "text-embedding-v4",
  "input_type": "document",
  "dimension": 2048,
  "text": "文档片段内容"
}
```

查询时：

```json
{
  "model": "text-embedding-v4",
  "input_type": "query",
  "dimension": 2048,
  "text": "EGFR quinazoline hERG risk"
}
```

中文解释：

- `document`：表示这是入库文档。
- `query`：表示这是检索问题。
- `dimension`：向量维度，2048 更适合高质量检索。

### 6.6 检索策略

每次 RAG 检索分三步：

1. 向量召回 Top 80。
2. BM25 关键词召回 Top 80。
3. 合并去重后交给 `qwen3-rerank` 精排 Top 10-20。

为什么还要 BM25：

- 向量检索擅长语义相似。
- BM25 擅长精确匹配，比如 `hERG`、`CYP3A4`、`EGFR T790M`、专利号。
- 两者结合比单独向量检索更稳。

### 6.7 RAG 输出格式

```json
{
  "query": "EGFR quinazoline hERG risk",
  "retrieved_chunks": [
    {
      "chunk_id": "CHK-000882",
      "document_id": "DOC-00031",
      "source_type": "paper",
      "title": "Known hERG liabilities in kinase inhibitors",
      "page": 7,
      "section": "Results",
      "rerank_score": 0.91,
      "evidence_summary": "类似双芳香环阳离子结构与 hERG 风险相关"
    }
  ]
}
```

字段中文含义：

- `query`：检索问题。
- `retrieved_chunks`：召回并精排后的证据片段。
- `source_type`：来源类型，例如论文、专利、数据库。
- `rerank_score`：重排序相关性分数。
- `evidence_summary`：该证据片段对当前问题的简短解释。

## 7. Agent 详细设计

### 7.1 Conversation Agent

中文名：自然语言对话智能体  
模型：`qwen3.7-plus`  

它负责和用户聊天，把用户的自然语言变成系统能执行的结构化指令。它不直接生成分子，也不直接做 docking。

它能理解的用户话语示例：

- “我想做 EGFR 的先导优化。”
- “优先降低 hERG 风险，活性可以稍微牺牲一点。”
- “保留 quinazoline 母核，只改 R6 位和 R7 位。”
- “这批结果为什么很多被 ADMET 淘汰？”
- “下一轮帮我更关注溶解度。”
- “我上传了一个 SDF 文件，把里面的分子作为种子分子。”

输入：

```json
{
  "session_id": "CHAT-0001",
  "project_id": "PROJ-0001",
  "user_message": "优先降低 hERG 风险，但不要改变 quinazoline 母核",
  "current_project_state": {
    "target": "EGFR",
    "current_round": 1,
    "top_molecule_count": 50
  }
}
```

输出：

```json
{
  "intent": "set_constraint",
  "intent_confidence": 0.91,
  "structured_constraints": [
    {
      "constraint_type": "penalty",
      "name": "hERG_high_risk",
      "direction": "minimize",
      "priority": "high"
    },
    {
      "constraint_type": "protected_motif",
      "name": "quinazoline_core",
      "priority": "hard"
    }
  ],
  "reply_to_user": "我会把降低 hERG 风险设为高优先级，同时把 quinazoline 母核设为不可改动的硬约束。"
}
```

字段中文含义：

- `intent`：用户意图，例如创建项目、上传知识、设置约束、请求解释。
- `intent_confidence`：意图识别置信度。
- `structured_constraints`：自然语言转成的结构化优化约束。
- `reply_to_user`：给用户看的自然语言回复。

是否调用 RAG：有时需要。例如用户问“为什么这个靶点可做”，需要查 RAG。  
是否写关系数据库：写 `conversation_messages`、`optimization_constraints`。

### 7.2 Knowledge Ingestion Agent

中文名：知识导入智能体  
模型：`qwen3.7-plus` + `text-embedding-v4`  

它负责把系统内置靶点-药物资料和用户上传资料整理成可用知识。

它做三件事：

1. 从内置库加载靶点、药物、结构、SAR、文献证据。
2. 解析用户上传文件，例如 PDF、CSV、SDF、PDB。
3. 决定哪些内容写关系数据库，哪些内容写 RAG。

输入：

```json
{
  "project_id": "PROJ-0001",
  "target": "EGFR",
  "use_builtin_library": true,
  "uploaded_files": [
    {
      "file_id": "FILE-0001",
      "file_path": "minio://uploads/egfr_ligands.sdf",
      "file_type": "sdf"
    },
    {
      "file_id": "FILE-0002",
      "file_path": "minio://uploads/egfr_review.pdf",
      "file_type": "pdf"
    }
  ]
}
```

输出：

```json
{
  "builtin_records_loaded": {
    "targets": 1,
    "reference_drugs": 4,
    "binding_sites": 2
  },
  "uploaded_records_loaded": {
    "files": 2,
    "molecules": 128,
    "activity_records": 76,
    "rag_chunks": 342
  },
  "warnings": [
    "FILE-0001 中有 3 个分子 SMILES 无法标准化，已跳过"
  ]
}
```

是否调用 RAG：它主要构建 RAG，不负责问答。  
是否写关系数据库：写 `uploaded_files`、`target_drug_library`、`seed_ligands`、`molecules`、`rag_documents`、`rag_chunks`。

### 7.3 Central Host Agent

中文名：中枢调度智能体  
模型：`qwen3.7-max`  

它是整个系统的大脑，不直接跑 docking 或 ADMET，而是决定下一步该调用谁、用什么输入、如何合并结果。

输入：

```json
{
  "project_goal": "针对 EGFR 做 lead optimization",
  "target": "EGFR",
  "binding_site": "ATP binding pocket",
  "seed_ligands": ["SMILES1", "SMILES2"],
  "conversation_constraints": [
    {
      "constraint_type": "penalty",
      "name": "hERG_high_risk",
      "direction": "minimize",
      "priority": "high"
    }
  ],
  "knowledge_status": {
    "builtin_library_loaded": true,
    "user_upload_loaded": true
  },
  "constraints": {
    "MW": [250, 550],
    "cLogP": [0, 5],
    "TPSA": [40, 120],
    "SA_score_max": 4.5
  }
}
```

输出：

```json
{
  "project_id": "PROJ-0001",
  "workflow_plan": [
    "parse_user_intent",
    "ingest_knowledge",
    "build_rag",
    "analyze_target",
    "analyze_sar",
    "generate_molecules",
    "filter_molecules",
    "dock_molecules",
    "predict_admet",
    "assess_synthesis",
    "self_refute",
    "rank_candidates",
    "generate_advice",
    "generate_report"
  ],
  "decision_rules": {
    "top_n_final": 50,
    "discard_if_con_score_above": 60
  }
}
```

是否调用 RAG：会，但只用于决策前查证，不直接承担批量检索。  
是否写关系数据库：会，写 `projects`、`agent_runs`、`rankings`。

### 7.4 RAG Builder Agent

中文名：知识库构建智能体  
模型：`qwen3.7-plus` + `text-embedding-v4`  

它负责把论文、专利、数据库说明变成可检索知识库。

调用模型：

- `qwen3.7-plus`：抽取标题、结论、表格说明、关键词。
- `text-embedding-v4`：把文本片段变成向量。

输入：

```json
{
  "project_id": "PROJ-0001",
  "documents": [
    {
      "file_path": "C:/data/egfr_review.pdf",
      "source_type": "paper"
    }
  ],
  "target": "EGFR"
}
```

输出：

```json
{
  "document_count": 12,
  "chunk_count": 860,
  "embedding_model": "text-embedding-v4",
  "dimension": 2048,
  "stored_tables": ["rag_documents", "rag_chunks"]
}
```

是否调用 RAG：它不“查询”RAG，而是“建设”RAG。  
是否写关系数据库：必须写 `rag_documents`、`rag_chunks`。

### 7.3 Target Agent

中文名：靶点分析智能体  
模型：`qwen3.7-plus`  

它回答：这个靶点是什么，口袋在哪里，哪些残基重要，已有结构是否可靠。

调用工具：

- UniProt 查询工具
- PDB 查询工具
- AlphaFold 结构读取
- RDKit/OpenMM/PyMOL/ChimeraX 脚本
- RAG Retriever

输入：

```json
{
  "target_name": "EGFR",
  "uniprot_id": "P00533",
  "pdb_id": "1M17",
  "binding_site_hint": "ATP pocket"
}
```

输出：

```json
{
  "target_id": "TGT-EGFR",
  "protein_structure": {
    "source": "PDB",
    "pdb_id": "1M17",
    "prepared_file": "minio://structures/PROJ-0001/egfr_prepared.pdb"
  },
  "binding_site": {
    "site_name": "ATP binding pocket",
    "center": [23.4, 18.9, 44.2],
    "box_size": [20, 20, 20],
    "key_residues": ["Met793", "Lys745", "Asp855"]
  },
  "evidence_ids": ["EVD-0001", "EVD-0002"]
}
```

字段中文含义：

- `center`：docking 网格中心坐标。
- `box_size`：docking 搜索盒大小。
- `key_residues`：关键残基，后面用来判断 pose 是否合理。

是否调用 RAG：需要，查靶点综述、关键残基、共晶配体。  
是否写关系数据库：写 `targets`、`binding_sites`、`evidence_links`。

### 7.4 SAR Agent

中文名：构效关系分析智能体  
模型：`qwen3.7-plus`  

它回答：已知活性分子里，哪些结构重要，哪些结构最好不要动，哪些改造方向可能提升性质。

调用工具：

- RDKit scaffold 分析
- ChEMBL/BindingDB 查询
- RAG Retriever
- 相似性搜索，Tanimoto similarity

输入：

```json
{
  "target_id": "TGT-EGFR",
  "seed_ligands": [
    {
      "smiles": "COc1cc2ncnc(Nc3ccc...)c2cc1OC",
      "activity_type": "IC50",
      "activity_value": 15,
      "unit": "nM"
    }
  ]
}
```

输出：

```json
{
  "sar_rules": [
    {
      "rule_id": "SAR-001",
      "rule_type": "keep",
      "description": "保留 hinge binder 以维持与 Met793 的氢键",
      "evidence_ids": ["EVD-0010"]
    },
    {
      "rule_id": "SAR-002",
      "rule_type": "avoid",
      "description": "避免引入强碱性大疏水侧链，可能增加 hERG 风险",
      "evidence_ids": ["EVD-0011"]
    }
  ],
  "seed_scaffolds": ["quinazoline"],
  "preferred_modification_sites": ["R6", "R7"]
}
```

标签中文含义：

- `keep`：必须保留的结构特征。
- `avoid`：尽量避免的结构特征。
- `improve`：建议优化的结构位置。
- `unknown`：证据不足，不能下结论。

是否调用 RAG：必须调用，SAR 规则要有文献或数据库证据。  
是否写关系数据库：写 `seed_ligands`、`evidence_links`，SAR 规则可写入 `project_rules`。

### 7.5 Molecule Generator Agent

中文名：候选分子生成智能体  
模型：`qwen3.7-plus` 负责配置生成任务，真实生成由专业工具执行。  

它不让 LLM 直接“想象分子”，而是调用分子生成工具。

调用工具：

- REINVENT4：围绕 seed ligand 做强化学习式优化。
- CReM：基于片段替换生成 analogs。
- AutoGrow4：结合 docking 做结构导向生成。

输入：

```json
{
  "project_id": "PROJ-0001",
  "seed_ligands": ["SMILES1", "SMILES2"],
  "sar_rules": ["SAR-001", "SAR-002"],
  "generation_size": 20000,
  "constraints": {
    "keep_core": true,
    "max_tanimoto_to_seed": 0.85,
    "min_tanimoto_to_seed": 0.35
  }
}
```

输出：

```json
{
  "generated_count": 20000,
  "stored_count": 18420,
  "failed_reason_summary": {
    "duplicate": 980,
    "invalid_smiles": 600
  },
  "molecule_ids": ["MOL-000001", "MOL-000002"]
}
```

字段中文含义：

- `generation_size`：计划生成数量。
- `keep_core`：是否保留核心骨架。
- `max_tanimoto_to_seed`：与种子分子的最高相似度，防止太像。
- `min_tanimoto_to_seed`：与种子分子的最低相似度，防止太发散。

是否调用 RAG：通常不直接调用，使用 SAR Agent 给出的结构规则。  
是否写关系数据库：写 `molecules`。

### 7.6 Filter Agent

中文名：基础规则过滤智能体  
模型：不需要 LLM，主要用 RDKit/Datamol。必要时用 `qwen3.7-plus` 解释过滤原因。  

它负责把明显不合格的结构先删掉。

调用工具：

- RDKit
- Datamol
- MolVS
- PAINS/Brenk/NIH filter
- SA Score

输入：

```json
{
  "molecule_ids": ["MOL-000001", "MOL-000002"],
  "filters": {
    "MW": [250, 550],
    "cLogP": [0, 5],
    "TPSA": [40, 120],
    "HBD_max": 5,
    "HBA_max": 10,
    "RotB_max": 10,
    "SA_score_max": 4.5,
    "remove_pains": true,
    "remove_brenk": true
  }
}
```

输出：

```json
{
  "input_count": 18420,
  "passed_count": 7120,
  "failed_count": 11300,
  "failure_breakdown": {
    "pains": 420,
    "MW_out_of_range": 1900,
    "cLogP_out_of_range": 3100,
    "SA_score_too_high": 2600
  }
}
```

标签中文含义：

- `MW_out_of_range`：分子量超出范围。
- `cLogP_out_of_range`：脂溶性超出范围。
- `TPSA_out_of_range`：极性表面积超出范围。
- `SA_score_too_high`：合成可及性差。
- `pains`：命中 PAINS 干扰结构。
- `brenk`：命中 Brenk 结构警报。

是否调用 RAG：不需要。  
是否写关系数据库：写 `molecule_properties`，更新 `molecules.status`。

### 7.7 Literature RAG Agent

中文名：文献证据检索智能体  
模型：`text-embedding-v4` + `qwen3-rerank` + `qwen3.7-plus`  

它负责把问题变成检索 query，并返回可引用证据。

调用模型：

- `text-embedding-v4`：语义召回。
- `qwen3-rerank`：候选证据重排序。
- `qwen3.7-plus`：总结证据，判断是否相关。

输入：

```json
{
  "query_type": "risk_check",
  "query": "quinazoline scaffold hERG CYP3A4 risk EGFR inhibitor",
  "target_id": "TGT-EGFR",
  "molecule_id": "MOL-000123",
  "top_k": 20
}
```

输出：

```json
{
  "evidence_ids": ["EVD-0101", "EVD-0102"],
  "answer": "类似 quinazoline kinase inhibitors 曾被报道存在 CYP 和 hERG 风险，需要关注碱性侧链和高 LogP。",
  "confidence": 0.78,
  "missing_information": []
}
```

字段中文含义：

- `query_type`：检索类型，比如风险检查、SAR 支持、专利检查。
- `confidence`：证据可信度，不是分子好坏分数。
- `missing_information`：缺失信息，如果为空说明证据基本够用。

是否调用 RAG：它就是 RAG 查询入口。  
是否写关系数据库：写 `evidence_links` 和查询日志。

### 7.8 Docking Agent

中文名：分子对接智能体  
模型：`qwen3.7-plus` 负责解释结果，docking 由工具执行。  

调用工具：

- GNINA：主要 docking 和 CNN rescore。
- AutoDock Vina：快速 baseline。
- DiffDock：pose prediction 补充。
- ODDT/RDKit：相互作用分析。

输入：

```json
{
  "target_id": "TGT-EGFR",
  "binding_site_id": "SITE-0001",
  "molecule_ids": ["MOL-000123"],
  "protein_file": "minio://structures/egfr_prepared.pdb",
  "grid_center": [23.4, 18.9, 44.2],
  "grid_size": [20, 20, 20],
  "key_residues": ["Met793", "Lys745", "Asp855"]
}
```

输出：

```json
{
  "molecule_id": "MOL-000123",
  "docking_score": -9.1,
  "cnn_score": 0.78,
  "pose_file": "minio://dockings/MOL-000123_pose.sdf",
  "interactions": [
    {
      "type": "hydrogen_bond",
      "residue": "Met793",
      "distance": 2.8
    }
  ],
  "pose_quality": "good",
  "docking_decision": "passed"
}
```

标签中文含义：

- `hydrogen_bond`：氢键。
- `salt_bridge`：盐桥。
- `pi_pi`：芳环堆积。
- `hydrophobic_contact`：疏水接触。
- `pose_quality=good`：构象合理。
- `pose_quality=bad`：构象不可信。

是否调用 RAG：需要少量调用，用来确认关键残基和已知相互作用。  
是否写关系数据库：写 `docking_results`。

### 7.9 ADMET Agent

中文名：成药性预测智能体  
模型：`qwen3.7-plus` 负责解释，预测由 ADMET 工具执行。  

调用工具：

- ADMETlab 3.0
- Chemprop
- DeepChem
- RDKit descriptor

输入：

```json
{
  "molecule_ids": ["MOL-000123"],
  "properties": [
    "solubility",
    "permeability",
    "hERG",
    "CYP3A4",
    "CYP2D6",
    "Ames",
    "DILI",
    "Pgp_substrate"
  ]
}
```

输出：

```json
{
  "molecule_id": "MOL-000123",
  "admet": {
    "solubility": "medium",
    "hERG": "medium_risk",
    "CYP3A4": "low_risk",
    "Ames": "low_risk",
    "DILI": "unknown",
    "Pgp_substrate": "possible"
  },
  "admet_risk_score": 38,
  "main_risks": ["hERG medium risk", "Pgp possible substrate"]
}
```

标签中文含义：

- `low_risk`：低风险。
- `medium_risk`：中等风险。
- `high_risk`：高风险。
- `unknown`：模型无法可靠判断。
- `possible`：可能存在，需要后续关注。

是否调用 RAG：需要，主要用于解释类似结构的已知毒性或代谢风险。  
是否写关系数据库：写 `admet_results`。

### 7.10 Synthesis Agent

中文名：合成可及性智能体  
模型：`qwen3.7-plus` 负责解释，路线由 retrosynthesis 工具生成。  

调用工具：

- AiZynthFinder
- ASKCOS，若可接入
- building block 库
- RDKit reaction template

输入：

```json
{
  "molecule_ids": ["MOL-000123"],
  "max_steps": 5,
  "prefer_buyable_building_blocks": true
}
```

输出：

```json
{
  "molecule_id": "MOL-000123",
  "route_found": true,
  "route_steps": 4,
  "buyable_building_blocks": 3,
  "route_risk": "medium",
  "route_summary": "可由两个可买芳香胺砌块和一个氯代杂环中间体经取代反应得到"
}
```

标签中文含义：

- `route_found`：是否找到路线。
- `route_steps`：预计合成步数。
- `buyable_building_blocks`：可购买砌块数量。
- `route_risk`：路线风险。

是否调用 RAG：一般不需要，除非要查专利路线或文献反应。  
是否写关系数据库：写 `synthesis_routes`。

### 7.11 Self-Refutation Agent

中文名：自我反驳智能体  
模型：`deepseek-v4-pro`，thinking mode 开启。  

它的任务不是帮系统找理由，而是反过来问：“为什么这个分子不该被推荐？”

调用工具：

- Literature RAG Agent
- 分子相似性搜索
- ADMET 结果查询
- docking 结果查询
- synthesis 结果查询
- patent/scaffold 检索

输入：

```json
{
  "molecule_id": "MOL-000123",
  "host_claim": "该分子建议进入最终 Top 50",
  "supporting_evidence": ["EVD-0101", "EVD-0102"],
  "tool_results": {
    "docking_score": -9.1,
    "pose_quality": "good",
    "admet_risk_score": 38,
    "route_steps": 4
  }
}
```

输出：

```json
{
  "molecule_id": "MOL-000123",
  "critiques": [
    {
      "risk_type": "admet",
      "risk_label": "hERG_risk",
      "severity": "medium",
      "argument": "该分子含高疏水芳香片段和可能带正电侧链，与部分 hERG 风险结构相似。",
      "evidence_ids": ["EVD-0201"]
    }
  ],
  "con_score": 42,
  "refutation_decision": "reserve"
}
```

标签中文含义：

- `risk_type=admet`：成药性风险。
- `risk_type=sar`：构效关系风险。
- `risk_type=docking`：对接姿势风险。
- `risk_type=synthesis`：合成风险。
- `risk_type=patent`：专利风险。
- `severity=low`：低风险。
- `severity=medium`：中等风险。
- `severity=high`：高风险。
- `refutation_decision=pass`：反驳后仍可推荐。
- `refutation_decision=reserve`：进入备选，不进第一推荐。
- `refutation_decision=reject`：淘汰。

是否调用 RAG：必须调用，而且重点查反证。  
是否写关系数据库：写 `critiques`、`evidence_links`。

注意：

DeepSeek thinking mode 调工具时，如果供应商协议要求在多轮工具调用中回传 `reasoning_content`，只能把它作为内部会话状态保存和传递，不作为用户可见解释内容。用户侧只展示结构化后的 `ReasoningTrace` 和 `DecisionCard`。工程上要把 DeepSeek 的会话管理单独封装。

### 7.12 Ranker Agent

中文名：综合排序智能体  
模型：`qwen3.7-max`  

它把所有工具分数和反驳结果合并，输出最终排名。

输入：

```json
{
  "molecule_id": "MOL-000123",
  "sar_score": 80,
  "docking_score_norm": 84,
  "admet_score": 62,
  "synthesis_score": 75,
  "novelty_score": 70,
  "con_score": 42,
  "evidence_confidence": 78
}
```

输出：

```json
{
  "molecule_id": "MOL-000123",
  "overall_score": 72.6,
  "rank": 18,
  "final_decision": "recommended",
  "decision_reason": "结构对接和 SAR 证据较好，ADMET 风险中等但未达到淘汰阈值。"
}
```

评分公式：

```text
overall_score =
  0.25 * SAR_score
+ 0.20 * docking_score_norm
+ 0.20 * ADMET_score
+ 0.15 * synthesis_score
+ 0.10 * novelty_score
+ 0.10 * evidence_confidence
- refutation_penalty
```

反驳扣分：

| Con Score | 中文含义     | 扣分     |
| --------- | ------------ | -------- |
| 0-20      | 反对理由很弱 | 0-5      |
| 21-40     | 有轻中度风险 | 5-12     |
| 41-60     | 风险明显     | 12-25    |
| >60       | 风险过高     | 直接淘汰 |

是否调用 RAG：一般不直接调用，依赖前面 Agent 给出的 evidence。  
是否写关系数据库：写 `rankings`。

### 7.13 Advisor Agent

中文名：优化建议智能体  
模型：`qwen3.7-max`  

它负责把分析结果翻译成用户能理解、下一轮能执行的建议。它不是简单总结报告，而是回答“下一轮怎么改”。

它能回答的问题：

- “为什么这一轮很多分子被淘汰？”
- “下一轮该优先优化什么？”
- “如果我想降低 hERG 风险，生成参数怎么改？”
- “Top 50 里主要有哪些结构趋势？”
- “为什么某个分子排名下降？”

输入：

```json
{
  "project_id": "PROJ-0001",
  "round_id": "ROUND-0001",
  "summary_stats": {
    "generated_count": 20000,
    "passed_filter_count": 7120,
    "docking_passed_count": 620,
    "recommended_count": 50
  },
  "failure_breakdown": {
    "cLogP_out_of_range": 3100,
    "SA_score_too_high": 2600,
    "hERG_medium_or_high_risk": 180,
    "docking_pose_bad": 420
  },
  "top_molecule_patterns": [
    "quinazoline core retained",
    "R6 polar substituent appears beneficial",
    "bulky hydrophobic amine increases hERG risk"
  ],
  "user_goal": "下一轮优先降低 hERG 风险，同时保留 quinazoline 母核"
}
```

输出：

```json
{
  "natural_language_advice": "这一轮主要问题集中在 cLogP 偏高和 hERG 中等风险。建议下一轮保留 quinazoline 母核，但限制强碱性疏水侧链，优先在 R6 位引入小体积极性取代基。",
  "next_round_constraints": [
    {
      "constraint_type": "hard_constraint",
      "name": "protected_motif",
      "value": "quinazoline_core"
    },
    {
      "constraint_type": "soft_constraint",
      "name": "cLogP",
      "target_range": [1.5, 3.5]
    },
    {
      "constraint_type": "penalty",
      "name": "basic_hydrophobic_amine",
      "weight": 0.8
    },
    {
      "constraint_type": "editable_region",
      "name": "R6",
      "preferred_substituents": ["morpholine", "small ether", "amide"]
    }
  ],
  "suggested_generation_config": {
    "generation_size": 15000,
    "min_tanimoto_to_seed": 0.45,
    "max_tanimoto_to_seed": 0.82,
    "increase_admet_weight": true,
    "decrease_hydrophobicity_weight": true
  }
}
```

字段中文含义：

- `natural_language_advice`：给用户看的建议。
- `next_round_constraints`：下一轮可直接使用的结构化约束。
- `suggested_generation_config`：下一轮生成模型参数建议。
- `failure_breakdown`：失败原因统计。
- `top_molecule_patterns`：高排名分子的共同结构趋势。

是否调用 RAG：需要，尤其当建议涉及文献证据、SAR 规律或已知风险时。  
是否写关系数据库：写 `advisor_suggestions`、`optimization_constraints`。

### 7.14 Report Agent

中文名：报告生成智能体  
模型：`qwen3.7-plus`  

它负责把最终结果变成用户能读懂的报告。

输入：

```json
{
  "project_id": "PROJ-0001",
  "top_n": 50,
  "include_sections": [
    "summary",
    "top_molecules",
    "evidence",
    "critiques",
    "technical_appendix"
  ]
}
```

输出：

```json
{
  "report_file": "minio://reports/PROJ-0001/final_report.md",
  "top_molecule_count": 50,
  "appendix_files": [
    "minio://reports/PROJ-0001/docking_summary.csv",
    "minio://reports/PROJ-0001/admet_summary.csv"
  ]
}
```

是否调用 RAG：不重新检索，只引用已有证据。  
是否写关系数据库：写报告路径到 `projects` 或 `agent_runs`。

### 7.15 Reasoning Trace / Decision Explanation 机制

中文名：可解释推理轨迹 / 判断解释机制  
模型：由各业务 Agent 输出结构化片段，最终由 `qwen3.7-plus` 整理成用户可读版本  

它负责把智能体的关键判断翻译成用户能检查、能质疑、能继续决策的“判断轨迹”。它不是暴露模型内部原始思维链，而是展示经过结构化整理的依据链。

必须展示给用户的内容：

- 当前判断结论：例如“该分子建议保留进入下一轮”。
- 判断适用对象：项目、分子、靶点、证据或一轮优化任务。
- 支持因素：例如 docking pose 合理、关键氢键存在、TPSA 在约束范围内。
- 反对因素：例如 hERG 风险、PAINS 警报、合成路线过长。
- 证据来源：关系数据库记录、RAG chunk、文件页码、工具运行结果。
- 置信度：用 `low`、`medium`、`high` 或 0-100 分表示。
- 不确定性：说明哪些信息缺失，哪些结论需要实验或专家复核。
- 下一步建议：给用户 1-3 个可以执行的操作。

不应该展示或保存的内容：

- 模型内部原始 token 级推理文本。
- 未经证据支持的长篇猜测。
- 把模型自我推演伪装成事实证据。
- 会误导用户以为已经完成实验验证的表达。

标准输出结构：

```json
{
  "trace_id": "TRACE-000123",
  "project_id": "PROJ-0001",
  "molecule_id": "MOL-000123",
  "agent_name": "ranker_agent",
  "claim": "该分子建议进入 Top 50，但需要重点关注 hERG 风险",
  "decision_type": "ranking_decision",
  "confidence": 0.78,
  "supporting_factors": [
    {
      "type": "computed_metric",
      "label": "docking_score",
      "value": -9.1,
      "why_it_matters": "对接分数优于本轮中位数"
    },
    {
      "type": "evidence",
      "evidence_id": "EVD-0008",
      "claim": "类似 scaffold 可与 EGFR hinge 区形成关键氢键"
    }
  ],
  "opposing_factors": [
    {
      "type": "risk",
      "label": "hERG_risk",
      "severity": "medium",
      "reason": "阳离子中心和高疏水性组合可能增加 hERG 风险"
    }
  ],
  "uncertainties": [
    "当前 ADMET 结果来自预测模型，不等同于实验值",
    "RAG 证据来自相似 scaffold，并非完全相同分子"
  ],
  "recommended_next_actions": [
    "保留该分子进入下一轮，但优先设计降低 cLogP 的类似物",
    "要求 Generator Agent 生成保留 hinge binding motif 的低疏水替代物"
  ],
  "source_refs": [
    "RUN-DOCK-0007",
    "ADMET-0012",
    "EVD-0008"
  ]
}
```

前端展示建议：

- 在分子详情页显示“为什么保留 / 为什么淘汰”卡片。
- 在 Top 排名表中显示简短判断摘要，例如“强 docking，ADMET 中风险”。
- 在报告中为每个 Top 分子生成“支持理由、反对理由、不确定性、下一步建议”四栏。
- 允许用户点击证据编号，跳转到 RAG 片段、上传文件页码或工具运行结果。
- 对低置信度结论显示醒目标记，避免用户误以为是确定结论。

各 Agent 的接入方式：

- `Filter Agent`：输出淘汰原因和触发规则。
- `Docking Agent`：输出 pose 合理性、关键相互作用和几何风险。
- `ADMET Agent`：输出每个风险项的原因、阈值和模型来源。
- `Synthesis Agent`：输出路线可行性、难点和可买砌块。
- `Self-Refutation Agent`：输出反对理由和证据。
- `Ranker Agent`：把支持因素和反对因素合并成最终判断卡片。
- `Advisor Agent`：把判断卡片转成下一轮优化建议。
- `Report Agent`：把判断卡片整理进最终报告。

落库建议：

- `reasoning_traces` 保存完整结构化 JSON。
- `decision_cards` 保存前端直接展示的精简版本。
- `evidence_links` 连接 trace/card 与 RAG chunk、工具结果、分子记录。
- `agent_runs.output_json` 保留原始结构化输出，方便调试和复现。

## 8. 输入输出对齐

为了避免 Agent 之间“说得上但接不上”，所有阶段都要用固定数据对象。

### 8.1 ProjectSpec 项目规格

```json
{
  "project_id": "PROJ-0001",
  "target_name": "EGFR",
  "task_type": "lead_optimization",
  "seed_ligands": ["SMILES1", "SMILES2"],
  "constraints": {
    "MW": [250, 550],
    "cLogP": [0, 5],
    "TPSA": [40, 120],
    "HBD_max": 5,
    "HBA_max": 10,
    "RotB_max": 10,
    "SA_score_max": 4.5
  }
}
```

中文含义：

- `task_type`：任务类型。第一版固定为 `lead_optimization`，即先导优化。
- `seed_ligands`：种子配体，用来限制生成空间。
- `constraints`：硬性药化约束。

### 8.2 MoleculeRecord 分子记录

```json
{
  "molecule_id": "MOL-000123",
  "project_id": "PROJ-0001",
  "smiles": "CC...",
  "inchi_key": "XXXX",
  "source_agent": "generator_agent",
  "status": "passed_filter"
}
```

### 8.3 EvidenceRecord 证据记录

```json
{
  "evidence_id": "EVD-0001",
  "chunk_id": "CHK-0001",
  "claim": "EGFR hinge binder 通常需要与 Met793 形成氢键",
  "source_type": "paper",
  "source_ref": "DOI or file path",
  "page": 4,
  "confidence": 0.86
}
```

### 8.4 AgentRun Agent 运行记录

```json
{
  "agent_run_id": "RUN-0001",
  "agent_name": "docking_agent",
  "model": "qwen3.7-plus",
  "input_ref": "molecule_batch_001",
  "output_ref": "docking_batch_001",
  "status": "success",
  "started_at": "2026-07-05T10:00:00Z",
  "ended_at": "2026-07-05T10:30:00Z"
}
```

状态标签：

| 标签       | 中文含义 |
| ---------- | -------- |
| `pending`  | 等待执行 |
| `running`  | 正在执行 |
| `success`  | 执行成功 |
| `failed`   | 执行失败 |
| `retrying` | 正在重试 |
| `skipped`  | 被跳过   |

### 8.5 ReasoningTrace 推理轨迹

```json
{
  "trace_id": "TRACE-000123",
  "project_id": "PROJ-0001",
  "agent_run_id": "RUN-0001",
  "molecule_id": "MOL-000123",
  "claim": "该分子建议保留进入下一轮优化",
  "decision_type": "keep_candidate",
  "confidence": 0.78,
  "supporting_factors": [
    {
      "label": "docking_score_good",
      "value": -9.1,
      "source_ref": "RUN-DOCK-0007"
    }
  ],
  "opposing_factors": [
    {
      "label": "hERG_medium_risk",
      "severity": "medium",
      "source_ref": "ADMET-0012"
    }
  ],
  "uncertainties": [
    "缺少真实 ADMET 实验数据"
  ],
  "recommended_next_actions": [
    "降低疏水性并保留关键 hinge binding motif"
  ]
}
```

字段中文含义：

- `claim`：智能体当前要用户相信或参考的结论。
- `decision_type`：判断类型，例如 `keep_candidate`、`reject_candidate`、`ranking_decision`、`next_round_advice`。
- `supporting_factors`：支持该结论的计算结果、证据或规则。
- `opposing_factors`：反对该结论的风险、证据或规则。
- `uncertainties`：当前信息不足或需要实验复核的地方。
- `recommended_next_actions`：用户或下一轮 Agent 可以执行的动作。

### 8.6 DecisionCard 判断卡片

```json
{
  "decision_id": "DEC-000045",
  "trace_id": "TRACE-000123",
  "title": "建议保留，但需要降低 hERG 风险",
  "summary": "该分子 docking 和关键相互作用较好，但疏水性与阳离子特征提示中等 hERG 风险。",
  "confidence_label": "medium_high",
  "display_sections": {
    "support": ["docking score 优于本轮中位数", "保留关键 hinge binding motif"],
    "risk": ["hERG 预测中风险", "RAG 证据来自相似 scaffold"],
    "next": ["生成低 cLogP 类似物", "保留核心氢键供体/受体排布"]
  }
}
```

字段中文含义：

- `DecisionCard` 是给前端和报告直接展示的精简对象。
- 它来自 `ReasoningTrace`，但语言更短、更适合用户阅读。
- 它必须保留 `trace_id`，方便用户回到完整判断轨迹。

### 8.7 ConversationMessage 对话消息

```json
{
  "message_id": "MSG-0001",
  "session_id": "CHAT-0001",
  "project_id": "PROJ-0001",
  "role": "user",
  "content": "下一轮优先降低 hERG 风险，但保留 quinazoline 母核",
  "parsed_intent": "set_constraint",
  "created_at": "2026-07-05T10:40:00Z"
}
```

字段中文含义：

- `role`：消息角色，`user` 是用户，`assistant` 是智能体。
- `content`：自然语言原文。
- `parsed_intent`：Conversation Agent 识别出的意图。

### 8.8 UploadedFile 用户上传文件

```json
{
  "file_id": "FILE-0001",
  "project_id": "PROJ-0001",
  "file_name": "egfr_ligands.sdf",
  "file_type": "sdf",
  "storage_path": "minio://uploads/egfr_ligands.sdf",
  "parse_status": "success",
  "extracted_molecule_count": 128,
  "extracted_chunk_count": 0
}
```

状态标签：

| 标签              | 中文含义       |
| ----------------- | -------------- |
| `uploaded`        | 已上传，未解析 |
| `parsing`         | 正在解析       |
| `success`         | 解析成功       |
| `partial_success` | 部分解析成功   |
| `failed`          | 解析失败       |

### 8.9 OptimizationConstraint 优化约束

```json
{
  "constraint_id": "CONS-0001",
  "project_id": "PROJ-0001",
  "source": "conversation",
  "constraint_type": "penalty",
  "name": "hERG_high_risk",
  "direction": "minimize",
  "priority": "high",
  "is_active": true
}
```

字段中文含义：

- `source`：约束来源，例如用户对话、Advisor 建议、系统默认。
- `constraint_type`：约束类型。
- `direction`：优化方向，例如增大、减小、保留、避免。
- `priority`：优先级。
- `is_active`：是否在当前轮生效。

## 9. 定量计算与标签体系

这里要先说清楚一个关键点：AI 不应该自己“心算”分子的化学性质。LLM 负责理解目标、调度工具、解释结果和做多目标权衡；真正的定量计算由专业工具完成，例如 RDKit、Datamol、GNINA、ADMET 模型、相似性搜索和合成路线工具。

通俗地说：

- LLM 像项目经理和解释器。
- 数学工具像实验仪器和计算器。
- 数据库保存每次计算结果。
- Ranker Agent 只使用这些可追踪数值做综合排序。

### 9.1 定量计算总览

| 计算模块       | 主要工具                         | 算什么                                   | 主要用途             |
| -------------- | -------------------------------- | ---------------------------------------- | -------------------- |
| 结构合法性     | RDKit, Datamol                   | SMILES 是否有效、价态、盐、重复、标准化  | 淘汰非法分子         |
| 物化性质       | RDKit                            | MW、cLogP、TPSA、HBD、HBA、RotB、QED 等  | 基础药物样性过滤     |
| 结构警报       | RDKit filters, PAINS, Brenk      | PAINS、反应性基团、毒性警报              | 早期风险淘汰         |
| 相似性和新颖性 | RDKit fingerprints               | Tanimoto 相似度、scaffold、聚类、多样性  | 控制不要太像或太发散 |
| 3D 构象        | RDKit, OpenBabel, OMEGA 可选     | 构象生成、strain energy、构象数量        | 判断 3D 合理性       |
| Docking        | GNINA, Vina, DiffDock            | docking score、CNN score、pose、相互作用 | 判断是否可能结合口袋 |
| ADMET          | ADMETlab, Chemprop, DeepChem     | hERG、CYP、Ames、DILI、溶解度、渗透性等  | 判断成药性风险       |
| 合成可及性     | SA Score, SCScore, AiZynthFinder | SA score、路线步数、可买砌块、路线风险   | 判断是否可能合成     |
| 多目标评分     | 自定义 scoring function          | SAR、docking、ADMET、合成、反驳扣分      | 生成最终排名         |

### 9.2 结构合法性计算

输入：

```json
{
  "smiles": "COc1cc2ncnc(Nc3ccc...)c2cc1OC"
}
```

计算项：

| 字段                      | 中文含义        | 输出类型 | 示例         |
| ------------------------- | --------------- | -------- | ------------ |
| `valid_smiles`            | SMILES 是否有效 | 布尔值   | `true`       |
| `canonical_smiles`        | 标准化 SMILES   | 字符串   | `COc1cc2...` |
| `inchi_key`               | 分子唯一结构键  | 字符串   | `BSYNRY...`  |
| `largest_fragment_smiles` | 最大有机片段    | 字符串   | `COc1cc2...` |
| `salt_removed`            | 是否去盐        | 布尔值   | `true`       |
| `metal_removed`           | 是否去金属      | 布尔值   | `false`      |
| `formal_charge`           | 总形式电荷      | 整数     | `0`          |
| `valence_valid`           | 价态是否合法    | 布尔值   | `true`       |

输出标签：

| 标签                  | 中文含义        |
| --------------------- | --------------- |
| `valid_structure`     | 结构合法        |
| `invalid_smiles`      | SMILES 无法解析 |
| `invalid_valence`     | 价态错误        |
| `mixture_removed`     | 混合物已处理    |
| `salt_stripped`       | 盐已去除        |
| `duplicate_structure` | 重复分子        |

用途：

- `invalid_smiles`、`invalid_valence` 直接淘汰。
- `duplicate_structure` 不进入后续计算。

### 9.3 物化性质计算

工具：RDKit。

这些是第一层硬过滤最重要的指标。

| 字段                 | 中文含义         | 推荐范围       | 说明                              |
| -------------------- | ---------------- | -------------- | --------------------------------- |
| `MW`                 | 分子量           | 250-550        | 太小可能不够作用，太大吸收差      |
| `cLogP`              | 计算脂水分配系数 | 0-5，优先 1-4  | 越高越疏水，hERG 和溶解度风险上升 |
| `TPSA`               | 拓扑极性表面积   | 40-120         | 影响渗透性和溶解度                |
| `HBD`                | 氢键供体数       | <= 5           | 太多会影响膜通透                  |
| `HBA`                | 氢键受体数       | <= 10          | 太多会影响膜通透                  |
| `RotB`               | 可旋转键数       | <= 10          | 太多构象太自由                    |
| `HeavyAtomCount`     | 重原子数         | 15-45          | 分子大小参考                      |
| `RingCount`          | 环数量           | 1-6            | 环太多可能复杂或疏水              |
| `AromaticRingCount`  | 芳香环数量       | 1-4            | 太多易带来溶解度/hERG 风险        |
| `FractionCSP3`       | sp3 碳比例       | 越高通常越立体 | 低值说明分子偏平面                |
| `QED`                | 类药性综合分     | 0-1，越高越好  | RDKit 的 drug-likeness 指标       |
| `LipinskiViolations` | Lipinski 违规数  | 0-1 优先       | 口服药经验规则                    |
| `VeberViolations`    | Veber 违规数     | 0 优先         | 与口服吸收相关                    |

输出标签：

| 标签                | 中文含义         |
| ------------------- | ---------------- |
| `drug_like`         | 药物样性较好     |
| `mw_out_of_range`   | 分子量超范围     |
| `high_logp`         | 脂溶性偏高       |
| `low_logp`          | 脂溶性偏低       |
| `tpsa_out_of_range` | 极性表面积不合适 |
| `too_many_hbd`      | 氢键供体过多     |
| `too_many_hba`      | 氢键受体过多     |
| `too_flexible`      | 可旋转键过多     |
| `too_flat`          | 分子过于平面     |
| `low_qed`           | 类药性偏低       |

示例输出：

```json
{
  "molecule_id": "MOL-000123",
  "physchem": {
    "MW": 438.9,
    "cLogP": 3.7,
    "TPSA": 82.4,
    "HBD": 2,
    "HBA": 7,
    "RotB": 6,
    "QED": 0.64,
    "LipinskiViolations": 0
  },
  "labels": ["drug_like"]
}
```

### 9.4 结构警报和毒性团过滤

工具：RDKit substructure search、PAINS、Brenk、NIH filter、内部 SMARTS 规则。

计算项：

| 字段                 | 中文含义                | 输出         |
| -------------------- | ----------------------- | ------------ |
| `PAINS_hit`          | 是否命中 PAINS 干扰结构 | `true/false` |
| `Brenk_hit`          | 是否命中 Brenk 警报     | `true/false` |
| `NIH_hit`            | 是否命中 NIH 警报       | `true/false` |
| `reactive_group_hit` | 是否有反应性基团        | `true/false` |
| `toxicophore_hit`    | 是否有已知毒性结构片段  | `true/false` |
| `alert_smarts`       | 命中的 SMARTS 规则      | 列表         |

输出标签：

| 标签                | 中文含义         |
| ------------------- | ---------------- |
| `pains_alert`       | PAINS 警报       |
| `brenk_alert`       | Brenk 警报       |
| `reactive_group`    | 反应性基团       |
| `toxicophore_alert` | 毒性结构警报     |
| `covalent_warhead`  | 可能共价 warhead |
| `unstable_group`    | 不稳定官能团     |

处理规则：

- `pains_alert` 默认淘汰。
- `reactive_group` 默认淘汰，除非项目明确需要共价抑制剂。
- `covalent_warhead` 需要用户显式允许。

### 9.5 相似性、新颖性和多样性计算

工具：RDKit Morgan fingerprint、Murcko scaffold、Tanimoto similarity、Butina clustering。

计算项：

| 字段                         | 中文含义               | 示例          |
| ---------------------------- | ---------------------- | ------------- |
| `morgan_fp`                  | Morgan 指纹            | 二进制向量    |
| `murcko_scaffold`            | Bemis-Murcko 骨架      | `quinazoline` |
| `tanimoto_to_seed_max`       | 与种子分子最高相似度   | `0.72`        |
| `tanimoto_to_known_drug_max` | 与已知药物最高相似度   | `0.64`        |
| `tanimoto_to_patent_max`     | 与专利分子最高相似度   | `0.81`        |
| `tanimoto_to_toxic_set_max`  | 与毒性分子集最高相似度 | `0.58`        |
| `cluster_id`                 | 聚类编号               | `CL-003`      |
| `diversity_score`            | 多样性分数             | `76`          |

输出标签：

| 标签                    | 中文含义               |
| ----------------------- | ---------------------- |
| `seed_like`             | 接近种子分子           |
| `too_close_to_seed`     | 与种子太像，创新性低   |
| `too_far_from_seed`     | 与种子太远，SAR 风险高 |
| `known_drug_like`       | 接近已知药物           |
| `patent_risk_high`      | 专利相似性风险高       |
| `toxic_similarity_risk` | 与毒性分子相似         |
| `novel_scaffold`        | 新骨架                 |
| `same_scaffold`         | 与种子同骨架           |
| `diverse_candidate`     | 多样性较好             |

推荐规则：

- `tanimoto_to_seed_max` 低于 0.35：可能太发散。
- `tanimoto_to_seed_max` 高于 0.85：可能太像种子。
- `tanimoto_to_patent_max` 高于 0.80：标记 `patent_risk_high`。
- `tanimoto_to_toxic_set_max` 高于 0.65：标记 `toxic_similarity_risk`。

### 9.6 3D 构象和几何质量计算

工具：RDKit ETKDG、MMFF/UFF、OpenBabel，可选商业构象工具。

计算项：

| 字段                       | 中文含义             |
| -------------------------- | -------------------- |
| `conformer_generated`      | 是否成功生成 3D 构象 |
| `conformer_count`          | 构象数量             |
| `lowest_energy`            | 最低构象能量         |
| `strain_energy`            | 结合构象应变能       |
| `rmsd_between_conformers`  | 构象间 RMSD          |
| `chiral_centers`           | 手性中心数量         |
| `undefined_stereo_centers` | 未定义手性中心数量   |

输出标签：

| 标签                     | 中文含义     |
| ------------------------ | ------------ |
| `conformer_ok`           | 构象生成成功 |
| `conformer_failed`       | 构象生成失败 |
| `high_strain`            | 构象应变高   |
| `stereo_undefined`       | 手性未定义   |
| `too_many_stereocenters` | 手性中心过多 |

处理规则：

- `conformer_failed` 不进入 docking。
- `high_strain` 会降低 docking 可信度。
- `stereo_undefined` 进入备选或要求明确立体化学。

### 9.7 Docking 定量输出

工具：GNINA、AutoDock Vina、DiffDock、ODDT/RDKit 相互作用分析。

计算项：

| 字段                        | 中文含义                | 说明                       |
| --------------------------- | ----------------------- | -------------------------- |
| `vina_score`                | Vina 对接分数           | 越负通常越好               |
| `gnina_affinity`            | GNINA 预测亲和力        | 越负通常越好               |
| `cnn_score`                 | GNINA CNN pose 评分     | 0-1，越高 pose 越可信      |
| `cnn_affinity`              | GNINA CNN affinity      | 预测结合强度               |
| `diffdock_confidence`       | DiffDock pose 置信度    | 越高越可信                 |
| `key_hbond_count`           | 关键氢键数量            | 与关键残基形成氢键         |
| `hydrophobic_contact_count` | 疏水接触数量            | 与疏水口袋接触数           |
| `clash_count`               | 原子冲突数量            | 越少越好                   |
| `pose_rmsd_to_reference`    | 与参考配体 pose 的 RMSD | 有共晶配体时使用           |
| `ligand_efficiency`         | 配体效率                | docking 分数按重原子数归一 |

输出标签：

| 标签                      | 中文含义         |
| ------------------------- | ---------------- |
| `docking_strong`          | 对接分数较强     |
| `docking_weak`            | 对接分数较弱     |
| `pose_confident`          | pose 可信        |
| `pose_uncertain`          | pose 不确定      |
| `key_interaction_present` | 关键相互作用存在 |
| `key_interaction_missing` | 缺少关键相互作用 |
| `steric_clash`            | 存在空间冲突     |
| `bad_pose`                | pose 不合理      |
| `good_ligand_efficiency`  | 配体效率较好     |

示例输出：

```json
{
  "molecule_id": "MOL-000123",
  "docking": {
    "vina_score": -8.7,
    "cnn_score": 0.82,
    "key_hbond_count": 1,
    "clash_count": 0,
    "ligand_efficiency": 0.31
  },
  "labels": ["pose_confident", "key_interaction_present", "good_ligand_efficiency"]
}
```

注意：

- docking score 不能单独决定排名。
- `cnn_score` 高但缺少关键相互作用时，仍应标记 `pose_uncertain`。
- 有共晶配体时，必须检查是否复现关键结合模式。

### 9.8 ADMET 定量预测

工具：ADMETlab、Chemprop、DeepChem、项目内 QSAR 模型。

常见输出：

| 字段                     | 中文含义             | 输出形式                 |
| ------------------------ | -------------------- | ------------------------ |
| `solubility`             | 溶解度               | 连续值或 low/medium/high |
| `permeability`           | 膜通透性             | 连续值或分类             |
| `hERG_risk`              | hERG 心脏毒性风险    | 概率 + 风险标签          |
| `Ames_risk`              | Ames 致突变风险      | 概率 + 风险标签          |
| `DILI_risk`              | 药物性肝损伤风险     | 概率 + 风险标签          |
| `CYP3A4_inhibition`      | CYP3A4 抑制风险      | 概率 + 风险标签          |
| `CYP2D6_inhibition`      | CYP2D6 抑制风险      | 概率 + 风险标签          |
| `CYP2C9_inhibition`      | CYP2C9 抑制风险      | 概率 + 风险标签          |
| `Pgp_substrate`          | 是否可能是 P-gp 底物 | 概率 + 标签              |
| `BBB_penetration`        | 是否可能过血脑屏障   | 概率 + 标签              |
| `plasma_protein_binding` | 血浆蛋白结合         | 连续值或分类             |
| `clearance`              | 清除率               | 连续值或分类             |
| `half_life`              | 半衰期               | 连续值或分类             |

统一风险标签：

| 标签            | 中文含义             |
| --------------- | -------------------- |
| `low_risk`      | 低风险               |
| `medium_risk`   | 中等风险             |
| `high_risk`     | 高风险               |
| `unknown_risk`  | 模型证据不足         |
| `admet_clean`   | ADMET 整体较干净     |
| `admet_warning` | 有中等风险，需要扣分 |
| `admet_blocker` | 高风险，原则上淘汰   |

具体风险标签：

| 标签                  | 中文含义      |
| --------------------- | ------------- |
| `hERG_high_risk`      | hERG 高风险   |
| `ames_positive_risk`  | Ames 阳性风险 |
| `dili_high_risk`      | 肝毒性高风险  |
| `cyp_inhibition_risk` | CYP 抑制风险  |
| `poor_solubility`     | 溶解度差      |
| `poor_permeability`   | 通透性差      |
| `pgp_substrate_risk`  | P-gp 底物风险 |
| `bbb_positive`        | 可能进入中枢  |

示例输出：

```json
{
  "molecule_id": "MOL-000123",
  "admet": {
    "hERG_probability": 0.42,
    "hERG_risk": "medium_risk",
    "Ames_probability": 0.12,
    "Ames_risk": "low_risk",
    "CYP3A4_inhibition_probability": 0.28,
    "solubility": "medium",
    "permeability": "medium"
  },
  "admet_risk_score": 38,
  "labels": ["admet_warning", "hERG_medium_risk"]
}
```

### 9.9 合成可及性定量输出

工具：SA Score、SCScore、AiZynthFinder、ASKCOS 可选。

计算项：

| 字段                       | 中文含义         | 推荐        |
| -------------------------- | ---------------- | ----------- |
| `SA_score`                 | 合成可及性分数   | <= 4.5 优先 |
| `SCScore`                  | 合成复杂度分数   | 越低越容易  |
| `route_found`              | 是否找到合成路线 | `true` 优先 |
| `route_steps`              | 预测合成步数     | <= 5 优先   |
| `buyable_building_blocks`  | 可购买砌块数量   | 越多越好    |
| `route_confidence`         | 路线置信度       | 0-1         |
| `hazardous_reaction_count` | 潜在危险反应数量 | 越少越好    |
| `protecting_group_count`   | 保护/脱保护次数  | 越少越好    |

输出标签：

| 标签                       | 中文含义         |
| -------------------------- | ---------------- |
| `easy_to_synthesize`       | 较容易合成       |
| `moderate_synthesis`       | 合成难度中等     |
| `hard_to_synthesize`       | 合成困难         |
| `route_found`              | 找到路线         |
| `route_not_found`          | 未找到路线       |
| `buyable_blocks_available` | 有可买砌块       |
| `too_many_steps`           | 步数过多         |
| `hazardous_route`          | 路线存在危险反应 |

### 9.10 多目标归一化评分

所有不同工具的原始分数不能直接相加，必须归一化到 0-100。

推荐统一输出：

```json
{
  "molecule_id": "MOL-000123",
  "normalized_scores": {
    "physchem_score": 82,
    "similarity_score": 74,
    "docking_score_norm": 81,
    "admet_score": 62,
    "synthesis_score": 76,
    "novelty_score": 68,
    "evidence_confidence": 79,
    "con_score": 42,
    "overall_score": 72.6
  },
  "final_labels": [
    "drug_like",
    "pose_confident",
    "admet_warning",
    "moderate_synthesis",
    "recommended"
  ]
}
```

最终推荐标签：

| 标签                      | 中文含义               | 条件示例                   |
| ------------------------- | ---------------------- | -------------------------- |
| `recommended`             | 推荐进入最终清单       | 综合分高，反驳风险可控     |
| `reserve`                 | 备选                   | 有潜力但证据或某项性质不足 |
| `reject`                  | 淘汰                   | 高风险或多项关键失败       |
| `needs_more_evidence`     | 证据不足               | RAG 或工具结果不足         |
| `optimize_admet_next`     | 下一轮优先优化 ADMET   | ADMET 是主要扣分项         |
| `optimize_synthesis_next` | 下一轮优先优化合成     | 合成可及性是主要扣分项     |
| `optimize_pose_next`      | 下一轮优先优化结合姿势 | docking/pose 是主要扣分项  |

### 9.11 数据库存储建议

定量计算结果建议分表保存：

- `molecule_properties`：RDKit 物化性质。
- `structure_alerts`：PAINS、Brenk、毒性团、反应性基团。
- `similarity_results`：Tanimoto、scaffold、聚类、新颖性。
- `conformer_results`：3D 构象和 strain。
- `docking_results`：docking 分数、pose、相互作用。
- `admet_results`：ADMET 模型输出。
- `synthesis_routes`：合成路线和路线风险。
- `normalized_scores`：归一化后的多目标评分。

每条记录必须保留：

- `tool_name`：工具名称。
- `tool_version`：工具版本。
- `model_name`：如果是机器学习模型，记录模型名。
- `input_hash`：输入分子的 hash。
- `created_at`：计算时间。
- `status`：成功、失败或跳过。

这样以后报告里每一个数字都能追溯来源。

## 10. 技术实现建议

### 9.1 后端服务

推荐 FastAPI。

核心 API：

- `POST /projects`：创建项目。
- `GET /builtin-targets`：查看系统内置靶点列表。
- `GET /builtin-targets/{target_id}`：查看某个靶点的内置药物、PDB、SAR 和证据概览。
- `POST /projects/{id}/chat`：自然语言对话，设置优化方向或询问结果。
- `POST /projects/{id}/files`：上传 PDF、CSV、SDF、PDB 等资料。
- `POST /projects/{id}/ingest`：解析上传资料并导入知识库。
- `POST /projects/{id}/documents`：上传文档，兼容旧接口，建议新实现使用 `/files`。
- `POST /projects/{id}/run`：启动完整流程。
- `POST /projects/{id}/rounds`：按当前约束启动新一轮优化。
- `POST /projects/{id}/advisor/apply`：接受 Advisor 建议并转成下一轮约束。
- `GET /projects/{id}/status`：查看流程状态。
- `GET /projects/{id}/molecules`：查看候选分子。
- `GET /projects/{id}/constraints`：查看当前生效的优化约束。
- `GET /projects/{id}/advice`：查看 Advisor 给出的优化建议。
- `GET /projects/{id}/reasoning-traces`：查看项目级可解释推理轨迹。
- `GET /projects/{id}/molecules/{molecule_id}/decision-cards`：查看单个分子的判断卡片。
- `GET /projects/{id}/report`：下载报告。

对话接口示例：

请求：

```json
{
  "message": "下一轮优先降低 hERG 风险，但保留 quinazoline 母核"
}
```

响应：

```json
{
  "reply": "我会把 hERG 高风险设为扣分项，并把 quinazoline 母核设为保护结构。下一轮生成会降低疏水强碱性侧链的权重。",
  "intent": "set_constraint",
  "created_constraints": ["CONS-0001", "CONS-0002"]
}
```

### 9.2 工作流调度

推荐 Prefect。

每个 Agent 是一个 task，整个智能体流程是一个 flow。

好处：

- 每一步可重试。
- 每一步有日志。
- 可以从失败节点继续。
- 可以批量处理分子。

### 9.3 文件存储

推荐 MinIO。

存：

- PDF 原文
- 解析后的 markdown
- PDB/SDF/MOL2 文件
- docking pose
- CSV 结果
- 最终报告

数据库只存路径，不存大文件。

### 9.4 工具封装

所有工具都封装成统一接口：

```json
{
  "tool_name": "gnina_docking",
  "input": {},
  "output": {},
  "stdout": "...",
  "stderr": "...",
  "exit_code": 0,
  "runtime_seconds": 128
}
```

这样 Agent 不直接依赖命令行细节，只读取标准化结果。

### 9.5 错误处理

常见错误：

- 分子结构非法。
- docking 文件缺失。
- ADMET 工具超时。
- RAG 检索无结果。
- LLM 输出 JSON 格式错误。

处理方式：

- JSON 格式错误：自动重试一次，要求模型修复 JSON。
- 工具超时：记录失败并跳过该分子，不中断全流程。
- RAG 无证据：该结论标为 `hypothesis`，不允许作为强证据。
- docking 失败：分子状态改为 `docking_failed`。

## 11. 最终输出报告结构

最终报告只输出智能体结果，不包含实验计划。

报告结构：

1. 项目摘要
2. 用户自然语言目标和当前优化约束
3. 输入信息和用户上传资料概览
4. 内置靶点-药物库使用情况
5. RAG 证据库概览
6. 靶点与口袋分析
7. 已知配体与 SAR 规则
8. 候选分子生成统计
9. 过滤统计
10. Docking 结果概览
11. ADMET 风险概览
12. 合成可及性概览
13. 自我反驳结果
14. Advisor 下一轮优化建议
15. 可解释推理轨迹总览
16. Top 20-50 候选分子
17. 每个候选分子的证据链和判断卡片
18. 技术附录

单个候选分子展示：

```json
{
  "rank": 1,
  "molecule_id": "MOL-000123",
  "smiles": "CC...",
  "overall_score": 86.2,
  "final_decision": "recommended",
  "why_recommended": [
    "保持已知 hinge binder 相互作用",
    "docking pose 合理",
    "ADMET 未出现高风险信号",
    "合成路线小于 5 步"
  ],
  "main_critiques": [
    "存在中等 hERG 风险，需要后续重点关注"
  ],
  "decision_card": {
    "title": "建议保留，但优先优化 hERG 风险",
    "support": ["docking pose 合理", "保留关键相互作用"],
    "risk": ["hERG 中风险", "预测结果需要实验复核"],
    "next": ["降低 cLogP", "减少强碱性侧链暴露"]
  },
  "evidence_ids": ["EVD-0001", "EVD-0021", "EVD-0044"]
}
```

## 12. MVP 开发里程碑

### M1：基础项目和数据库

周期：1-2 周

交付：

- FastAPI 项目骨架。
- PostgreSQL 表结构。
- MinIO 文件存储。
- AgentRun 日志表。
- 内置靶点-药物库基础表。
- 对话消息表和优化约束表。

### M2：对话、上传和知识导入

周期：2-3 周

交付：

- Conversation Agent。
- `POST /projects/{id}/chat` 对话接口。
- 用户上传文件接口。
- Knowledge Ingestion Agent。
- 内置靶点-药物库导入流程。
- PDF/CSV/SDF/PDB 文件解析状态可追踪。

### M3：RAG 建库和检索

周期：2-3 周

交付：

- PDF/文本导入。
- chunk 切分。
- `text-embedding-v4` 入库。
- BM25 + pgvector 检索。
- `qwen3-rerank` 精排。
- evidence_id 可追踪。

### M4：分子生成和规则过滤

周期：3-4 周

交付：

- seed ligand 输入。
- REINVENT4/CReM 生成。
- RDKit/Datamol 标准化和过滤。
- 分子状态标签完整记录。

### M5：Docking、ADMET、合成

周期：4-6 周

交付：

- GNINA docking pipeline。
- ADMETlab/Chemprop 批量预测。
- AiZynthFinder 路线评估。
- 结果全部写入数据库。

### M6：自我反驳、Advisor 和综合排序

周期：2-3 周

交付：

- DeepSeek Self-Refutation Agent。
- 反证检索。
- Con Score 和 refutation_decision。
- Qwen Ranker 综合排序。
- Advisor Agent。
- Reasoning Trace 结构化判断轨迹。
- Decision Card 用户可见判断卡片。
- 自然语言优化建议和下一轮参数建议。

### M7：报告生成和前端展示

周期：2-3 周

交付：

- Top 20-50 报告。
- 每个分子证据链。
- 每个分子反驳链。
- 每个 Top 分子的判断卡片。
- 对话式结果解释。
- 简单 Web 页面展示结果。

## 13. MVP 验收指标

必须达到：

- 每个 Top 分子都有 `pro_score`、`con_score`、`evidence_confidence`、`overall_score`。

- 每个 Top 分子至少绑定 2 条证据。

- 每条证据都能追溯到文档、页码或数据库来源。

- 所有 Agent 输出都能落库。

- 用户自然语言约束能转成 `optimization_constraints`。

- 用户上传 PDF/CSV/SDF/PDB 至少各支持一种解析流程。

- 内置靶点-药物库能被项目初始化流程调用。

- RAG 检索 Top 10 中相关证据比例大于 70%。

- 最终 Top 50 中 90% 以上通过基础药化规则。

- 所有淘汰分子都有淘汰原因。

- DeepSeek 反驳结果能改变至少一部分候选分子的排名，而不是只做装饰。

- Advisor Agent 能给出至少 3 条可执行的下一轮优化约束。

- 每个 Top 分子都有 `ReasoningTrace`，包含支持因素、反对因素、不确定性和下一步建议。

- 前端或报告中必须展示 `DecisionCard`，用户不需要读原始 JSON 也能判断为什么推荐或淘汰。

- 所有判断卡片都必须能追溯到至少一个数据库记录、工具结果或 RAG 证据；没有证据的判断必须标记为 `hypothesis`。

## 14. 最终项目结构 tree

当前 MVP 为了快速验证，代码可以集中在 `src/medagent` 下。最终迁移到完整系统时，建议演进为下面的结构。每个分支后面的中文标签说明该目录负责什么。

```text
  small-molecule-drug-design-agent/
  ├─ apps/                                  # 所有可运行应用
  │  ├─ api/                                # 后端 API 服务
  │  │  ├─ main.py                          # FastAPI 启动入口
  │  │  ├─ routes/                          # HTTP 路由分组
  │  │  │  ├─ projects.py                    # 项目创建、状态、轮次
  │  │  │  ├─ chat.py                        # 自然语言对话与约束
  │  │  │  ├─ files.py                       # 文件上传、解析、导入
  │  │  │  ├─ targets.py                     # 内置靶点库
  │  │  │  ├─ molecules.py                   # 候选分子查询
  │  │  │  ├─ pipeline.py                    # 启动完整 Agent 流程
  │  │  │  └─ reports.py                     # 报告查看与导出
  │  │  └─ dependencies.py                   # 数据库、权限、配置依赖注入
  │  │
  │  ├─ web/                                # 前端页面
  │  │  ├─ pages/                            # 页面：项目、上传、结果、报告
  │  │  ├─ components/                       # 表格、分子卡片、文件上传器
  │  │  ├─ api-client/                       # 调后端 API 的客户端
  │  │  └─ styles/                           # 主题和样式
  │  │
  │  └─ worker/                             # 后台任务进程
  │     ├─ main.py                           # Worker 启动入口
  │     ├─ queues.py                         # 队列定义
  │     └─ jobs/                             # 长任务：解析、生成、Docking、ADMET
  │
  ├─ packages/                              # 核心业务包
  │  ├─ domain/                              # 领域模型与统一数据结构
  │  │  ├─ project.py                        # ProjectSpec
  │  │  ├─ molecule.py                       # MoleculeRecord
  │  │  ├─ evidence.py                       # EvidenceRecord
  │  │  ├─ agent_run.py                      # AgentRun
  │  │  └─ constraints.py                    # OptimizationConstraint
  │  │
  │  ├─ database/                            # 数据库层
  │  │  ├─ models.py                         # SQLAlchemy ORM 表模型
  │  │  ├─ session.py                        # DB session
  │  │  ├─ migrations/                       # Alembic 迁移
  │  │  └─ repositories/                     # 数据访问封装
  │  │
  │  ├─ storage/                             # 文件存储层
  │  │  ├─ local.py                          # 本地文件存储
  │  │  ├─ minio.py                          # MinIO/S3 存储
  │  │  └─ paths.py                          # 文件路径规范
  │  │
  │  ├─ ingestion/                           # 文件解析与知识导入
  │  │  ├─ parsers/                          # 各类文件解析器
  │  │  │  ├─ pdf.py                         # PDF 文本抽取
  │  │  │  ├─ csv.py                         # 活性表解析
  │  │  │  ├─ sdf.py                         # SDF 分子解析
  │  │  │  ├─ smiles.py                      # SMILES 文件解析
  │  │  │  └─ pdb.py                         # PDB 结构解析
  │  │  ├─ normalizers.py                    # 字段归一化
  │  │  └─ service.py                        # 导入编排
  │  │
  │  ├─ rag/                                 # RAG 系统
  │  │  ├─ chunking.py                       # 文档切分
  │  │  ├─ embedding.py                      # text-embedding-v4
  │  │  ├─ retrieval.py                      # BM25 + pgvector 检索
  │  │  ├─ rerank.py                         # qwen3-rerank
  │  │  └─ evidence.py                       # evidence_id 生成与引用
  │  │
  │  ├─ chemistry/                           # 分子处理
  │  │  ├─ standardize.py                    # SMILES 标准化
  │  │  ├─ descriptors.py                    # MW、LogP、TPSA、HBD、HBA
  │  │  ├─ filters.py                        # PAINS、Brenk、Lipinski
  │  │  ├─ similarity.py                     # Tanimoto、新颖性、多样性
  │  │  ├─ conformers.py                     # 3D 构象生成
  │  │  └─ labels.py                         # 分子标签规则
  │  │
  │  ├─ agents/                              # 智能体实现
  │  │  ├─ conversation_agent.py             # 对话理解
  │  │  ├─ central_host_agent.py             # 中枢编排
  │  │  ├─ knowledge_ingestion_agent.py      # 知识导入
  │  │  ├─ rag_agent.py                      # 文献检索与证据
  │  │  ├─ target_agent.py                   # 靶点/口袋分析
  │  │  ├─ sar_agent.py                      # SAR 分析
  │  │  ├─ generator_agent.py                # 候选分子生成
  │  │  ├─ filter_agent.py                   # 规则过滤
  │  │  ├─ docking_agent.py                  # Docking 调度
  │  │  ├─ admet_agent.py                    # ADMET 调度
  │  │  ├─ synthesis_agent.py                # 合成可及性评估
  │  │  ├─ self_refutation_agent.py          # DeepSeek 反驳
  │  │  ├─ ranker_agent.py                   # 综合排序
  │  │  ├─ advisor_agent.py                  # 下一轮建议
  │  │  ├─ report_agent.py                   # 报告生成
  │  │  └─ reasoning_trace.py                # 可解释推理轨迹和判断卡片生成
  │  │
  │  ├─ llm/                                 # 大模型调用封装
  │  │  ├─ qwen.py                           # qwen3.7-max / plus
  │  │  ├─ deepseek.py                       # deepseek-v4-pro
  │  │  ├─ prompts/                          # prompt 模板
  │  │  └─ json_repair.py                    # JSON 输出修复
  │  │
  │  ├─ tools/                               # 外部科学计算工具适配器
  │  │  ├─ base.py                           # 标准 ToolRunResult
  │  │  ├─ rdkit_tool.py                     # RDKit/Datamol
  │  │  ├─ gnina.py                          # GNINA docking
  │  │  ├─ vina.py                           # AutoDock Vina
  │  │  ├─ admetlab.py                       # ADMETlab
  │  │  ├─ chemprop.py                       # Chemprop
  │  │  └─ aizynthfinder.py                  # 合成路线
  │  │
  │  ├─ pipeline/                            # 主流程编排
  │  │  ├─ graph.py                          # Agent 流程图
  │  │  ├─ tasks.py                          # Prefect/Celery 任务
  │  │  ├─ state.py                          # 流程状态机
  │  │  └─ recovery.py                       # 失败重试和断点续跑
  │  │
  │  ├─ scoring/                             # 综合评分
  │  │  ├─ normalization.py                   # 0-100 归一化
  │  │  ├─ weights.py                        # 多目标权重
  │  │  ├─ penalties.py                      # 风险扣分
  │  │  └─ ranking.py                        # Top 20-50 排序
  │  │
  │  └─ reporting/                           # 报告生成
  │     ├─ markdown.py                       # Markdown 报告
  │     ├─ pdf.py                            # PDF 报告
  │     ├─ tables.py                         # Top 分子表格
  │     ├─ molecule_cards.py                 # 单分子证据卡
  │     └─ decision_cards.py                 # 用户可读判断卡片
  │
  ├─ data/                                   # 项目数据，不放大文件进 git
  │  ├─ seed/                                # 内置靶点-药物种子库
  │  ├─ uploads/                             # 用户上传原始文件
  │  ├─ parsed/                              # 解析后的中间文件
  │  ├─ poses/                               # docking pose 文件
  │  └─ reports/                             # 最终报告
  │
  ├─ database/                               # 数据库快照和初始化资产
  │  ├─ seed.sqlite                          # 轻量种子库
  │  ├─ init.sql                             # PostgreSQL 初始化
  │  └─ backups/                             # 数据库备份
  │
  ├─ infra/                                  # 部署与基础设施
  │  ├─ docker-compose.yml                   # 本地开发环境
  │  ├─ docker/                              # 各服务 Dockerfile
  │  ├─ minio/                               # MinIO 初始化
  │  ├─ postgres/                            # PostgreSQL 扩展配置
  │  └─ prefect/                             # Prefect 工作流配置
  │
  ├─ configs/                                # 配置文件
  │  ├─ models.yaml                          # 模型栈配置
  │  ├─ scoring.yaml                         # 打分权重
  │  ├─ filters.yaml                         # 分子过滤阈值
  │  └─ tools.yaml                           # 外部工具路径和超时
  │
  ├─ tests/                                  # 自动化测试
  │  ├─ unit/                                # 单元测试
  │  ├─ integration/                         # API/数据库/文件解析集成测试
  │  ├─ fixtures/                            # 测试文件样例
  │  └─ e2e/                                 # 端到端流程测试
  │
  ├─ scripts/                                # 运维和数据脚本
  │  ├─ download_pubchem_seed.py             # 下载 PubChem 种子数据
  │  ├─ init_database.py                     # 初始化数据库
  │  ├─ run_demo_project.py                  # 跑演示项目
  │  └─ export_report.py                     # 导出报告
  │
  ├─ docs/                                   # 人类阅读文档
  │  ├─ architecture.md                      # 架构说明
  │  ├─ api.md                               # API 说明
  │  ├─ database.md                          # 数据库表说明
  │  ├─ deployment.md                        # 部署说明
  │  ├─ workflow.md                          # Agent 流程说明
  │  └─ migration.md                         # 迁移文档
  │
  ├─ .env.example                            # 环境变量模板
  ├─ pyproject.toml                          # Python 项目配置
  ├─ package.json                            # 如果前端独立构建，则放这里
  └─ README.md                               # 项目总入口
```

最终结构的核心分层：

- `apps/`：真正启动的应用，包括后端 API、前端页面和后台 worker。
- `packages/domain/`：统一领域对象，保证 Agent、API、数据库和报告说同一种语言。
- `packages/database/`：关系数据库模型、迁移和 repository。
- `packages/storage/`：本地、MinIO 或 S3 文件存储适配。
- `packages/ingestion/`：PDF、CSV、SDF、SMILES、PDB 等文件解析和字段归一化。
- `packages/rag/`：RAG 文档切分、向量化、检索、重排序和 evidence_id 管理。
- `packages/chemistry/`：RDKit/Datamol 分子标准化、性质计算、过滤、相似性和构象处理。
- `packages/agents/`：所有智能体，包括中枢编排、生成、过滤、反驳、排序、建议、报告和推理轨迹。
- `packages/llm/`：Qwen、DeepSeek 等模型调用封装，避免业务代码直接写供应商 API。
- `packages/tools/`：GNINA、Vina、ADMETlab、Chemprop、AiZynthFinder 等外部工具适配器。
- `packages/pipeline/`：Agent 流程图、任务调度、状态机、失败重试和断点续跑。
- `packages/scoring/`：多目标归一化、权重、风险扣分和 Top 20-50 排名。
- `packages/reporting/`：Markdown/PDF 报告、分子卡片、判断卡片和表格输出。
- `data/`：运行时数据，不建议提交大文件进 git。
- `database/`：数据库快照、初始化 SQL 和备份。
- `infra/`：Docker、MinIO、PostgreSQL、Prefect 等部署资产。
- `configs/`：模型栈、评分权重、过滤阈值、工具路径和超时配置。
- `tests/`：单元、集成和端到端测试。
- `scripts/`：数据下载、数据库初始化、演示项目和报告导出脚本。
- `docs/`：架构、API、数据库、部署、流程和迁移文档。
