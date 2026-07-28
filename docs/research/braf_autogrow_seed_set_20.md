# BRAF/3OG7 AutoGrow4：20 个 Seed 候选分子研究说明

日期：2026-07-23

## 结论

本候选集包含 20 个可作为 AutoGrow4 输入的单组分、中性、互不重复的 Seed 分子。集合以 3OG7 的共晶配体 vemurafenib（PLX4032）为结构锚点，同时加入获批 BRAF 抑制剂、多靶点 RAF 抑制剂、pan-RAF 抑制剂和不同骨架的研究工具化合物，以避免全部 Seed 集中在同一化学系列。

RCSB 将 3OG7 标题记录为 “B-Raf Kinase V600E oncogenic mutant in complex with PLX4032”，分辨率为 2.45 Å，蛋白映射到 UniProt P15056；其非聚合物实体 2 的化学组分代码为 `032`，RCSB 同时把 `032` 标注为 vemurafenib/PLX4032。[RCSB 3OG7][rcsb-3og7] [RCSB entry API][rcsb-entry-api] [RCSB chemcomp 032][rcsb-032]

这 20 个分子适合用于验证 AutoGrow4 Seed 导入、分子准备、遗传操作和候选输出链路，但不代表实验活性、安全性或临床有效性已经得到确认。

## 数据获取与筛选方法

1. 名称、CID、分子式、电荷、PubChem 标准化 SMILES 和 InChIKey 均通过 PubChem PUG REST 官方接口按 CID 获取。PUG REST 当前把请求的 `CanonicalSMILES` 返回为 `ConnectivitySMILES`，把 `IsomericSMILES` 返回为 `SMILES`；下表采用后者作为 Seed SMILES，以保留已知立体化学。
2. BRAF/RAF 关联优先由 PubChem PUG View 中的官方聚合注释核对；3OG7 锚点额外由 RCSB 结构与化学组分接口核对。Naporafenib 的 RAF 关联使用 NCI Drug Dictionary 官方条目补足。AZ-628 另有 PubChem BioAssay `AID 734647` 的 BRAF V600E 细胞测定记录。
3. 排除规则：SMILES 含 `.` 的盐或混合物、非零总电荷、RDKit 不能解析、重复 InChIKey/规范结构，以及与 RAF/BRAF 缺少明确关联的候选。
4. RDKit 2026.03.3 复核结果：`20/20` 可解析，`20/20` 结构唯一，`19` 个唯一 Bemis–Murcko 骨架，`0` 个点号分隔结构。Sorafenib 与 regorafenib 共享核心骨架，但保留二者用于覆盖这一临床多激酶 RAF 系列。
5. ChEMBL 官方 API 在本次核验时持续返回 HTTP 500 或超时，因此未把其作为表格字段的唯一来源；PubChem 中由 ChEMBL 提交的 BioAssay 记录仍可从 PubChem 官方接口追溯。

## Seed 候选集

“定位”只说明为什么把该结构纳入测试集，不应被解释为新的药理结论。每行“名称/SMILES”链接指向该 CID 的 PUG REST 属性响应，“RAF 依据”链接指向官方注释或测定记录。

