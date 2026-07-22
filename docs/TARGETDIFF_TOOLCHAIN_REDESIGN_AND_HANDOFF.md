# 小分子药物设计 Agent：TargetDiff 与全工具链改造计划

更新时间：2026-07-22  
状态：设计与交接文档，尚未按本文实施业务代码和数据库改造

## 1. 项目介绍

本项目是一个面向小分子药物设计的可追溯多 Agent 工作台。用户选择内置靶点或上传自定义靶点、受体、口袋、配体和文献，通过手动条件或自然语言描述设计目标。中枢 LLM 根据可用数据、轮次历史、工具状态和用户要求制定每轮生成与评估策略，但每个重要决定都必须允许用户检查和修改。

核心业务循环是：

```text
项目与靶点
-> 靶点资料、受体口袋和 seed 准备
-> 中枢 LLM 生成轮次策略草稿
-> 用户确认或用自然语言修改
-> 多种方法生成候选分子
-> 结构、性质、ADMET、对接和合成评估
-> 共识排名与中文报告
-> 用户选择或 Agent 建议下一轮 seed
-> 创建下一轮草稿
```

项目不是自动给出“真实活性结论”的系统。生成模型、对接分数、ADMET 和逆合成结果都属于计算预测，必须在中文报告中与论文证据、实验数据和人工判断明确区分。

## 2. 本次改造的目标

1. 使用 TargetDiff 替换 REINVENT4，面向“少量 seed 或无 seed，但有可靠蛋白口袋”的场景进行三维口袋条件生成。
2. 保留 CReM 负责 seed 周围局部结构优化，保留 AutoGrow4 负责受体引导的遗传式优化。
3. 将对接流程改为固定的“Vina 全量初筛 + GNINA GPU 精筛”，不再把两者作为互相替代的 fallback。
4. 删除不再使用的 REINVENT4、DiffDock 执行链路和会伪装成真实结果的静默 surrogate。
5. 让每个保留的核心化学工具同时满足运行时、模型/数据库、靶点资源和真实验收要求。
6. 为全部内置靶点建立共享的 target-level 科学资源包，新项目创建后直接引用，不要求用户重复上传。
7. 记录每轮、每个生成方法、每个工具运行、每个 pose、每项分数、原始文件和来源证据。
8. 不删除已有分子数据库、历史轮次、历史 REINVENT4 分子或历史 DiffDock 记录。

## 3. 已确认的关键决策

### 3.1 新的生成工具组合

| 工具 | 主要输入 | 业务角色 | 是否需要口袋 | 是否需要 seed |
|---|---|---|---|---|
| CReM | 一个或多个 seed、片段替换数据库 | 局部 SAR 优化 | 否 | 是 |
| TargetDiff | 清洗后的蛋白口袋、checkpoint | 口袋条件 de novo 三维生成 | 是 | 否 |
| AutoGrow4 | 受体、网格、来源分子池 | 遗传生长、交叉和后续优化 | 是 | 是或需要来源池 |

REINVENT4 的预训练 prior 可以在少 seed 时采样，但它不直接理解蛋白口袋；少量 seed 也不足以支撑可靠的靶点特异性迁移学习。因此 TargetDiff 更符合当前项目定位。

TargetDiff 输出的三维构象是 `generation_pose`，只能视为生成假设。它必须经过键级重建、RDKit 校验、去重和独立对接，不能直接作为结合证据，也不能覆盖 Vina/GNINA pose。

### 3.2 新的对接工具组合

AutoDock Vina 是广泛使用、可复现的标准基线。GNINA 源自 smina/Vina 体系，增加 CNN pose score、CNN affinity 和 GPU 加速，但运行 GNINA 不等于运行独立的 AutoDock Vina。

新流程固定为：

```text
Vina：所有正式对接候选的标准初筛和基线 pose
GNINA：精筛候选的 Vina-pose 重评分 + 独立重新对接/优化
```

Vina 和 GNINA 都是预期执行阶段，不再把 Vina 仅作为 GNINA 失败后的 CPU fallback。

### 3.3 “所有工具可用”的定义

仅检测到 Python 包、CLI 或 Docker 镜像，不得再显示为“工具可用”。工具状态必须拆为：

- `runtime_available`：包、CLI 或镜像可以真实启动。
- `model_data_ready`：checkpoint、片段库、策略模型或 stock 数据存在并通过哈希校验。
- `target_data_ready`：当前靶点具备该工具需要的受体、口袋、网格或来源池。
- `smoke_test_passed`：用固定小样本执行过真实计算并生成可解析结果。
- `ready`：以上必要条件全部满足。

中枢 LLM 只能调度 `ready=true` 的工具，不能用 surrogate 补足数量后声称工具已执行。

## 4. 核心工具范围与数据依赖

