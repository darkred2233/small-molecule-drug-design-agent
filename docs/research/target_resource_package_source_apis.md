# 靶点资源包的官方数据源与采集约定

本说明限定第一期十个靶点（EGFR、BRAF V600E、ALK、MET、JAK2、BTK、PIK3CA、PARP1、KRAS G12C、HDAC6）的真实数据采集方式。数据导入器应保存每次响应的原始字节、SHA-256、请求 URL、UTC 下载时间和来源版本；仅有 PDB ID 或元数据不能把资源包标记为 `dock_ready`。

## UniProtKB

每个已知 accession 应下载完整、可审计的 JSON：

```text
GET https://rest.uniprot.org/uniprotkb/{accession}.json
```

例如 `P00533` 的响应含有 `primaryAccession`、`secondaryAccessions`、`uniProtkbId`、`entryAudit`、`organism`、`proteinDescription`、`genes`、`features`、交叉引用和 `sequence`。需要持久化的最小字段为：

- `primaryAccession`、`secondaryAccessions`、`uniProtkbId`
- `organism.scientificName`、`organism.taxonId`（第一期必须为人类 `9606`）
- `proteinDescription.recommendedName.fullName.value`、`genes[].geneName.value` 及同义词
- `sequence.value`、`sequence.length`、`sequence.md5`、`sequence.crc64`
- `entryAudit.entryVersion`、`entryAudit.sequenceVersion`、两个更新时间
- 与结构选择有关的 `features[]`（`type`、`location.start.value`、`location.end.value`、`description`、evidence）和 PDB 交叉引用。

若根据基因名发现 accession，使用审阅过的人类条目作为候选集，再人工确认突变和构建体：

```text
GET https://rest.uniprot.org/uniprotkb/search?query=(gene:{SYMBOL})%20AND%20(organism_id:9606)%20AND%20(reviewed:true)&format=tsv&fields=accession,id,protein_name,gene_primary,gene_names,organism_name,organism_id,length,sequence,cc_function,ft_domain,ft_binding
```

不要把 TSV 字段名写死为未经验证的值；字段清单以 UniProt 的 result-fields 配置为准。导入时还要记录完整条目响应头的 `X-UniProt-Release` 和 `X-UniProt-Release-Date`，而不是手写一个推测的 release 名称。

官方来源：

- [UniProtKB REST 完整条目示例（P00533）](https://rest.uniprot.org/uniprotkb/P00533.json)
- [UniProtKB 搜索字段目录](https://rest.uniprot.org/configure/uniprotkb/result-fields)
- [UniProt REST 服务根目录](https://rest.uniprot.org/)

## RCSB PDB

先以 UniProt accession 从 RCSB Search API 枚举候选条目；结果必须再按实验方法、分辨率、物种、目标链、变体、共晶小分子和口袋完整度筛选，搜索命中本身不是可用于对接的结构。

```json
{
  "query": {
    "type": "terminal",
    "service": "text",
    "parameters": {
      "attribute": "rcsb_polymer_entity_container_identifiers.reference_sequence_identifiers.database_accession",
      "operator": "exact_match",
      "value": "{UNIPROT_ACCESSION}"
    }
  },
  "return_type": "entry",
  "request_options": {"return_all_hits": true, "results_verbosity": "compact"}
}
```

提交该 JSON 到 `POST https://search.rcsb.org/rcsbsearch/v2/query`。对选中的 `{PDB_ID}`，依次采集：

| 目的 | 官方端点 | 需要写入的关键字段 |
| --- | --- | --- |
| 条目质量与版本 | `GET https://data.rcsb.org/rest/v1/core/entry/{PDB_ID}` | `struct.title`、`exptl.method`、`rcsb_entry_info.experimental_method`、`rcsb_entry_info.resolution_combined`、`rcsb_accession_info.initial_release_date`、`revision_date`、`major_revision`、`minor_revision`、`rcsb_entry_container_identifiers` |
| 蛋白实体和链 | `GET https://data.rcsb.org/rest/v1/core/polymer_entity/{PDB_ID}/{ENTITY_ID}` | `rcsb_polymer_entity_container_identifiers.asym_ids`、`auth_asym_ids`、`uniprot_ids`、`reference_sequence_identifiers`，以及构建体序列 `entity_poly.pdbx_seq_one_letter_code` |
| 共晶小分子实体 | `GET https://data.rcsb.org/rest/v1/core/nonpolymer_entity/{PDB_ID}/{ENTITY_ID}` | `pdbx_entity_nonpoly.comp_id`、`name`、`rcsb_nonpolymer_entity_container_identifiers` |
| 配体实例及邻近残基 | `GET https://data.rcsb.org/rest/v1/core/nonpolymer_entity_instance/{PDB_ID}/{ASYM_ID}` | `rcsb_nonpolymer_entity_instance_container_identifiers` 和 `rcsb_target_neighbors`（目标链、auth residue 编号、残基名、距离） |
| 化学组分标准描述符 | `GET https://data.rcsb.org/rest/v1/core/chemcomp/{COMP_ID}` | `rcsb_chem_comp_descriptor.SMILES`、`SMILES_stereo`、`InChI`、`InChIKey` |
| 实际坐标工件 | `GET https://files.rcsb.org/download/{PDB_ID}.cif` | 保存原始 mmCIF 及 SHA-256；可额外保存 `.pdb`，但 mmCIF 是主输入 |

以 BRAF `3OG7` 为例，条目端点提供 2.45 A 分辨率和修订信息；蛋白实体端点将链映射到 `P15056`；非聚合物实例端点的 `rcsb_target_neighbors` 给出配体邻近的蛋白链、残基和距离。该 API 数据可用于生成候选 pocket residues，但 grid 中心、受体准备参数和 redock RMSD 仍须由本项目计算并保存，不能被标成来自 RCSB 的已验证结果。

官方来源：

- [RCSB Search API](https://search.rcsb.org/)
- [RCSB Data API 文档](https://data.rcsb.org/)
- [RCSB Data API 的 3OG7 entry 示例](https://data.rcsb.org/rest/v1/core/entry/3OG7)
- [RCSB 文件下载的 3OG7 mmCIF 示例](https://files.rcsb.org/download/3OG7.cif)

## 导入状态门槛

导入器应将来源记录、`TargetExternalId`、`TargetStructure`、链、共晶配体和原始工件分开写入。建议状态如下：

1. `metadata_ready`：已核对 UniProt 和 PDB 元数据，但尚未下载并验证坐标工件。
2. `structure_collected`：mmCIF、完整 API 响应和 SHA-256 均已存档，且蛋白链确实映射到目标 UniProt accession。
3. `receptor_prepared`：记录了去水/辅因子策略、质子化、缺失残基处理、输出 receptor 文件及 SHA-256。
4. `dock_ready`：除上述内容外，含从同一结构提取的参考配体、可重复的 pocket/grid 参数、重对接命令和通过项目阈值的 RMSD。缺失任何一项时仍不得开放 Vina/GNINA 正式阶段。

这一区分避免将数据库元数据、推导出的口袋和实际可复现的结构计算混为同一证据等级。