| # | 化合物 | PubChem CID | 规范 Seed SMILES（保留立体化学） | InChIKey | 选择定位与官方依据 |
|---:|---|---:|---|---|---|
| 1 | Vemurafenib (PLX4032) | [42611257][prop-42611257] | `CCCS(=O)(=O)NC1=C(C(=C(C=C1)F)C(=O)C2=CNC3=C2C=C(C=N3)C4=CC=C(C=C4)Cl)F` | `GPXBXXGIAQBQNI-UHFFFAOYSA-N` | 3OG7 共晶配体和 BRAF 抑制剂；[RCSB 032][rcsb-032]、[PubChem 注释][view-42611257] |
| 2 | Dabrafenib | [44462760][prop-44462760] | `CC(C)(C)C1=NC(=C(S1)C2=NC(=NC=C2)N)C3=C(C(=CC=C3)NS(=O)(=O)C4=C(C=CC=C4F)F)F` | `BFSMGDJOXZAERB-UHFFFAOYSA-N` | B-Raf 抑制剂；[PubChem 注释][view-44462760] |
| 3 | Encorafenib | [50922675][prop-50922675] | `C[C@@H](CNC1=NC=CC(=N1)C2=CN(N=C2C3=C(C(=CC(=C3)Cl)NS(=O)(=O)C)F)C(C)C)NC(=O)OC` | `CMJCXYNUCSMDBY-ZDUSSCGKSA-N` | BRAF/RAF 抑制剂，保留单一手性中心；[PubChem 注释][view-50922675] |
| 4 | Sorafenib | [216239][prop-216239] | `CNC(=O)C1=NC=CC(=C1)OC2=CC=C(C=C2)NC(=O)NC3=CC(=C(C=C3)Cl)C(F)(F)F` | `MLDQJTXFUGDVEO-UHFFFAOYSA-N` | 多激酶 RAF 系列；[PubChem 注释][view-216239] |
| 5 | Regorafenib | [11167602][prop-11167602] | `CNC(=O)C1=NC=CC(=C1)OC2=CC(=C(C=C2)NC(=O)NC3=CC(=C(C=C3)Cl)C(F)(F)F)F` | `FNHKPVJBJVTLMP-UHFFFAOYSA-N` | 与 sorafenib 相关但不重复的多激酶 RAF 分子；[PubChem 注释][view-11167602] |
| 6 | Belvarafenib | [89655386][prop-89655386] | `CC1=C(C2=C(C=C1)C(=NC=C2)NC3=C(C(=CC=C3)Cl)F)NC(=O)C4=CSC5=C4N=CN=C5N` | `KVCQTKNUUQOELD-UHFFFAOYSA-N` | RAF 家族抑制剂；[PubChem 注释][view-89655386] |
| 7 | Naporafenib (LXH254) | [90456533][prop-90456533] | `CC1=C(C=C(C=C1)NC(=O)C2=CC(=NC=C2)C(F)(F)F)C3=CC(=NC(=C3)OCCO)N4CCOCC4` | `UEPXBTCUIIGYCY-UHFFFAOYSA-N` | RAF 抑制剂；[NCI Drug Dictionary][nci-naporafenib] |
| 8 | Lifirafenib (BGB-283) | [89670174][prop-89670174] | `C1CC(=O)NC2=NC=CC(=C21)OC3=CC4=C(C=C3)O[C@H]5[C@@H]4[C@@H]5C6=NC7=C(N6)C=C(C=C7)C(F)(F)F` | `NGFFVZQXSRKHBM-FKBYEOEOSA-N` | BRAF 抑制剂，提供稠合多环手性骨架；[PubChem 注释][view-89670174] |
| 9 | Tovorafenib (TAK-580/MLN2480) | [25161177][prop-25161177] | `C[C@H](C1=NC=C(S1)C(=O)NC2=NC=C(C(=C2)C(F)(F)F)Cl)NC(=O)C3=C(C(=NC=N3)N)Cl` | `VWMJHAFYPMOMGF-ZCFIWIBFSA-N` | pan-RAF 抑制剂，保留已知构型；[PubChem 注释][view-25161177] |
| 10 | Exarafenib (KIN-2787) | [156297592][prop-156297592] | `CC1=C(C=C(C=C1)NC(=O)N2CC[C@H](C2)CC(F)(F)F)C3=CC(=NC(=C3)N4CCOCC4)N[C@H](C)CO` | `GZMYLSJUNSCMTD-MOPGFXCFSA-N` | 多类别 BRAF 变体抑制剂，包含两个已定义手性中心；[PubChem 注释][view-156297592] |
| 11 | PLX-4720 | [24180719][prop-24180719] | `CCCS(=O)(=O)NC1=C(C(=C(C=C1)F)C(=O)C2=CNC3=C2C=C(C=N3)Cl)F` | `YZDJQTHVDDOVHR-UHFFFAOYSA-N` | Vemurafenib 的直接结构近邻和 BRAF V600E 工具化合物；[PubChem 注释][view-24180719] |
| 12 | AZ-628 | [11676786][prop-11676786] | `CC1=C(C=C(C=C1)NC(=O)C2=CC(=CC=C2)C(C)(C)C#N)NC3=CC4=C(C=C3)N=CN(C4=O)C` | `ZGBGPEDJXCYQPH-UHFFFAOYSA-N` | 不同于 PLX 系列的 RAF 研究骨架；[PubChem BRAF V600E assay AID 734647][aid-734647] |
| 13 | TAK-632 | [46209401][prop-46209401] | `C1CC1C(=O)NC2=NC3=C(S2)C(=C(C=C3)OC4=CC(=C(C=C4)F)NC(=O)CC5=CC(=CC=C5)C(F)(F)F)C#N` | `OJFKUJDRGJSAQB-UHFFFAOYSA-N` | pan-RAF 抑制剂、苯并噻唑骨架；[PubChem 注释][view-46209401] |
| 14 | LY3009120 | [71721540][prop-71721540] | `CC1=CC(=C(C=C1C2=C(N=C3C(=C2)C=NC(=N3)NC)C)NC(=O)NCCC(C)(C)C)F` | `HHCBMISMPSAZBF-UHFFFAOYSA-N` | pan-RAF 抑制剂、吡啶并嘧啶骨架；[PubChem 注释][view-71721540] |
| 15 | RAF265 (CHIR-265) | [11656518][prop-11656518] | `CN1C2=C(C=C(C=C2)OC3=CC(=NC=C3)C4=NC=C(N4)C(F)(F)F)N=C1NC5=CC=C(C=C5)C(F)(F)F` | `YABJJWZLRMPFSI-UHFFFAOYSA-N` | RAF/BRAF V600E 抑制剂、苯并咪唑系列；[PubChem 注释][view-11656518] |
| 16 | BMS-908662 (XL281) | [56931136][prop-56931136] | `CC1=C(C=C(C=C1)Cl)N2C(=O)C3=CC=CC=C3C2(C4=CC5=C(C=C4)N=C(N5)NC(=O)OC)O` | `MMNNTJYFHUDSKL-UHFFFAOYSA-N` | RAF 激酶抑制剂、螺/稠合杂环骨架；[PubChem 注释][view-56931136] |
| 17 | Agerafenib (RXDX-105) | [56846693][prop-56846693] | `CC(C)(C1=CC(=NO1)NC(=O)NC2=CC(=CC=C2)OC3=NC=NC4=CC(=C(C=C43)OC)OC)C(F)(F)F` | `DKNUPRMJNUQNHR-UHFFFAOYSA-N` | BRAF V600E/RAF 相关抑制剂、异噁唑-喹唑啉骨架；[PubChem 注释][view-56846693] |
| 18 | GDC-0879 | [11717001][prop-11717001] | `C1C/C(=N\O)/C2=C1C=C(C=C2)C3=CN(N=C3C4=CC=NC=C4)CCO` | `DEZZLWQELQORIU-RELWKKBWSA-N` | B-Raf 工具抑制剂、吲满酮肟/吡唑骨架；[PubChem 注释][view-11717001] |
| 19 | SB 590885 | [135564599][prop-135564599] | `CN(C)CCOC1=CC=C(C=C1)C2=NC(=C(N2)C3=CC=NC=C3)C4=CC5=C(C=C4)C(=NO)CC5` | `MLSAQOINCGAULQ-UHFFFAOYSA-N` | B-Raf 选择性研究工具；[PubChem 注释][view-135564599] |
| 20 | PLX8394 (plixorafenib) | [90116675][prop-90116675] | `C1CN(C[C@@H]1F)S(=O)(=O)NC2=C(C(=C(C=C2)F)C(=O)C3=CNC4=C3C=C(C=N4)C5=CN=C(N=C5)C6CC6)F` | `YYACLQUDUDXAPA-MRXNPFEDSA-N` | BRAF dimer-breaker/“paradox breaker”系列，保留含氟吡咯烷构型；[PubChem 注释][view-90116675] |