| 工具 | 保留状态 | 所需全局数据 | 所需靶点/项目数据 | 验收产物 |
|---|---|---|---|---|
| RDKit | 核心保留 | Python 包、结构警报规则 | SMILES/SDF | 标准化结构、描述符、告警 |
| Datamol | 内部依赖 | Python 包 | 分子结构 | 标准化结果 |
| CReM | 核心保留 | `chembl22_sa2.db` 片段数据库 | seed | 真实 CReM 候选和 provenance |
| TargetDiff | 新增核心 | 固定版本镜像、checkpoint、CUDA 运行时 | 清洗受体、pocket-only PDB、口袋坐标 | 原始原子坐标、重建 SDF、有效性指标 |
| AutoGrow4 | 核心保留 | 固定版本镜像、操作片段/依赖 | 受体、网格、来源分子池 | 真实 AutoGrow4 候选和父代关系 |
| AutoDock Vina | 核心保留 | 固定版本镜像/CLI | 受体 PDBQT、配体 PDBQT、网格 | 多个 Vina pose 和 affinity |
| GNINA | 核心保留 | 固定镜像摘要、内置 CNN 模型、CUDA | 清洗受体、配体 SDF、同一网格 | CNN 重评分、GNINA pose、CNN affinity |
| ADMET-AI | 核心保留 | 固定版本模型权重并预缓存 | SMILES | 可解析的 ADMET 预测 |
| AiZynthFinder | 核心保留 | policy/filter/ringbreaker 模型、模板、stock、config | SMILES | 路线树、步骤、stock 命中 |
| Open Babel/Meeko | 内部准备依赖 | 固定版本运行时 | PDB/SDF/SMILES | 合法 PDBQT 和格式转换证据 |
| Chemprop CLI | 可选扩展 | 用户或项目明确指定的 checkpoint | SMILES | checkpoint 对应的预测 |

Chemprop CLI 没有 checkpoint 时不是一个可用的预测工具。核心 ADMET 使用已验证的 ADMET-AI；Chemprop 只在 checkpoint 配置完成时显示为可选扩展。

## 5. 需要删除或停止执行的旧工具

### 5.1 REINVENT4

删除新运行能力：

- `src/medagent/agents/reinvent4_agent.py`
- `src/medagent/services/reinvent4_adapter.py`
- `docker/reinvent4/`
- `docker-compose.yml` 中的 REINVENT4 服务、环境变量和 volume
- `configs/tools.yaml`、`.env.example`、构建脚本和状态接口中的 REINVENT4 配置
- 策略 schema、LLM prompt、validator 和 orchestrator 中的新 REINVENT4 调度入口

保留历史兼容：

- 数据库中 `CampaignRun.method=reinvent4` 的旧记录。
- 旧分子的 `generation_method/source_agent/provenance`。
- 报告和前端只读层的 legacy 标签映射。
- 旧运行原始日志和 artifact，除非用户另行要求清理。

只有 TargetDiff BRAF 真实验收通过后，才清理本机 `.local/models/reinvent4/`，避免在替换尚未成功时丢失现有运行能力。

### 5.2 DiffDock

DiffDock 已不属于目标工作流，应删除：

- `docker/diffdock/` 和 compose 服务。
- `docking_adapters.py` 中的 DiffDock 命令、探测、解析和运行函数。
- 配置、环境变量、脚本、API 状态和默认工具清单中的 DiffDock。
- 候选评估、排名、报告和测试中的新 DiffDock 路径。

历史 `diffdock_confidence` 字段先保留为只读 nullable 兼容字段，不再写入；确认历史报告迁移完成后，再决定是否在后续大版本删除列。

### 5.3 surrogate 与静默 fallback

删除或禁用以下行为：

- CReM 数量不足时用 RDKit 片段拼接冒充 CReM 候选。
- 外部对接失败时写入 `rdkit_surrogate_docking` 并参与正式排名。
- ADMET-AI 或 AiZynthFinder 失败时用简单规则结果冒充对应外部模型。
- 任一工具失败后将 surrogate 分数当作真实工具证据。

允许的行为是明确返回 `failed/skipped/not_ready`，保留错误和重试建议。RDKit 规则仍可作为独立的低层级规则证据，但名称、分数和报告必须与外部工具分开。

## 6. 内置靶点科学资源包

当前内置库约有 50 个靶点和已知药物。已有的 `BindingSite` 多数只有 PDB ID、RCSB 页面 URL、网格和关键残基，缺少可直接计算的本地受体 artifact。

每个可计算 binding site 应包含：

```text
原始 RCSB mmCIF/PDB
原始结构元数据和 primary citation
选定的蛋白链、构象、突变和物种
共结晶配体的晶体坐标 SDF
清洗后的完整受体 PDB
Vina 受体 PDBQT
参考配体 PDBQT
TargetDiff pocket-only PDB
口袋原子/残基列表
grid center、grid size、计算方法
关键残基和与参考配体的接触
质子化、缺失残基、金属、辅因子和结构水处理记录
每个文件的 SHA-256、大小、格式、来源 URL 和许可证说明
Vina/GNINA 共结晶配体 redocking 结果
```

### 6.1 存储原则

