# RAG 数据建设方案

日期：2026-07-09

## 1. 建设目标

这个 RAG 不应该做成“什么资料都塞进去”的全文仓库，而应该做成候选分子排序和解释用的证据库。

当前 `candidate_ranking` 主要依赖 docking、ADMET、synthesis、rule filter、properties 和 RAG evidence。RAG 的价值是补强这些问题：

- 这个靶点为什么值得做。
- 哪些配体、骨架、关键取代基和活性数据支持当前设计。
- 哪些结构、口袋、关键残基支持 docking 解释。
- 哪些已知药物、类似骨架或标签提示 ADMET/安全风险。
- 哪些专利、临床、文献证据提示竞争或可开发性风险。
- 每个 Top 分子的推荐或淘汰原因能追溯到文档、页码、数据库记录或 evidence_id。

## 2. 总体数据量建议

### 单个活跃项目靶点

第一版建议每个活跃靶点建设一个“深度包”：

| 数据类型 | RAG 文档/摘要建议量 | 结构化记录建议量 | 目标用途 |
| --- | ---: | ---: | --- |
| 靶点基础资料 | 1-3 条 | 1 条 target 记录 | 建立 target profile |
| 已知药物/参考配体 | 20-80 条说明 | 20-200 个分子 | seed ligand、机制、参照物 |
| 活性与 SAR | 50-150 条 assay/SAR 摘要 | 500-5,000 条活性记录 | SAR、相似骨架、活性阈值 |
| 论文/综述 | 20-60 篇摘要或全文片段 | PMID/DOI 元数据 | 机制、SAR、ADMET、反证 |
| PDB/结构口袋 | 5-15 个结构摘要 | 5-30 个 PDB/binding site | docking 解释、关键残基 |
| ADMET/安全性 | 20-80 条风险证据 | 100-2,000 条实验/标签/预测记录 | hERG、Ames、DILI、CYP、毒性 |
| 专利/竞争情报 | 20-60 个专利族摘要 | 50-500 个专利化合物/claim/example | novelty、FTO、专利风险 |
| 临床/适应症/竞品 | 10-50 条 trial/drug evidence | 10-200 条 trial/drug 记录 | 成药性、适应症、竞品状态 |
| 用户项目资料 | 全量上传 | 全量结构化 | 项目私有证据 |

深度包建完后，通常会产生 2,000-8,000 个 chunks。这个范围对当前 SQLite + JSON embedding 能跑；如果长期扩到多个靶点和十万级 chunk，建议切 PostgreSQL + pgvector。

### 10 个内置 MVP 靶点

当前内置靶点包括 EGFR、ALK、BRAF、KRAS G12C、JAK2、BTK、CDK4/6、PARP1、PI3K、HDAC。第一轮不要每个靶点都做满深度包，建议先做“基础包”：

| 数据类型 | 每靶点建议量 | 10 靶点合计 |
| --- | ---: | ---: |
| target profile | 1 条 | 10 条 |
| 参考药物/工具分子 | 5-15 个 | 50-150 个 |
| 高质量活性记录 | 100-500 条 | 1,000-5,000 条 |
| 关键文献/综述 | 5-15 篇 | 50-150 篇 |
| PDB 结构 | 3-8 个 | 30-80 个 |
| ADMET/安全片段 | 5-20 条 | 50-200 条 |
| 专利族摘要 | 5-15 个 | 50-150 个 |

基础包用于“用户不上传资料也能启动项目”；活跃项目再补深度包。

## 3. 每类数据放什么

### 3.1 靶点基础资料

存入 RAG：

- 靶点名称、别名、物种、UniProt ID、Ensembl ID。
- 功能描述、疾病关系、成药性说明。
- 关键突变、关键残基、亚型选择性。
- 已知适应症、耐药机制、主流药物类别。

结构化入库：

- `targets`
- 后续可扩展 `target_aliases`、`target_disease_links`

获取方式：