## AutoGrow4 使用建议

- 推荐写入 `.smi` 时使用两列：`SMILES<TAB>NAME`。名称应保持唯一，例如 `seed_01_vemurafenib` 到 `seed_20_plx8394`。
- 不要把商品盐型再加入同一文件。例如本表使用 dabrafenib 游离分子，不另加入 dabrafenib mesylate；这样可以避免同一母体结构重复计数。
- 20 个 Seed 能显著降低“抽样数大于当前可用种群”风险，但 `Cannot take a larger sample than population when replace=False` 并不只由初始 Seed 数量决定。若 AutoGrow4 在过滤、去重或某一代幸存者选择后把种群缩得过小，crossover/mutation 的抽样参数仍可能触发同类错误；应同时限制每代抽样数不超过实时种群规模。
- 本集合有 19 个 Murcko 骨架，但包含高分子量、卤素较多和不同电离倾向的分子。正式运行前仍应由现有配体准备流程生成合理质子化状态和 3D 构象，再进入 AutoGrow4。
- 不应直接把对接分数或 AutoGrow4 排名解释为实验活性；候选仍需经过构象检查、反应可行性、ADMET 与实验验证。

## 官方来源

- [RCSB PDB 3OG7 结构页][rcsb-3og7]
- [RCSB Data API：3OG7 entry][rcsb-entry-api]
- [RCSB Data API：3OG7 nonpolymer entity 2][rcsb-nonpolymer]
- [RCSB Data API：chemical component 032][rcsb-032]
- [PubChem PUG REST 文档][pug-rest-docs]
- [PubChem PUG View 文档][pug-view-docs]
- [NCI Drug Dictionary：naporafenib][nci-naporafenib]