“写入内置数据库”采用 target-level 共享资源，而不是为每个项目复制：

- `project_id=NULL`、`target_id=<内置靶点>`、`scope=builtin`。
- 新项目选择内置靶点时直接链接 target-level resources。
- 小型元数据、网格、残基和 provenance 存 PostgreSQL/SQLite。
- 受体坐标和参考配体存版本化 artifact 存储，数据库保存不可变 URI 和 SHA-256。
- TargetDiff checkpoint、ADMET-AI 模型和 AiZynthFinder 模型不作为数据库大 BLOB 保存；它们进入全局 tool data package，并由数据库登记版本和哈希。
- 可移植的 seed SQLite 保存资源 manifest；完整部署通过同步脚本验证并补齐 artifact。

### 6.2 数据状态

每个 binding site 使用以下状态：

- `discovered`：已找到候选 PDB。
- `downloaded`：原始文件和来源元数据已归档。
- `prepared`：受体、配体、口袋和 PDBQT 已生成。
- `calibrated`：共结晶配体 redocking 已通过。
- `ready`：TargetDiff、AutoGrow4、Vina 和 GNINA 所需资源完整。
- `needs_curation`：链、辅因子、共价配体、缺失区域或口袋定义需要人工判断。
- `unsupported`：没有可靠结构或当前工作流不适用。

不能为了让状态变绿而为缺少可靠结构的靶点伪造口袋。当前 `TGT-ACC` 等缺少明确 PDB 的条目必须保持 `needs_curation`，直到找到并验证可用结构。

## 7. 数据获取和准备流程

### 7.1 来源

优先使用可审计的一手来源：

- RCSB PDB Data API 与坐标下载：结构、实验方法、分辨率、链、配体和 primary citation。
- UniProt REST：蛋白名称、物种、序列、突变和 accession 校验。
- RCSB Chemical Component Dictionary/PubChem PUG REST：参考配体标识和结构交叉校验。
- ChEMBL API：靶点配体、活性类型、单位和 pChEMBL，保留 assay 与文献来源。
- PubMed/Crossref：PDB primary citation 和关键实验论文。
- 各工具官方 release：TargetDiff checkpoint、AiZynthFinder 模型、ADMET-AI 模型和容器版本。

所有下载必须写 manifest：`source_url`、`retrieved_at`、`upstream_version`、`license_note`、`sha256`、`content_length`。禁止将网页 URL 直接当作 `receptor_file`。

### 7.2 自动选择结构

对每个内置靶点：

1. 校验 PDB entry 的 UniProt、物种、突变和蛋白链是否符合目标。
2. 优先选择含共结晶小分子、分辨率较高、口袋完整且生物学状态明确的结构。
3. 记录结构是 wild type、突变体、active/inactive、type I/type II 构象或变构口袋。
4. 抽取共结晶配体晶体坐标，不使用理想 CCD 坐标代替 redocking 参考 pose。
5. 根据参考配体定义口袋和 docking box，并保存具体算法和 padding。
6. 对多结构靶点允许建立多个 binding site profile，而不是覆盖成一个口袋。

### 7.3 受体准备

准备流程必须可复现并保存每一步：

1. 固定 chain、altloc、突变和保留的辅因子。
2. 删除无关蛋白链、结晶添加物和非必要溶剂。
3. 保留或删除结构水必须有逐水分子规则和记录。
4. 修复可安全修复的缺失侧链/原子；大段缺失不得自动编造。
5. 按固定 pH 策略添加氢并记录质子化工具和版本。
6. 生成 GNINA/TargetDiff/AutoGrow4 共用的 canonical prepared receptor PDB。
7. 从同一 canonical receptor 派生 Vina PDBQT。
8. 从同一 reference ligand 派生 SDF 和 PDBQT，避免格式转换改变键级或立体化学。
9. 计算并保存 pocket-only PDB、残基列表、网格和接触证据。

金属配位、共价配体、GPCR、离子通道和明显 induced-fit 结构进入人工复核。KRAS G12C、共价 EGFR/BTK 等当前只能标记为非共价近似，不得把普通 Vina/GNINA 结果写成共价对接证据。

### 7.4 口袋校准

每个口袋在标记 `calibrated` 前必须：

1. 移除共结晶配体。
2. 用独立准备的参考配体分别运行 Vina 和 GNINA。
3. 对预测 pose 与晶体 pose 做对称性修正后的重原子 RMSD。
4. 检查关键残基、氢键、碰撞和配体是否仍位于目标亚口袋。
5. 默认以 RMSD 小于或等于 2 Å 作为成功参考，但最终阈值允许按配体对称性和口袋类型人工复核。
6. 保存失败结果；校准失败的口袋不能进入自动生产工作流。

## 8. 全局工具数据包

新增 `ToolDataPackage` 概念，登记与具体项目无关的大型模型和数据库：