- UniProt REST API：`https://rest.uniprot.org/uniprotkb/{accession}.json`
- Open Targets GraphQL：`https://api.platform.opentargets.org/api/v4/graphql`
- ChEMBL target search：`https://www.ebi.ac.uk/chembl/api/data/target/search.json?q=EGFR`

权威来源：

- [UniProt API](https://www.uniprot.org/help/api)
- [Open Targets GraphQL API](https://platform-docs.opentargets.org/data-access/graphql-api)
- [ChEMBL Data Web Services](https://chembl.gitbook.io/chembl-interface-documentation/web-services/chembl-data-web-services)

### 3.2 已知药物和参考配体

存入 RAG：

- 每个药物/参考配体的一段说明：机制、靶点、适应症、研发状态、已知风险。
- 只放解释性文字，不把大批 SMILES 原样当文本 chunk。

结构化入库：

- `seed_ligands` 或后续 `reference_drugs`
- `target_drug_library`
- `molecules`

建议量：

- 基础包：每靶点 5-15 个。
- 深度包：每靶点 20-80 个，优先 approved、clinical、tool compound、经典 SAR series。

获取方式：

- PubChem PUG-REST 获取 CID、SMILES、InChIKey、性质。
- ChEMBL molecule/drug/mechanism/drug_indication 获取药物与机制。
- Open Targets drug endpoint 获取 indication、mechanism、known drugs。

示例：

```text
https://pubchem.ncbi.nlm.nih.gov/rest/pug/compound/name/osimertinib/property/CanonicalSMILES,InChIKey,MolecularWeight/JSON
https://www.ebi.ac.uk/chembl/api/data/molecule/search.json?q=osimertinib
```

权威来源：

- [PubChem PUG-REST](https://pubchem.ncbi.nlm.nih.gov/docs/pug-rest)
- [ChEMBL Data Web Services](https://chembl.gitbook.io/chembl-interface-documentation/web-services/chembl-data-web-services)

### 3.3 活性数据与 SAR

这是候选排序最该重视的数据。RAG 只存“解释性摘要”，原始数值表要结构化。

存入 RAG：

- assay 描述摘要。
- SAR 结论：哪些取代基提高活性，哪些导致选择性或毒性问题。
- 数据来源文献摘要。
- 对每个主要 scaffold 生成 1 条简短 SAR card。

结构化入库：

- `seed_ligands`
- 后续可扩展 `activity_records`
- 后续可扩展 `sar_rules`

建议量：

- 基础包：每靶点 100-500 条高质量活性记录，10-30 条 SAR 摘要。
- 深度包：每靶点 500-5,000 条活性记录，50-150 条 assay/SAR 摘要。

筛选规则：

- 优先 Homo sapiens、single protein target、binding/functional assay。
- 优先 `IC50/Ki/Kd/EC50`，保留单位、关系符号、pChEMBL。
- 优先 `pchembl_value >= 5` 或活性小于等于 10 uM。
- 去掉明显重复、盐型重复、assay 描述缺失或靶点不清记录。

获取方式：

- ChEMBL activity/assay/document。
- BindingDB by UniProt 或 PDB。
- PubChem BioAssay/Tox21 作为补充。

示例：

```text
https://www.ebi.ac.uk/chembl/api/data/activity.json?target_chembl_id=CHEMBL203&pchembl_value__gte=5&limit=1000
https://www.bindingdb.org/rwd/bind/BindingDBRESTfulAPI.jsp
```

权威来源：

- [ChEMBL activity/assay/document endpoints](https://chembl.gitbook.io/chembl-interface-documentation/web-services/chembl-data-web-services)
- [BindingDB Web Services](https://www.bindingdb.org/rwd/bind/BindingDBRESTfulAPI.jsp)
- [Tox21 Data and Tools](https://tox21.gov/data-and-tools/)

### 3.4 论文、综述和全文片段

存入 RAG：

- 综述摘要。
- SAR 论文的 abstract、Results/SAR section、figure/table caption。
- ADMET、安全性、耐药机制、选择性相关段落。
- 开放全文可用时收 PMC full text；否则只收题录和摘要。

建议量：

- 基础包：每靶点 5-15 篇。
- 深度包：每靶点 20-60 篇。
- 对活跃项目，额外加入用户上传的核心论文，全量收。

获取方式：

- PubMed ESearch：检索 PMID。
- ESummary/EFetch：获取题录、摘要。
- PMC：优先 free full text。

检索式示例：

```text
EGFR AND (inhibitor OR ligand) AND (SAR OR "structure activity" OR "crystal structure" OR ADMET)
BTK AND covalent AND inhibitor AND selectivity
KRAS G12C AND inhibitor AND resistance
```

权威来源：

- [NCBI E-utilities](https://www.ncbi.nlm.nih.gov/books/NBK25501/)
- [E-utilities 参数与用法](https://www.ncbi.nlm.nih.gov/books/NBK25499/)

### 3.5 PDB 结构和结合口袋

存入 RAG：

- PDB 标题、分辨率、方法、配体、突变、构象状态。
- 关键相互作用摘要：hinge H-bond、covalent residue、DFG-in/out、gatekeeper residue。
- 共晶配体和口袋说明。

结构化入库：

- `binding_sites`
- 后续可扩展 `pdb_entries`
- 后续可扩展 `protein_ligand_interactions`

建议量：

- 基础包：每靶点 3-8 个代表结构。
- 深度包：每靶点 5-15 个结构，必要时 30 个以内。

筛选规则：

- 优先 co-crystal ligand。
- 分辨率优先 <= 3.0 A。
- 覆盖 active/inactive、突变体、代表药物、关键耐药突变。
- 对 docking 使用的结构必须有明确 chain、binding site、grid center。

获取方式：

- RCSB PDB Data API：entry/polymer/nonpolymer metadata。
- RCSB Search API：按 UniProt、ligand、experimental method、resolution 搜索。

示例：

```text
https://data.rcsb.org/rest/v1/core/entry/4ZAU
https://data.rcsb.org/graphql
```

权威来源：

- [RCSB PDB Data API](https://data.rcsb.org/)

### 3.6 ADMET 与安全性

存入 RAG：

- 已上市药物标签中的 warnings、adverse reactions、drug interactions。
- 类似骨架的 hERG、Ames、DILI、CYP inhibition、solubility、permeability 风险说明。
- ADMETlab/工具输出的解释摘要。

结构化入库：

- `admet_results`
- 后续可扩展 `admet_evidence_records`

建议量：

- 基础包：每靶点 5-20 条安全/ADMET 证据。
- 深度包：每靶点 20-80 条 RAG 证据，100-2,000 条结构化 ADMET/毒性记录。

获取方式：

- openFDA drug label：已上市药物标签。
- ChEMBL drug_warning/metabolism。
- SIDER：药物-不良反应。
- EPA CompTox/ToxCast/Tox21：公开毒理和 assay 数据。
- ADMETlab 3.0：作为预测工具输出，不作为原始事实库替代实验数据。

示例：

```text
https://api.fda.gov/drug/label.json?search=openfda.generic_name:"OSIMERTINIB"&limit=1
```

权威来源：

- [openFDA drug label API](https://open.fda.gov/apis/drug/label/)
- [EPA CompTox APIs](https://www.epa.gov/comptox-tools/computational-toxicology-and-exposure-apis)
- [Tox21 Data and Tools](https://tox21.gov/data-and-tools/)
- [SIDER download](https://sideeffects.embl.de/download/)
- [ADMETlab 3.0 API docs](https://admetlab3.scbdd.com/apis/)

### 3.7 专利与竞争情报

存入 RAG：

- 专利 title、abstract、claims、examples、assay table 摘要。
- scaffold/warhead/核心 Markush 范围。
- patent family、priority date、assignee。
- 与项目分子的相似性风险摘要。

结构化入库：

- 后续可扩展 `patent_records`
- 后续可扩展 `patent_compounds`
- 后续可扩展 `similarity_to_patent`

建议量：

- 基础包：每靶点 5-15 个专利族。
- 深度包：每靶点 20-60 个专利族，50-500 个结构化专利化合物或 examples。

获取方式：

- Lens Patent API：适合检索全文、claims、description，但可能需要机构/访问计划。
- EPO OPS：可查 bibliographic、legal status、full text/image 等，需注册。
- Google Patents Public Datasets / BigQuery：适合大规模统计和专利检索，不建议网页硬爬。

权威来源：

- [Lens API docs](https://docs.api.lens.org/)
- [EPO Open Patent Services](https://www.epo.org/en/searching-for-patents/data/web-services/ops)
- [Google Patents Public Datasets](https://github.com/google/patents-public-data)

### 3.8 临床、适应症和竞品

存入 RAG：

- target-disease association。
- known drug、mechanism、clinical phase、trial status。
- 临床适应症、失败原因、耐药/安全信号。

结构化入库：

- 后续可扩展 `clinical_trials`
- 后续可扩展 `target_disease_links`
- 后续可扩展 `competitor_drugs`

建议量：

- 基础包：每靶点 5-20 条。
- 深度包：每靶点 10-50 条 trial/drug evidence，10-200 条结构化记录。

获取方式：

- ClinicalTrials.gov API v2。
- Open Targets drug/disease/target association。
- ChEMBL drug_indication/mechanism。

权威来源：

- [ClinicalTrials.gov API](https://clinicaltrials.gov/data-api/api)
- [ClinicalTrials.gov API v2 公告](https://www.nlm.nih.gov/pubs/techbull/ma24/ma24_clinicaltrials_api.html)
- [Open Targets GraphQL API](https://platform-docs.opentargets.org/data-access/graphql-api)

## 4. 入库原则

### 4.1 什么进 RAG

进 RAG 的内容应该是“人能读懂、能解释决策”的文本：

- 文献摘要、结论、SAR 描述。
- assay 方法说明和数据解释。
- PDB 结构说明和关键相互作用。
- 药物标签中的安全性段落。
- 专利 claim/example/assay 的解释性段落。
- 用户项目说明、实验背景、会议纪要、假设。

### 4.2 什么不直接进 RAG

这些内容应该优先结构化，不要只当文本塞向量库：

- 大规模 SMILES/SDF/MOL2。
- 原始活性表格。
- 原始 ADMET 预测表。
- docking pose 坐标。
- PDB/mmCIF 原始坐标。
- 大型专利化合物表。

正确做法是：结构化数据入关系库；再生成简短摘要进入 RAG。

## 5. 第一轮执行清单

### 第 1 周：打基础包

目标：让 10 个内置靶点都能回答基础问题。

每个靶点抓取：

- UniProt target profile：1 条。
- PubChem/ChEMBL 参考药物：5-15 个。
- ChEMBL 活性记录：100-500 条。
- PubMed 文献摘要：5-15 篇。
- RCSB PDB：3-8 个结构。
- openFDA/SIDER/ChEMBL drug warning：5-20 条安全证据。

验收：

- 每个内置靶点至少 100 个 RAG chunks。
- 查询“target + inhibitor + SAR/risk/resistance”时 Top 10 至少 7 条相关。
- 每个 target 至少有 2 条 target evidence、2 条 SAR evidence、1 条 safety evidence、1 条 structure evidence。

### 第 2 周：做活跃项目深度包

目标：针对当前正在做的项目靶点，让 ranking 的 RAG evidence 真正可用。

抓取：

- 活性记录 500-5,000 条。
- SAR/assay 摘要 50-150 条。
- 文献 20-60 篇。
- PDB 5-15 个。
- ADMET/安全证据 20-80 条。
- 专利族 20-60 个。
- 临床/竞品 10-50 条。

验收：

- 项目 RAG chunks 2,000-8,000。
- Top 20 候选分子中，每个分子至少能绑定 2 条证据。
- evidence link 至少覆盖 `target_sar`、`admet_risk`、`structure_interaction`、`patent_or_novelty` 中的 2 类。
- 更新 RAG 后执行 `/projects/{project_id}/rankings/generate`，证据置信度能随 evidence 数量变化。

### 第 3 周：质量控制和自动刷新

目标：把 RAG 从“一次性资料库”变成可维护的数据资产。

增加：

- 数据源版本记录。
- DOI/PMID/PDB/CHEMBL/BindingDB/Patent ID 去重。
- 低质量 chunk 过滤。
- 每周刷新 PubMed/ChEMBL/ClinicalTrials。
- 每月刷新专利和大型毒理数据。

验收：

- 每条 evidence 都有 `source`、`source_type`、`title`、`page/section` 或数据库 ID。
- 高风险结论不能只来自模型预测，必须尽量绑定公开实验、标签或文献证据。
- 专利/临床/安全性证据标记日期和来源，避免旧证据误导。

## 6. 数据优先级

如果只能先做一批，我建议按这个顺序：

1. UniProt + ChEMBL target/drug/activity：最影响 SAR 和 reference ligand。
2. PubChem：补齐 SMILES、InChIKey、基础性质。
3. PubMed/PMC：补机制、SAR、ADMET、反证解释。
4. RCSB PDB：补 docking 和关键残基解释。
5. openFDA + SIDER + ChEMBL drug_warning：补安全性。
6. BindingDB：补高质量亲和力记录。
7. ClinicalTrials + Open Targets：补临床和适应症。
8. Patent：补 novelty/FTO 风险。
9. EPA/Tox21/ADMETlab：补毒理和预测证据。

## 7. 推荐的数据抓取策略

### 7.1 查询先从靶点 ID 出发

每个项目先建立 canonical IDs：

```json
{
  "target_name": "EGFR",
  "aliases": ["ERBB1", "HER1"],
  "uniprot_id": "P00533",
  "ensembl_id": "ENSG00000146648",
  "chembl_target_id": "CHEMBL203",
  "pdb_ids": ["4ZAU", "5UG9", "6JXT"]
}
```

这样比只用关键词搜索稳定得多。

### 7.2 每条记录保留 provenance

最少要保留：

- `source_name`
- `source_url`
- `external_id`
- `retrieved_at`
- `license_or_terms`
- `target_id`
- `molecule_id` 或 `drug_name`
- `document_type`
- `section/page`

### 7.3 不要一次抓全库

第一版按项目靶点抓取，不要全量下载 ChEMBL/BindingDB/PubChem。原因：

- 体量大。
- 去重和清洗成本高。
- 当前 RAG MVP 还不是大规模数据仓库。
- 排序需要的是与项目相关的证据，不是全域检索。

## 8. 当前代码需要的后续增强

当前 RAG 已能存文档、URL 和内置靶点。为了完整执行本方案，建议下一步加这些抓取器：

| 模块 | 功能 |
| --- | --- |
| `scripts/collect_target_pack.py` | 按 target_id 抓 UniProt/ChEMBL/PubChem/RCSB/PubMed 基础包 |
| `scripts/collect_activity_records.py` | 抓 ChEMBL/BindingDB 活性表，结构化入库并生成 SAR 摘要 |
| `scripts/collect_safety_pack.py` | 抓 openFDA/SIDER/ChEMBL warning，生成安全证据 |
| `scripts/collect_patent_pack.py` | 接 Lens/EPO/BigQuery 专利数据 |
| `src/medagent/services/rag_importers.py` | 把外部 JSON/TSV 规范化为 RAG document/chunk |
| `src/medagent/services/evidence_linking.py` | 按 molecule/scaffold/claim_type 自动绑定 evidence |

## 9. 最小可行版本

如果现在就要开始喂数据，最小可行版本如下：

对当前项目靶点：

- 1 条 UniProt profile。
- 20 个 reference drugs / seed ligands。
- 500 条 ChEMBL activity records。
- 20 篇 PubMed 文献摘要。
- 5 个 PDB 结构摘要。
- 20 条 ADMET/安全性证据。
- 10 个专利族摘要。

这批数据通常就足够让 RAG 在候选排序里产生可见价值。