[rcsb-3og7]: https://www.rcsb.org/structure/3OG7
[rcsb-entry-api]: https://data.rcsb.org/rest/v1/core/entry/3OG7
[rcsb-nonpolymer]: https://data.rcsb.org/rest/v1/core/nonpolymer_entity/3OG7/2
[rcsb-032]: https://data.rcsb.org/rest/v1/core/chemcomp/032
[pug-rest-docs]: https://pubchem.ncbi.nlm.nih.gov/docs/pug-rest
[pug-view-docs]: https://pubchem.ncbi.nlm.nih.gov/docs/pug-view
[nci-naporafenib]: https://www.cancer.gov/publications/dictionaries/cancer-drug/def/naporafenib
[aid-734647]: https://pubchem.ncbi.nlm.nih.gov/bioassay/734647

[prop-42611257]: https://pubchem.ncbi.nlm.nih.gov/rest/pug/compound/cid/42611257/property/Title,CanonicalSMILES,IsomericSMILES,InChIKey,MolecularFormula,MolecularWeight,Charge/JSON
[prop-44462760]: https://pubchem.ncbi.nlm.nih.gov/rest/pug/compound/cid/44462760/property/Title,CanonicalSMILES,IsomericSMILES,InChIKey,MolecularFormula,MolecularWeight,Charge/JSON
[prop-50922675]: https://pubchem.ncbi.nlm.nih.gov/rest/pug/compound/cid/50922675/property/Title,CanonicalSMILES,IsomericSMILES,InChIKey,MolecularFormula,MolecularWeight,Charge/JSON
[prop-216239]: https://pubchem.ncbi.nlm.nih.gov/rest/pug/compound/cid/216239/property/Title,CanonicalSMILES,IsomericSMILES,InChIKey,MolecularFormula,MolecularWeight,Charge/JSON
[prop-11167602]: https://pubchem.ncbi.nlm.nih.gov/rest/pug/compound/cid/11167602/property/Title,CanonicalSMILES,IsomericSMILES,InChIKey,MolecularFormula,MolecularWeight,Charge/JSON
[prop-89655386]: https://pubchem.ncbi.nlm.nih.gov/rest/pug/compound/cid/89655386/property/Title,CanonicalSMILES,IsomericSMILES,InChIKey,MolecularFormula,MolecularWeight,Charge/JSON
[prop-90456533]: https://pubchem.ncbi.nlm.nih.gov/rest/pug/compound/cid/90456533/property/Title,CanonicalSMILES,IsomericSMILES,InChIKey,MolecularFormula,MolecularWeight,Charge/JSON
[prop-89670174]: https://pubchem.ncbi.nlm.nih.gov/rest/pug/compound/cid/89670174/property/Title,CanonicalSMILES,IsomericSMILES,InChIKey,MolecularFormula,MolecularWeight,Charge/JSON
[prop-25161177]: https://pubchem.ncbi.nlm.nih.gov/rest/pug/compound/cid/25161177/property/Title,CanonicalSMILES,IsomericSMILES,InChIKey,MolecularFormula,MolecularWeight,Charge/JSON
[prop-156297592]: https://pubchem.ncbi.nlm.nih.gov/rest/pug/compound/cid/156297592/property/Title,CanonicalSMILES,IsomericSMILES,InChIKey,MolecularFormula,MolecularWeight,Charge/JSON
[prop-24180719]: https://pubchem.ncbi.nlm.nih.gov/rest/pug/compound/cid/24180719/property/Title,CanonicalSMILES,IsomericSMILES,InChIKey,MolecularFormula,MolecularWeight,Charge/JSON
[prop-11676786]: https://pubchem.ncbi.nlm.nih.gov/rest/pug/compound/cid/11676786/property/Title,CanonicalSMILES,IsomericSMILES,InChIKey,MolecularFormula,MolecularWeight,Charge/JSON
[prop-46209401]: https://pubchem.ncbi.nlm.nih.gov/rest/pug/compound/cid/46209401/property/Title,CanonicalSMILES,IsomericSMILES,InChIKey,MolecularFormula,MolecularWeight,Charge/JSON
[prop-71721540]: https://pubchem.ncbi.nlm.nih.gov/rest/pug/compound/cid/71721540/property/Title,CanonicalSMILES,IsomericSMILES,InChIKey,MolecularFormula,MolecularWeight,Charge/JSON
[prop-11656518]: https://pubchem.ncbi.nlm.nih.gov/rest/pug/compound/cid/11656518/property/Title,CanonicalSMILES,IsomericSMILES,InChIKey,MolecularFormula,MolecularWeight,Charge/JSON
[prop-56931136]: https://pubchem.ncbi.nlm.nih.gov/rest/pug/compound/cid/56931136/property/Title,CanonicalSMILES,IsomericSMILES,InChIKey,MolecularFormula,MolecularWeight,Charge/JSON
[prop-56846693]: https://pubchem.ncbi.nlm.nih.gov/rest/pug/compound/cid/56846693/property/Title,CanonicalSMILES,IsomericSMILES,InChIKey,MolecularFormula,MolecularWeight,Charge/JSON
[prop-11717001]: https://pubchem.ncbi.nlm.nih.gov/rest/pug/compound/cid/11717001/property/Title,CanonicalSMILES,IsomericSMILES,InChIKey,MolecularFormula,MolecularWeight,Charge/JSON
[prop-135564599]: https://pubchem.ncbi.nlm.nih.gov/rest/pug/compound/cid/135564599/property/Title,CanonicalSMILES,IsomericSMILES,InChIKey,MolecularFormula,MolecularWeight,Charge/JSON
[prop-90116675]: https://pubchem.ncbi.nlm.nih.gov/rest/pug/compound/cid/90116675/property/Title,CanonicalSMILES,IsomericSMILES,InChIKey,MolecularFormula,MolecularWeight,Charge/JSON