| package | 当前状态 | 改造动作 |
|---|---|---|
| CReM ChEMBL22 SA2 DB | `database/chembl22_sa2.db` 已存在 | 校验 schema、版本、许可和 SHA-256，登记为内置 package |
| TargetDiff checkpoint | 尚未接入 | 从官方 release 获取，固定 commit/checkpoint/CUDA，登记哈希 |
| GNINA CNN models | 镜像内置 | 固定镜像 digest 和默认 model 名称，运行时报告实际 model |
| ADMET-AI models | Python 包模型 | 在镜像构建或初始化阶段预缓存，禁止生产首次运行临时联网下载 |
| AiZynthFinder models | `data/aizynthfinder/` 已存在 | 校验 config 中所有路径、ONNX 模型、模板和 ZINC stock 哈希 |
| AutoGrow4 resources | 镜像与运行资源 | 固定源码 commit，验证操作库并登记；来源分子池仍按项目生成 |

新增启动期 `tool data audit`，任何文件缺失、空文件、哈希变化或版本不匹配都使对应工具 `ready=false`。

## 9. 数据库改造

### 9.1 科学资源和工具数据

新增或扩展：

#### `scientific_artifacts`

- `artifact_id`
- `kind`：receptor_raw、receptor_prepared、receptor_pdbqt、pocket_pdb、reference_ligand_sdf、pose 等
- `storage_uri`
- `sha256`、`size_bytes`、`media_type`、`file_format`
- `source_url`、`source_version`、`retrieved_at`、`license_note`
- `preparation_pipeline`、`preparation_version`、`metadata_json`

#### `target_resource_links`

- `target_id`、`binding_site_id`、`artifact_id`
- `role`、`scope`、`is_default`
- `compatibility_json`：TargetDiff/Vina/GNINA/AutoGrow4 可用性

#### `tool_data_packages`

- `package_id`、`tool_name`、`package_role`
- `version`、`storage_uri`、`sha256`
- `runtime_constraints_json`
- `verification_status`、`verified_at`、`verification_json`

### 9.2 TargetDiff 生成证据

新增 `generation_artifacts` 或等价结构，保存：

- campaign、样本序号、随机种子、checkpoint 和 pocket hash。
- 原始原子类型与三维坐标 artifact。
- 键级重建工具与结果。
- canonical SMILES、重建 SDF、generation pose。
- sanitize、价态、连通性、重复、几何合理性和失败原因。
- `source_agent=targetdiff` 和 `generation_method=targetdiff`。

失败样本不写入正式 `molecules`，但必须进入 campaign metrics，避免只报告成功结果造成偏差。

### 9.3 Vina/GNINA 独立结果

当前 `DockingResult` 对每个“molecule + round”唯一，只能保存一个 pose，且将 GNINA affinity 写进 `vina_score`。应拆分为：

#### `docking_runs`

- 工具、版本、镜像 digest、CPU/GPU、参数和完整命令。
- receptor artifact、binding site、grid、输入准备版本。
- 状态、日志、开始/结束时间和失败原因。

#### `docking_poses`

- run、molecule、engine、pose rank 和 pose artifact。
- `search_affinity`、`cnn_pose_score`、`cnn_affinity`、score function。
- 是否由 Vina 搜索、GNINA rescore、GNINA refinement 或 GNINA redocking 产生。

#### `pose_interactions`

- pose、interaction type、蛋白残基、配体原子、距离和角度。
- clash、氢键、疏水接触、盐桥及关键残基标记。

#### `docking_consensus`

- molecule、round、Vina pose、GNINA pose。
- 两个 pose 的 RMSD、共享关键接触、分数百分位和分歧等级。
- 共识状态：high_confidence、supported、discordant、insufficient_evidence。

旧 `DockingResult` 先作为兼容摘要读取层；新代码不再依赖一个 `vina_score` 和一个 `pose_file` 表达全部对接证据。

### 9.4 迁移约束

- 只做增量 migration，不重建或清空分子表。
- 对历史工具来源能从 `raw_output/labels/tool_run_id` 确认的记录进行保守回填。
- 无法确定是 Vina 还是 GNINA 的旧分数标记 `legacy_engine_unknown`，不能猜测。
- 所有历史 REINVENT4 和 DiffDock provenance 保持可读。
- migration 提供 dry-run、计数对账和回滚脚本。

## 10. TargetDiff 接入设计

### 10.1 运行时隔离

TargetDiff 依赖较旧且复杂的 PyTorch/PyG/CUDA 组合，应使用独立 Docker 镜像，不能污染 API 主环境。镜像固定：

- TargetDiff 源码 commit/tag。
- Python、PyTorch、PyG、CUDA 和 Open Babel/RDKit 版本。
- checkpoint 路径和 SHA-256。
- 非 root 运行用户、只读输入 mount、独立输出目录和超时。

### 10.2 生成接口

现有接口只传 `seeds + requested_count + constraints`，不足以表达口袋。改为统一 `GenerationRequest`：

- project、round、campaign。
- requested raw samples 和 requested accepted molecules。
- seed molecules/IDs，可为空。
- receptor、binding site 和 resource bundle。
- random seed、计算预算和方法特定参数。
- 用户约束和中枢 LLM rationale。