[view-42611257]: https://pubchem.ncbi.nlm.nih.gov/rest/pug_view/data/compound/42611257/JSON
[view-44462760]: https://pubchem.ncbi.nlm.nih.gov/rest/pug_view/data/compound/44462760/JSON
[view-50922675]: https://pubchem.ncbi.nlm.nih.gov/rest/pug_view/data/compound/50922675/JSON
[view-216239]: https://pubchem.ncbi.nlm.nih.gov/rest/pug_view/data/compound/216239/JSON
[view-11167602]: https://pubchem.ncbi.nlm.nih.gov/rest/pug_view/data/compound/11167602/JSON
[view-89655386]: https://pubchem.ncbi.nlm.nih.gov/rest/pug_view/data/compound/89655386/JSON
[view-89670174]: https://pubchem.ncbi.nlm.nih.gov/rest/pug_view/data/compound/89670174/JSON
[view-25161177]: https://pubchem.ncbi.nlm.nih.gov/rest/pug_view/data/compound/25161177/JSON
[view-156297592]: https://pubchem.ncbi.nlm.nih.gov/rest/pug_view/data/compound/156297592/JSON
[view-24180719]: https://pubchem.ncbi.nlm.nih.gov/rest/pug_view/data/compound/24180719/JSON
[view-46209401]: https://pubchem.ncbi.nlm.nih.gov/rest/pug_view/data/compound/46209401/JSON
[view-71721540]: https://pubchem.ncbi.nlm.nih.gov/rest/pug_view/data/compound/71721540/JSON
[view-11656518]: https://pubchem.ncbi.nlm.nih.gov/rest/pug_view/data/compound/11656518/JSON
[view-56931136]: https://pubchem.ncbi.nlm.nih.gov/rest/pug_view/data/compound/56931136/JSON
[view-56846693]: https://pubchem.ncbi.nlm.nih.gov/rest/pug_view/data/compound/56846693/JSON
[view-11717001]: https://pubchem.ncbi.nlm.nih.gov/rest/pug_view/data/compound/11717001/JSON
[view-135564599]: https://pubchem.ncbi.nlm.nih.gov/rest/pug_view/data/compound/135564599/JSON
[view-90116675]: https://pubchem.ncbi.nlm.nih.gov/rest/pug_view/data/compound/90116675/JSON