每个生成 adapter 返回统一 `GenerationBatch`，包括 accepted、rejected、failed、artifacts、metrics、warnings 和完整 provenance。

### 10.3 TargetDiff 输出流水线

```text
检查 GPU、checkpoint 和 pocket
-> 原始 3D 原子采样
-> 键级与分子连通性重建
-> RDKit sanitize/价态/立体化学检查
-> 标准化与去盐
-> canonical SMILES/SDF 去重
-> generation pose 几何检查
-> 描述符、规则和多样性统计
-> 持久化正式分子和失败统计
```

中枢 LLM 决定目标“有效候选数”，adapter 可以在受控 retry budget 内多采样，但必须同时报告 raw count、valid count、unique count 和 accepted count，不能只报告最终成功数。

## 11. 新的 Vina + GNINA 工作流

### 11.1 前置校验

- receptor 与 binding site 必须 `ready`。
- 所有候选必须通过 RDKit、立体化学和基础理化过滤。
- Vina 与 GNINA 使用同一 canonical receptor、生物学构象、质子化方案和 grid。
- PDBQT/SDF 是从同一 receptor/ligand artifact 派生，防止格式导致不可比。

### 11.2 Vina 初筛

- 对所有可能进入正式排名的候选运行真实 Vina。
- 初始建议 `exhaustiveness=8/16`，每个分子保留多个 mode。
- 保存全部 pose、affinity、运行参数和原始输出。
- CPU 并行受限于资源队列，不与 GNINA GPU 作业争抢准备目录。

### 11.3 精筛候选选择

不能只取 Vina 全局 Top N。选择集由以下部分组成：

- Vina 全局高分。
- CReM、TargetDiff、AutoGrow4 各方法内 Top。
- 结构聚类代表分子。
- ADMET/性质较优分子。
- 用户手动指定分子。

选择算法和配额进入 round strategy snapshot，用户可通过自然语言修改。

### 11.4 GNINA 两阶段精筛

1. 对 Vina 保留的多个 pose 做 GNINA CNN rescore，回答“Vina pose 是否被 CNN 支持”。
2. 对更小的 Top K 做 GNINA 独立 redocking/refinement，生成单独的 GNINA best pose。

两种 pose 都保存。计算对称性修正后的 RMSD、共享关键残基接触、氢键和碰撞。

### 11.5 共识排名

不直接平均原始分数。先在同一轮中转换为百分位或稳健标准化排名：

- Vina affinity：越低越好。
- GNINA CNNscore：越高越好。
- GNINA CNNaffinity：越高越好。
- 几何相互作用质量：明确规则评分。

初始对接共识权重可以从 `35% Vina rank + 35% GNINA affinity rank + 20% CNN pose rank + 10% geometry` 开始，但必须配置化并做基准校准。对接共识只是总排名的一个子分数，不能覆盖 ADMET、合成和实验证据。

### 11.6 分歧处理

- Vina 与 GNINA 都好且 pose 接近：高置信计算候选。
- 两者分数好但 pose 差异大：构象不确定。
- Vina 好、GNINA 差或相反：评分模型分歧。
- 只有 Vina 成功：保留基线，但不能进入高置信 Top。
- Vina 失败：检查准备和重试；不能用 GNINA 结果伪装成 Vina 已执行。

## 12. 中枢 LLM 的新工作流

中枢 LLM 输入应包括：

- seed、已知靶点配体和活性数据数量。
- 口袋准备、校准和工具兼容状态。
- 每个工具的 `ready` 状态和本轮计算预算。
- 上轮每种生成方法的 valid/unique/pass/Top 命中率。
- 上轮结构多样性、评分分布、失败原因和不确定性。
- 用户自然语言要求和手动覆盖。

LLM 输出策略草稿：

- 每个生成方法是否启用及目标有效候选数。
- CReM seed 分配、TargetDiff pocket、AutoGrow4 来源池。
- Vina 初筛数量、每方法保留配额、GNINA rescore/redock 数量。
- 约束、理由、风险和依赖检查。
- 下一轮 seed 建议及其证据。

确定性 validator 必须覆盖 LLM：

- 无 seed 时禁用 CReM。
- 无 ready pocket 时禁用 TargetDiff/AutoGrow4/Vina/GNINA。
- AutoGrow4 来源池不足时禁用或降低规模。
- 工具或模型不 ready 时禁用对应方法。
- 数量、超时、GPU 内存和磁盘使用受硬限制。
- 每次执行前要求用户确认策略快照。

建议轮次角色：

- 第一轮少 seed、有可靠口袋：TargetDiff 主探索，CReM 局部探索；AutoGrow4 仅在来源池充分时启用。
- 后续轮次：CReM 优化 Top、AutoGrow4 扩展、TargetDiff 补充新骨架。
- 连续两轮新颖性下降：增加 TargetDiff 探索比例。
- TargetDiff 有效性或唯一性下降：降低预算并分析 pocket/checkpoint/采样失败。

## 13. 逐文件修改地图

### 13.1 新增文件

- `src/medagent/agents/targetdiff_agent.py`：TargetDiff Agent。
- `src/medagent/services/targetdiff_adapter.py`：运行时、命令、输出解析和 provenance。
- `src/medagent/services/targetdiff_resources.py`：口袋资源解析和输入 bundle。
- `src/medagent/services/scientific_artifacts.py`：artifact 登记、哈希和读取。
- `src/medagent/services/tool_data_registry.py`：全局模型/数据库审计。
- `src/medagent/services/docking_consensus.py`：Vina/GNINA 共识和分歧。
- `src/medagent/data/target_resource_manifest.json`：内置靶点资源 manifest。
- `scripts/sync_builtin_target_resources.py`：下载、校验、准备和登记。
- `scripts/audit_tool_data.py`：全局工具数据审计。
- `docker/targetdiff/Dockerfile`：固定版本 GPU 镜像。
- 数据库 migration：scientific artifacts、tool packages、docking runs/poses/consensus、generation artifacts。

### 13.2 生成和策略

- `src/medagent/domain/schemas.py`：`AgentName`、TargetDiff config、统一 generation request/result、双阶段 docking config。
- `src/medagent/agents/generation_base.py`：从 seed-only interface 改为 resource-aware interface。
- `src/medagent/services/molecule_generation.py`：注册 TargetDiff，移除 REINVENT4 和 CReM surrogate fill。
- `src/medagent/agents/round_strategy.py`：上下文加入 pocket/tool readiness 和方法历史指标，替换 REINVENT4 schema/prompt。
- `src/medagent/services/strategy_validator.py`：增加 TargetDiff 和双阶段对接硬校验。
- `src/medagent/pipeline/round_orchestrator.py`：执行 CReM/TargetDiff/AutoGrow4，随后 Vina/GNINA 漏斗。
- `src/medagent/api/rounds_router.py`：新策略请求、状态和 campaign 输出。
- `src/medagent/llm/client.py`：删除 REINVENT4 默认 JSON，加入 TargetDiff 与对接漏斗示例。

### 13.3 靶点资源和数据库

- `src/medagent/db/models.py`：新增 artifact、tool data、docking run/pose/consensus 和 generation artifact 模型。
- `src/medagent/services/bootstrap.py`：从 manifest 幂等 seed target-level resources，不再把 RCSB 网页 URL 写成 receptor file。
- `src/medagent/services/database.py`：运行 migration/audit、数据库摘要增加资源 readiness。
- `src/medagent/data/builtin_targets.py`：关联资源 manifest。
- `src/medagent/data/target_metadata.py`：逐步替换手写且未验证的 URL/网格为生成的、带来源的 manifest。
- `src/medagent/services/receptor_preparation.py`：生成 canonical receptor、PDBQT、reference ligand 和 pocket artifact。
- `src/medagent/services/autogrow4_resources.py`：统一消费 target-level resource bundle。
- `src/medagent/api/resources_router.py`：返回 readiness、来源、hash 和兼容工具。

### 13.4 对接、评估、排名和报告

- `src/medagent/services/docking_adapters.py`：删除 DiffDock；Vina/GNINA 分成明确的 run/rescore/redock interface。
- `src/medagent/services/docking_workflow.py`：统一输入准备，保存多 pose，不再只选第一个可用工具。
- `src/medagent/services/candidate_assessment.py`：Vina 全量后 GNINA 精筛；删除 docking surrogate。
- `src/medagent/services/candidate_ranking.py`：消费 consensus percentile 和 evidence tier。
- `src/medagent/services/pose_interactions.py`：按 pose 保存几何证据。
- `src/medagent/services/decision_cards.py`、`self_refutation.py`、`llm_critique.py`：加入引擎分歧和口袋校准风险。
- `src/medagent/reporting/round_report.py`、`project_report.py`：中文展示两个引擎、两个 pose、论文来源和计算不确定性。
- `src/medagent/api/app.py`、`api/tools_router.py`：新数据合同和真实 readiness 状态。

### 13.5 ADMET 与合成

- `src/medagent/services/admet_adapter.py`：将核心状态命名为 ADMET-AI；Chemprop 无 checkpoint 时只显示 extension-not-configured；删除 surrogate 冒充。
- `src/medagent/services/synthesis_workflow.py`：AiZynthFinder 失败时不写 surrogate route。
- `src/medagent/services/aizynthfinder_adapter.py`：完整校验 config 引用的模型、模板和 stock，记录实际 ONNX provider。

### 13.6 配置、容器和脚本

- `configs/tools.yaml`：删除 REINVENT4/DiffDock，新增 TargetDiff、tool data packages 和双阶段 docking 参数。
- `docker-compose.yml`：删除旧服务，新增 TargetDiff GPU 服务，固定 retained tool volumes。
- `.env.example`：删除旧模型变量，增加 TargetDiff checkpoint 和 artifact root。
- `src/medagent/core/config.py`：同步环境设置。
- `scripts/build_docker_tools.ps1`、`scripts/check_tools.py`、`scripts/manage_docker_tools.py`、`check_docker_tools.bat`：更新工具列表和真实 smoke test。
- `README.md`：更新项目介绍、工具矩阵、数据同步和运行说明，并修复当前中文编码显示问题。

### 13.7 前端（后端稳定后）

- `apps/web/src/types/workbench.ts`：TargetDiff、readiness、multi-pose 和 consensus 类型。
- `StrategyPage.tsx`：三种生成方法和 Vina/GNINA 漏斗参数。
- `ProjectDataPage.tsx`、`ProjectOverviewPage.tsx`：靶点资源和工具 readiness。
- `MoleculeDetailPage.tsx`、`PoseViewer.tsx`：Vina/GNINA pose 切换、RMSD、相互作用和论文引用。
- `RankingPage.tsx`、`RoundReportPage.tsx`：共识、分歧和证据层级。
- `apps/web/src/lib/format.ts`：TargetDiff 与 legacy REINVENT4 标签。

## 14. 实施顺序和提交边界

### 阶段 0：保护现状

- 保存当前 dirty worktree 清单并确认用户改动。
- 运行当前轻量测试，记录基线失败，不回退已有修改。
- 备份数据库 schema 和数据计数，不删除分子表。

### 阶段 1：TargetDiff 可行性试验

- 构建独立镜像、获取官方 checkpoint、验证 GPU。
- 使用 BRAF 3OG7 pocket 生成 10 至 20 个原始样本。
- 验证输出解析、键重建、有效分子、唯一分子和 artifact。
- 此阶段未通过，不进入大范围 REINVENT4 删除。

### 阶段 2：资源与数据库基础

- 加 scientific artifacts、tool data packages 和 target resource links。
- 编写幂等数据同步和 audit。
- 先完整准备并校准 BRAF，再扩展内置靶点。

### 阶段 3：生成接口和 TargetDiff 正式接入

- 改统一 generation interface。
- 加 TargetDiff Agent/adapter/resource bundle。
- 修改 orchestrator、strategy、validator、API 和报告 provenance。
- 停止新的 REINVENT4 运行，保留历史读取。

### 阶段 4：Vina/GNINA 双阶段对接

- 新建 docking run/pose/interaction/consensus。
- 先 Vina 全量，再 GNINA rescore/redock。
- 修改评估、排名、报告和 API。
- 删除 DiffDock 新执行路径和 docking surrogate。

### 阶段 5：其余核心工具全部 ready

- CReM DB 审计并禁止 surrogate fill。
- AutoGrow4 来源池和真实产物验收。
- ADMET-AI 模型预缓存和真实预测验收。
- AiZynthFinder 模型、模板、stock 和 GPU/CPU provider 验收。
- Open Babel/Meeko 输入准备验收。

### 阶段 6：内置靶点批量资源化

- 按 target manifest 下载、准备、校准和登记。
- 第一批：BRAF、EGFR、ALK 等已有明确共结晶口袋的靶点。
- 第二批：其余结构清晰的激酶、酶和受体。
- 第三批：多靶点条目、无可靠结构、共价/金属/膜蛋白等需人工复核条目。
- 输出 ready/needs_curation/unsupported 清单，不能伪造 100% 覆盖。

### 阶段 7：删除旧运行时并更新前端

- TargetDiff 和新 docking workflow 验收后删除 REINVENT4/DiffDock 镜像构建文件和本地旧模型。
- 保留历史数据库可读。
- 更新前端和中文报告。

### 阶段 8：全量测试与发布验收

- 轻量单元测试和 migration 测试。
- Docker 工具逐个真实 smoke test。
- BRAF 三轮小规模端到端。
- 全量 Python、前端、API、E2E 和报告测试。

建议每个阶段独立提交，避免把数据库、模型接入、对接重构和前端混成一次不可审查的大提交。

## 15. 测试和验收标准

### 15.1 通用工具验收

每个核心工具必须证明：

- 探测不是只看文件或镜像存在，而是真实启动。
- 所需模型/数据库 hash 与 manifest 一致。
- 固定小输入能在超时内产生真实输出。
- 输出可解析、可持久化并关联到 tool run。
- provenance 包含工具版本、模型版本、参数、硬件和原始 artifact。
- 失败不会被 surrogate 掩盖。

### 15.2 TargetDiff

- BRAF pocket 可执行真实 GPU sampling。
- 原始样本数、重建成功率、RDKit validity、唯一性和接受率均可追踪。
- 正式 molecule 有性质记录、generation artifact 和 `source_agent=targetdiff`。
- generation pose 与 docking pose 分开。

### 15.3 CReM 和 AutoGrow4

- CReM 必须实际读取登记的片段 DB，数量不足时如实返回。
- AutoGrow4 必须实际消费 receptor/grid/source pool，记录父代和操作类型。
- 两者结果经过统一结构校验和性质持久化。

### 15.4 Vina 和 GNINA

- 共结晶配体 redocking 产生真实 pose 文件。
- 正式精筛分子同时有独立 Vina run 和 GNINA run。
- Vina pose 与 GNINA pose 不互相覆盖。
- CNNscore、CNNaffinity 和 Vina affinity 方向、量纲、来源明确。
- 共识排名不直接平均原始分数。
- 报告能展示关键相互作用和引擎分歧。

### 15.5 ADMET-AI 和 AiZynthFinder

- ADMET-AI 在离线环境中不临时下载模型，固定分子产生非空模型预测。
- AiZynthFinder 读取真实 policy/filter/template/stock，至少一个已知可解分子得到可解析路线。
- 未找到路线与工具失败是两个不同状态。

### 15.6 数据库保护

- migration 前后 molecule、project、round、campaign 计数对账。
- 历史 REINVENT4 和 DiffDock 项目报告仍可打开。
- 新项目选择 BRAF 后自动获得 3OG7 target-level receptor 和 binding site。
- 删除项目不会删除共享的 builtin target resources。

## 16. BRAF 端到端验收方案

使用 3OG7 BRAF V600E/PLX4032 共晶结构：

1. 同步原始结构、清洗受体、032 晶体配体、PDBQT、pocket-only PDB 和 citation。
2. Vina 与 GNINA redock 032，检查 RMSD 和关键残基。
3. 第一轮：少量 BRAF seed，运行 CReM + TargetDiff；AutoGrow4 仅在来源池充分时运行。
4. 所有通过基础过滤的候选运行 Vina。
5. 按全局 Vina、方法配额和结构聚类选 GNINA rescore 集。
6. 对更小 Top K 运行 GNINA redocking/refinement。
7. 保存两个引擎的 pose、相互作用、分歧和中文报告。
8. 用户确认 Top 分子作为第二轮 seed。
9. 第二、三轮验证中枢 LLM 根据方法命中率、分歧和多样性调整预算。

小规模验收首先证明流程真实、可重复、可追溯，不以生成大量分子为目标。

## 17. 已知风险和不可妥协项

- TargetDiff checkpoint 和旧版 CUDA/PyG 依赖可能需要较长的镜像兼容工作，必须先做 feasibility gate。
- TargetDiff 在 CrossDocked 类数据上的模型表现不能直接等同于真实靶点活性。
- TargetDiff 原始坐标到化学键的重建可能产生价态错误和断裂结构，失败样本必须保留统计。
- Vina/GNINA 都不能证明实验亲和力，也不能自动解决蛋白柔性、共价反应、金属配位和关键结构水问题。
- 多个内置 target ID 代表家族或多个蛋白，必须为具体 receptor profile 建模，不能共用一个模糊口袋。
- 大模型/stock 文件不能无许可证说明直接分发；manifest 必须记录来源和许可。
- 当前工作区有大量未提交修改，实施时不得 reset、checkout 或覆盖用户已有改动。

## 18. 当前仓库状态与下一窗口起点

当前项目路径：

```text
C:\Users\zhihong\Desktop\small-molecule-drug-design-agent
```

已知现状：

- 工作区存在大量未提交的后端、前端和测试修改，必须先读 `git status --short`。
- 前序工作已实现分子性质持久化、GNINA pose/相互作用和部分真实工具验收，但当前 docking 模型仍只能可靠表达单一结果。
- 最近一次对话中记录的全量 Python 测试为 `238 passed, 2 skipped, 3 failed`，不是本次重新运行的结果。
- 三个已知失败与无效 SMILES 在 seed 导入阶段被删除后，旧测试仍期待相反行为有关。
- `database/chembl22_sa2.db` 已存在。
- `data/aizynthfinder/` 下的模型、模板和 stock 文件已存在，但仍需完整 hash/config/真实运行审计。
- `.local/models/reinvent4/` 和 `.local/models/diffdock/` 仍存在，暂不在计划实施前删除。
- BRAF 3OG7 研究记录位于 `docs/research/braf_3og7_binding_site.md`。

下一窗口建议从“阶段 0 + 阶段 1”开始：保护 dirty worktree、记录测试基线，然后只做 TargetDiff BRAF GPU 可行性试验。在试验成功前，不开始大范围删除 REINVENT4。

## 19. 建议的新窗口提示词

```text
请阅读 docs/TARGETDIFF_TOOLCHAIN_REDESIGN_AND_HANDOFF.md，按其中阶段 0 和阶段 1 开始实施。
先检查当前 dirty worktree 和已有改动，不要 reset、checkout 或覆盖用户修改。
本轮先完成 TargetDiff 独立 Docker/checkpoint/GPU 可行性验证，并使用内置 BRAF 3OG7 pocket 真实生成 10-20 个样本；记录原始输出、键重建、RDKit validity 和唯一性。
可行性未通过前不要删除 REINVENT4。完成后运行相关轻量测试并报告结果，再进入数据库和正式接口改造。
```

