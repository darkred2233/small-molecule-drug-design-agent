# 小分子药物设计 Agent - 数据库扩展完整指南

**目标**: 扩展RAG知识库、靶点信息库、专利论文库，提升系统的知识覆盖度和推理准确性

**更新日期**: 2026-07-12

---

## 📋 数据扩展总览

### 扩展目标
1. **靶点信息库**: 从10个扩展到50-100个常见药物靶点
2. **药物分子库**: 从32个扩展到500-1000个已上市/临床药物
3. **文献知识库**: 建立10000+篇高质量论文的RAG库
4. **专利知识库**: 建立5000+件相关专利的检索库
5. **结构活性数据**: 获取100万+条化合物活性数据
6. **ADMET数据**: 建立毒性/代谢/药代数据库
7. **合成路线库**: 收集常见药物骨架的合成方法

---

## 🎯 一、靶点信息扩展

### 1.1 推荐靶点列表（按疾病领域）

#### 肿瘤靶点（20个）
\`\`\`
已有: EGFR, ALK, BRAF, KRAS G12C
待扩展:
- HER2 (ERBB2)
- MET
- ROS1
- RET
- NTRK1/2/3
- FGFR1/2/3
- MEK1/2
- mTOR
- AKT1/2
- PI3Kα/β/δ/γ
- CDK2/4/6/9
- PARP1/2
- BCL-2/BCL-XL
- MDM2
- PD-1/PD-L1
\`\`\`

#### 代谢疾病靶点（10个）
\`\`\`
- DPP-4
- SGLT2
- GLP-1R
- PPAR-γ
- GPR40 (FFAR1)
- 11β-HSD1
- PTP1B
- Glucokinase
- FXR
- ACC1/2
\`\`\`

#### 心血管靶点（8个）
\`\`\`
- ACE
- AT1R
- Renin
- PCSK9
- Factor Xa
- Thrombin
- P2Y12
- β1-adrenergic receptor
\`\`\`

#### 神经系统靶点（10个）
\`\`\`
- NMDA receptor
- AMPA receptor
- mGluR5
- 5-HT receptors (1A/2A/2C/6)
- D2/D3 dopamine receptors
- MAO-A/B
- AChE
- BACE1
- Tau aggregation
- α-Synuclein
\`\`\`

#### 感染性疾病靶点（10个）
\`\`\`
- HIV-1 protease
- HIV-1 RT
- HIV-1 integrase
- HCV NS3/4A protease
- HCV NS5A
- HCV NS5B polymerase
- Neuraminidase (influenza)
- SARS-CoV-2 Mpro
- SARS-CoV-2 RdRp
- Bacterial DNA gyrase
\`\`\`

### 1.2 靶点信息数据源

| 数据源 | 内容 | 获取方法 | API/工具 |
|--------|------|----------|---------|
| **UniProt** | 靶点序列、功能注释、疾病关联 | RESTful API | \`https://rest.uniprot.org/\` |
| **PDB** | 蛋白结构、共晶配体、结合口袋 | RESTful API + RCSB Search | \`https://data.rcsb.org/\` |
| **AlphaFold DB** | 预测结构（无实验结构时） | 批量下载 | \`https://alphafold.ebi.ac.uk/\` |
| **ChEMBL** | 靶点-化合物活性数据 | SQL API | \`https://chembl.gitbook.io/\` |
| **DrugBank** | 靶点-药物关联、药物信息 | XML下载（需注册） | \`https://go.drugbank.com/\` |
| **Therapeutic Target Database** | 靶点分类、疾病关联、药物管线 | 网页爬取或数据下载 | \`https://db.idrblab.net/ttd/\` |
| **Open Targets Platform** | 靶点-疾病关联证据 | GraphQL API | \`https://platform.opentargets.org/\` |
| **Pharos** | 靶点开发水平分类 | RESTful API | \`https://pharos.nih.gov/api\` |

### 1.3 靶点信息获取脚本示例

\`\`\`python
# src/medagent/data/collectors/uniprot.py 增强版

import requests
from typing import Dict, List

class UniProtCollector:
    BASE_URL = "https://rest.uniprot.org/uniprotkb"
    
    def fetch_target_info(self, uniprot_id: str) -> Dict:
        """获取靶点基础信息"""
        url = f"{self.BASE_URL}/{uniprot_id}.json"
        response = requests.get(url)
        data = response.json()
        
        return {
            "uniprot_id": uniprot_id,
            "protein_name": data["proteinDescription"]["recommendedName"]["fullName"]["value"],
            "gene_name": data["genes"][0]["geneName"]["value"] if "genes" in data else None,
            "organism": data["organism"]["scientificName"],
            "function": self._extract_function(data),
            "disease_associations": self._extract_diseases(data),
            "sequence": data["sequence"]["value"],
        }
    
    def fetch_structure_pdbs(self, uniprot_id: str) -> List[str]:
        """获取关联的PDB结构"""
        url = f"{self.BASE_URL}/search?query=accession:{uniprot_id}&fields=xref_pdb"
        response = requests.get(url)
        return self._parse_pdb_ids(response.json())

# 使用示例
collector = UniProtCollector()
egfr_info = collector.fetch_target_info("P00533")
egfr_pdbs = collector.fetch_structure_pdbs("P00533")
\`\`\`

### 1.4 结合口袋信息获取

| 工具 | 用途 | 获取方法 |
|------|------|---------|
| **P2Rank** | 从结构预测结合位点 | \`https://github.com/rdk/p2rank\` |
| **fpocket** | 口袋识别和打分 | \`https://github.com/Discngine/fpocket\` |
| **DeepSite** | 基于深度学习的位点预测 | \`https://playmolecule.com/deepsite/\` |
| **PDBbind** | 已知结合口袋数据集 | \`http://www.pdbbind.org.cn/\` |
| **sc-PDB** | 药物结合位点数据库 | \`http://bioinfo-pharma.u-strasbg.fr/scPDB/\` |

---

## 🧪 二、分子活性数据扩展

### 2.1 化合物活性数据源

| 数据库 | 数据量 | 内容 | 获取方法 |
|--------|--------|------|---------|
| **ChEMBL** | 230万+化合物，1900万+活性数据 | IC50, Ki, Kd, EC50等 | PostgreSQL dump或API |
| **BindingDB** | 280万+结合数据 | Kd, Ki, IC50, EC50 | TSV批量下载 |
| **PubChem BioAssay** | 130万+生物测定 | 各类活性筛选数据 | FTP下载或API |
| **ZINC** | 23亿+可购买化合物 | 化合物可获得性 | 子集下载 |
| **ExCAPE-DB** | 7000万+活性预测 | ChEMBL数据的扩展预测 | Zenodo下载 |
| **DTC** | Drug Target Commons | 众包的活性数据 | 网页下载 |


### 2.2 ChEMBL数据获取方案

#### 方案A: PostgreSQL完整库（推荐用于大规模）
```bash
# 1. 下载ChEMBL PostgreSQL dump（约10GB）
wget https://ftp.ebi.ac.uk/pub/databases/chembl/ChEMBLdb/latest/chembl_34_postgresql.tar.gz

# 2. 导入PostgreSQL
tar -xzf chembl_34_postgresql.tar.gz
psql -U postgres -d chembl_34 < chembl_34.pgdump.sql

# 3. 提取靶点相关数据
psql -U postgres -d chembl_34 << EOF
-- 导出EGFR相关活性数据
COPY (
  SELECT 
    md.chembl_id as compound_id,
    cs.canonical_smiles,
    td.chembl_id as target_id,
    td.pref_name as target_name,
    act.standard_type,
    act.standard_value,
    act.standard_units,
    act.pchembl_value,
    d.pubmed_id
  FROM activities act
  JOIN molecule_dictionary md ON act.molregno = md.molregno
  JOIN compound_structures cs ON md.molregno = cs.molregno
  JOIN assays a ON act.assay_id = a.assay_id
  JOIN target_dictionary td ON a.tid = td.tid
  JOIN docs d ON act.doc_id = d.doc_id
  WHERE td.pref_name ILIKE '%EGFR%'
    AND act.standard_type IN ('IC50', 'Ki', 'Kd', 'EC50')
    AND act.pchembl_value IS NOT NULL
) TO '/tmp/egfr_activities.csv' WITH CSV HEADER;
EOF
```

#### 方案B: REST API（灵活但慢，适合小规模）
```python
from chembl_webresource_client.new_client import new_client

# 查询EGFR靶点
target = new_client.target
egfr_targets = target.filter(target_synonym__icontains='EGFR')

# 获取活性数据
activity = new_client.activity
egfr_activities = activity.filter(
    target_chembl_id='CHEMBL203',
    pchembl_value__isnull=False
).only(['molecule_chembl_id', 'canonical_smiles', 'standard_type', 
        'standard_value', 'pchembl_value'])

# 批量获取（自动分页）
for act in egfr_activities:
    print(act)
```

### 2.3 数据清洗和标准化

```python
# src/medagent/data/processing/activity_cleaner.py

import pandas as pd
import numpy as np
from rdkit import Chem

class ActivityDataCleaner:
    def clean_chembl_data(self, df: pd.DataFrame) -> pd.DataFrame:
        """清洗ChEMBL活性数据"""
        # 1. 标准化SMILES
        df['mol'] = df['canonical_smiles'].apply(Chem.MolFromSmiles)
        df = df[df['mol'].notnull()]  # 移除无效SMILES
        
        # 2. 统一单位到nM
        df['value_nm'] = df.apply(self._convert_to_nm, axis=1)
        
        # 3. 转换为pActivity (pIC50, pKi等)
        df['p_activity'] = -df['value_nm'].apply(lambda x: np.log10(x * 1e-9))
        
        # 4. 过滤异常值
        df = df[(df['p_activity'] >= 3) & (df['p_activity'] <= 11)]
        
        # 5. 去重（取平均值）
        df = df.groupby(['compound_id', 'target_id', 'standard_type']).agg({
            'canonical_smiles': 'first',
            'p_activity': 'mean',
            'pubmed_id': lambda x: ';'.join(map(str, x.unique()))
        }).reset_index()
        
        return df
    
    def _convert_to_nm(self, row):
        """统一单位到nM"""
        value = row['standard_value']
        unit = row['standard_units']
        
        if unit == 'nM':
            return value
        elif unit == 'uM':
            return value * 1000
        elif unit == 'pM':
            return value / 1000
        elif unit == 'M':
            return value * 1e9
        else:
            return None
```

---

## 📚 三、文献知识库扩展

### 3.1 文献数据源

| 数据源 | 覆盖范围 | 获取方法 | API限制 |
|--------|---------|---------|---------|
| **PubMed** | 3600万+生物医学文献 | Entrez API | 3请求/秒，需API key |
| **PubMed Central (PMC)** | 800万+全文文章 | OAI-PMH或FTP | 开放获取 |
| **Europe PMC** | 4200万+摘要，700万+全文 | RESTful API | 无严格限制 |
| **bioRxiv/medRxiv** | 预印本 | API | 开放 |
| **Semantic Scholar** | 跨学科文献+引用图谱 | API（需申请key） | 100请求/5分钟 |

### 3.2 PubMed检索实现

```python
# src/medagent/data/collectors/pubmed.py

from Bio import Entrez
import time

class PubMedCollector:
    def __init__(self, email: str, api_key: str = None):
        Entrez.email = email
        if api_key:
            Entrez.api_key = api_key  # 提升到10请求/秒
    
    def search_target_literature(self, target_name: str, max_results: int = 1000):
        """检索靶点相关文献"""
        # 构建查询
        query = f'("{target_name}"[Title/Abstract]) AND (drug design OR inhibitor OR ligand OR binding)'
        
        # 限定时间范围（最近10年）
        query += ' AND ("2014/01/01"[Date - Publication] : "3000"[Date - Publication])'
        
        # 限定文章类型
        query += ' AND (Journal Article[PT] OR Review[PT])'
        
        # 搜索
        handle = Entrez.esearch(db="pubmed", term=query, retmax=max_results, sort="relevance")
        record = Entrez.read(handle)
        pmids = record["IdList"]
        
        return self.fetch_articles(pmids)
    
    def fetch_articles(self, pmids: list):
        """批量获取文章详情"""
        articles = []
        batch_size = 200
        
        for i in range(0, len(pmids), batch_size):
            batch_pmids = pmids[i:i+batch_size]
            handle = Entrez.efetch(db="pubmed", id=batch_pmids, rettype="medline", retmode="xml")
            records = Entrez.read(handle)
            
            for record in records['PubmedArticle']:
                article = self._parse_article(record)
                articles.append(article)
            
            time.sleep(0.34)  # 3请求/秒限制
        
        return articles
```

### 3.3 推荐检索主题列表

```python
# 为每个靶点准备的检索主题
SEARCH_TOPICS = {
    "EGFR": [
        "EGFR inhibitor drug design",
        "EGFR T790M resistance",
        "EGFR kinase structure activity relationship",
        "EGFR ADMET toxicity",
        "osimertinib gefitinib erlotinib mechanism",
        "EGFR binding pocket molecular docking",
    ],
    "BRAF": [
        "BRAF V600E inhibitor",
        "BRAF kinase drug design",
        "vemurafenib dabrafenib resistance",
        "BRAF paradoxical activation",
    ],
    # ... 其他靶点
}
```

### 3.4 全文PDF获取

```python
# src/medagent/data/collectors/fulltext.py

import requests
from pathlib import Path

class FullTextCollector:
    def download_pmc_pdf(self, pmcid: str, output_dir: Path):
        """从PMC下载开放获取PDF"""
        url = f"https://www.ncbi.nlm.nih.gov/pmc/articles/{pmcid}/pdf/"
        response = requests.get(url)
        
        if response.status_code == 200:
            pdf_path = output_dir / f"{pmcid}.pdf"
            pdf_path.write_bytes(response.content)
            return pdf_path
        return None
    
    def download_via_unpaywall(self, doi: str, output_dir: Path):
        """通过Unpaywall API查找开放获取版本"""
        email = "your@email.com"
        url = f"https://api.unpaywall.org/v2/{doi}?email={email}"
        response = requests.get(url)
        
        if response.status_code == 200:
            data = response.json()
            if data['is_oa'] and data['best_oa_location']:
                pdf_url = data['best_oa_location']['url_for_pdf']
                if pdf_url:
                    pdf_response = requests.get(pdf_url)
                    pdf_path = output_dir / f"{doi.replace('/', '_')}.pdf"
                    pdf_path.write_bytes(pdf_response.content)
                    return pdf_path
        return None
```

### 3.5 文献入RAG库流程

```python
# src/medagent/data/processing/literature_rag.py

from medagent.rag.chunking import PaperChunker
from medagent.rag.embedding import EmbeddingService

class LiteratureRAGBuilder:
    def ingest_paper(self, paper_info: dict, pdf_path: Path = None):
        """将文献入库"""
        # 1. 创建文档记录
        doc = RAGDocument(
            source_type='paper',
            title=paper_info['title'],
            external_id=paper_info['pmid'],
            metadata={
                'doi': paper_info.get('doi'),
                'journal': paper_info['journal'],
                'pub_date': paper_info['pub_date'],
            }
        )
        self.db.add(doc)
        self.db.flush()
        
        # 2. 提取和切分内容
        if pdf_path and pdf_path.exists():
            full_text = self._extract_pdf_text(pdf_path)
            chunks = self.chunker.chunk_paper(full_text, doc_id=doc.id)
        else:
            chunks = [{'text': paper_info['abstract'], 'section': 'abstract'}]
        
        # 3. 向量化并入库
        for chunk_data in chunks:
            embedding = self.embedder.embed_document(chunk_data['text'])
            chunk = RAGChunk(
                document_id=doc.id,
                content=chunk_data['text'],
                embedding=embedding,
                metadata={'section': chunk_data.get('section')}
            )
            self.db.add(chunk)
        
        self.db.commit()
```

---

## ⚖️ 四、专利知识库扩展

### 4.1 专利数据源

| 数据源 | 覆盖范围 | 获取方法 | 成本 |
|--------|---------|---------|------|
| **Google Patents** | 全球1.2亿+专利 | Public Datasets (BigQuery) | 免费（需GCP账号） |
| **SureChEMBL** | 化学专利（EBI维护） | PostgreSQL dump或API | 免费 |
| **USPTO** | 美国专利 | Bulk Data Download | 免费 |
| **EPO (Espacenet)** | 欧洲专利 | OPS API | 免费（需注册） |
| **Lens.org** | 全球专利+学术文献关联 | API | 学术用途免费 |

### 4.2 SureChEMBL（化学专利专用，推荐）

```python
# src/medagent/data/collectors/surechembl.py

import requests

class SureChEMBLCollector:
    BASE_URL = "https://www.surechembl.org/api"
    
    def search_by_target(self, target_name: str, max_results: int = 1000):
        """按靶点搜索专利"""
        url = f"{self.BASE_URL}/search"
        params = {
            'q': f'{target_name} inhibitor',
            'type': 'patent',
            'limit': max_results,
        }
        response = requests.get(url, params=params)
        return response.json()
    
    def search_by_structure(self, smiles: str, similarity: float = 0.85):
        """按结构相似度搜索专利"""
        url = f"{self.BASE_URL}/similarity/{smiles}"
        params = {'threshold': similarity}
        response = requests.get(url, params=params)
        return response.json()
    
    def get_patent_details(self, patent_id: str):
        """获取专利详情"""
        url = f"{self.BASE_URL}/patent/{patent_id}"
        response = requests.get(url)
        data = response.json()
        
        return {
            'patent_id': patent_id,
            'title': data['title'],
            'abstract': data['abstract'],
            'claims': data['claims'],
            'compounds': data['extracted_compounds'],
            'assignee': data['assignee'],
            'filing_date': data['filing_date'],
        }
```

### 4.3 Google Patents Public Dataset

```python
from google.cloud import bigquery

class GooglePatentsCollector:
    def __init__(self, project_id: str):
        self.client = bigquery.Client(project=project_id)
    
    def search_patents(self, keywords: list, country: str = 'US', limit: int = 10000):
        """搜索专利"""
        keyword_conditions = " OR ".join([
            f"LOWER(title_localized[0].text) LIKE '%{kw.lower()}%'"
            for kw in keywords
        ])
        
        query = f"""
        SELECT 
          publication_number,
          title_localized[0].text AS title,
          abstract_localized[0].text AS abstract,
          filing_date,
          assignee
        FROM `patents-public-data.patents.publications`
        WHERE ({keyword_conditions})
          AND country_code = '{country}'
          AND publication_date >= '2010-01-01'
        LIMIT {limit}
        """
        
        return self.client.query(query).to_dataframe()
```

### 4.4 专利化合物表提取

```python
import re
from rdkit import Chem

class PatentCompoundExtractor:
    def extract_compound_tables(self, patent_text: str):
        """从专利文本中提取化合物表"""
        # 查找Example段落
        compound_sections = re.findall(
            r'(Example \d+.*?(?=Example \d+|\Z))', 
            patent_text, 
            re.DOTALL | re.IGNORECASE
        )
        
        compounds = []
        for section in compound_sections:
            # 提取SMILES
            smiles_matches = re.findall(r'SMILES:\s*([^\s\n]+)', section)
            
            # 提取活性数据
            activity_matches = re.findall(
                r'IC50[:\s=]*([0-9.]+)\s*(nM|μM)', 
                section, 
                re.IGNORECASE
            )
            
            if smiles_matches:
                compounds.append({
                    'smiles': smiles_matches[0],
                    'ic50_value': activity_matches[0][0] if activity_matches else None,
                    'ic50_unit': activity_matches[0][1] if activity_matches else None,
                })
        
        return compounds
```

---

## 🧬 五、ADMET数据扩展

### 5.1 公开ADMET数据集

| 数据集 | 内容 | 规模 | 获取方式 |
|--------|------|------|---------|
| **ToxCast** | EPA毒性筛选 | 9000+化合物，700+测定 | \`https://www.epa.gov/chemical-research/toxicity-forecasting\` |
| **Tox21** | NIH毒性数据 | 10000+化合物，12个毒性端点 | \`https://tripod.nih.gov/tox21/\` |
| **SIDER** | 药物副作用 | 1430个药物，5880种副作用 | \`http://sideeffects.embl.de/\` |
| **hERG Central** | hERG抑制数据 | 8000+化合物 | 文献整合 |
| **DILI-score** | 药物性肝损伤 | 1200+药物 | 文献数据 |
| **ADMET Predictor DB** | 商业工具内置数据 | 数十万条 | 商业软件 |
| **MoleculeNet** | 多任务ADMET基准 | 多个子集 | \`http://moleculenet.org/\` |

### 5.2 ToxCast数据获取

```python
# src/medagent/data/collectors/toxcast.py

import pandas as pd
import requests

class ToxCastCollector:
    BASE_URL = "https://comptox.epa.gov/dashboard-api"
    
    def download_toxcast_data(self):
        """下载ToxCast数据"""
        # ToxCast提供FTP批量下载
        url = "https://www.epa.gov/sites/default/files/2021-06/toxcast_summary_table.xlsx"
        df = pd.read_excel(url)
        return df
    
    def query_compound_toxicity(self, dtxsid: str):
        """查询单个化合物的毒性数据"""
        url = f"{self.BASE_URL}/chemical/toxcast/{dtxsid}"
        response = requests.get(url)
        return response.json()
```

### 5.3 hERG数据整合

```python
# src/medagent/data/processing/herg_data.py

class hERGDataCollector:
    """整合多源hERG数据"""
    
    def collect_from_chembl(self):
        """从ChEMBL获取hERG数据"""
        # hERG靶点: CHEMBL240
        query = """
        SELECT 
          md.chembl_id,
          cs.canonical_smiles,
          act.standard_value,
          act.standard_units,
          act.pchembl_value
        FROM activities act
        JOIN molecule_dictionary md ON act.molregno = md.molregno
        JOIN compound_structures cs ON md.molregno = cs.molregno
        WHERE act.target_id = (
          SELECT tid FROM target_dictionary WHERE chembl_id = 'CHEMBL240'
        )
        AND act.standard_type IN ('IC50', 'Ki')
        """
        return self.execute_chembl_query(query)
    
    def label_herg_risk(self, ic50_um: float):
        """标记hERG风险等级"""
        if ic50_um < 1:
            return 'high_risk'
        elif ic50_um < 10:
            return 'medium_risk'
        else:
            return 'low_risk'
```

---

## 🧪 六、合成路线数据扩展

### 6.1 合成路线数据源

| 数据源 | 内容 | 获取方式 |
|--------|------|---------|
| **Reaxys** | 商业反应数据库 | 机构订阅（最全面） |
| **SciFinder** | CAS反应数据库 | 机构订阅 |
| **USPTO反应数据集** | 美国专利反应 | 公开下载 |
| **ORD (Open Reaction Database)** | 开放反应数据 | \`https://open-reaction-database.org/\` |
| **Pistachio** | NextMove整理的反应库 | 社区版可用 |

### 6.2 USPTO反应数据

```python
# USPTO数据获取
import pandas as pd

class USPTOReactionCollector:
    def download_uspto_data(self):
        """下载USPTO反应数据（Lowe提取版本）"""
        # Daniel Lowe整理的USPTO 1976-2016反应数据
        url = "https://figshare.com/articles/dataset/Chemical_reactions_from_US_patents_1976-Sep2016_/5104873"
        # 约170万反应，需要下载后本地处理
        
    def parse_reaction_smiles(self, reaction_smiles: str):
        """解析反应SMILES"""
        # 格式: reactants>agents>products
        parts = reaction_smiles.split('>')
        return {
            'reactants': parts[0],
            'agents': parts[1] if len(parts) > 1 else '',
            'products': parts[2] if len(parts) > 2 else '',
        }
```

### 6.3 Building Block数据

```python
# src/medagent/data/collectors/building_blocks.py

class BuildingBlockCollector:
    """收集可购买砌块信息"""
    
    def collect_from_zinc(self):
        """从ZINC获取可购买砌块"""
        # ZINC15 building blocks子集
        url = "https://zinc15.docking.org/substances/subsets/building-blocks/"
        # 下载SMILES和供应商信息
    
    def collect_from_emolecules(self):
        """从eMolecules获取"""
        # eMolecules提供可购买化合物API
        # https://www.emolecules.com/info/plus/download-database
```

---

## 📊 七、数据扩展实施计划

### 7.1 优先级分级

#### 高优先级（立即执行）
1. **扩展靶点到50个** - 覆盖主要疾病领域
2. **ChEMBL活性数据** - 按靶点批量导入（方案A或B）
3. **PubMed文献检索** - 每个靶点至少200篇核心文献
4. **内置知识库结构化** - 补全PDB、口袋、SAR规则

#### 中优先级（1-2周内）
5. **专利数据** - SureChEMBL按靶点检索
6. **ADMET数据** - ToxCast + Tox21 + hERG整合
7. **全文PDF获取** - Unpaywall批量下载
8. **Building Blocks** - ZINC砌块库

#### 低优先级（后续扩展）
9. **反应数据** - USPTO反应库
10. **代谢数据** - CYP底物/抑制剂数据
11. **临床试验数据** - ClinicalTrials.gov

### 7.2 实施脚本模板

```python
# scripts/expand_database.py

import argparse
from medagent.data.collectors import *
from medagent.data.processing import *

def main():
    parser = argparse.ArgumentParser()
    parser.add_argument('--targets', nargs='+', help='靶点列表')
    parser.add_argument('--mode', choices=['full', 'incremental'], default='incremental')
    args = parser.parse_args()
    
    # 1. 扩展靶点信息
    uniprot_collector = UniProtCollector()
    for target in args.targets:
        target_info = uniprot_collector.fetch_target_info(target)
        # 入库...
    
    # 2. 获取活性数据
    chembl_collector = ChEMBLCollector()
    for target in args.targets:
        activities = chembl_collector.get_activities(target)
        # 清洗并入库...
    
    # 3. 检索文献
    pubmed_collector = PubMedCollector(email="your@email.com")
    for target in args.targets:
        papers = pubmed_collector.search_target_literature(target)
        # 入RAG库...
    
    # 4. 检索专利
    surechembl_collector = SureChEMBLCollector()
    for target in args.targets:
        patents = surechembl_collector.search_by_target(target)
        # 入RAG库...

if __name__ == '__main__':
    main()
```

### 7.3 执行示例

```bash
# 扩展5个新靶点的完整数据
python scripts/expand_database.py \
  --targets HER2 MET ROS1 FGFR1 mTOR \
  --mode full

# 增量更新现有靶点
python scripts/expand_database.py \
  --targets EGFR BRAF \
  --mode incremental
```

---

## 🛠️ 八、数据质量控制

### 8.1 数据验证检查清单

- [ ] **SMILES有效性**: 所有SMILES可被RDKit解析
- [ ] **单位统一**: 活性数据统一为nM或pActivity
- [ ] **去重**: 同一化合物-靶点对取平均值
- [ ] **异常值过滤**: pActivity在3-11范围内
- [ ] **引用完整**: 每条数据有PMID或专利号
- [ ] **向量化成功**: RAG chunk都有embedding
- [ ] **元数据完整**: 文档来源、日期、作者等字段完整

### 8.2 数据统计脚本

```python
# scripts/data_stats.py

def generate_data_statistics():
    """生成数据统计报告"""
    stats = {
        'targets': {
            'total': count_targets(),
            'with_structure': count_targets_with_pdb(),
            'with_activities': count_targets_with_activities(),
        },
        'molecules': {
            'total': count_molecules(),
            'with_activities': count_molecules_with_activities(),
            'with_admet': count_molecules_with_admet(),
        },
        'rag': {
            'documents': count_rag_documents(),
            'chunks': count_rag_chunks(),
            'papers': count_documents_by_type('paper'),
            'patents': count_documents_by_type('patent'),
        },
        'activities': {
            'total': count_activities(),
            'ic50': count_activities_by_type('IC50'),
            'ki': count_activities_by_type('Ki'),
        }
    }
    return stats
```

---

## 📚 九、参考资源

### 9.1 必读文档
- ChEMBL Database Schema: https://chembl.gitbook.io/chembl-interface-documentation/
- PubMed E-utilities: https://www.ncbi.nlm.nih.gov/books/NBK25501/
- RDKit Documentation: https://www.rdkit.org/docs/
- BioPython Tutorial: https://biopython.org/wiki/Documentation

### 9.2 推荐工具
- **数据处理**: Pandas, NumPy, RDKit
- **API客户端**: requests, biopython, chembl_webresource_client
- **数据库**: PostgreSQL, pgvector
- **向量化**: text-embedding-v4 (via DashScope)

### 9.3 社区资源
- ChEMBL Blog: https://chembl.blogspot.com/
- RDKit Discussion: https://github.com/rdkit/rdkit/discussions
- Open Drug Discovery Toolkit: http://oddt.org/

---

## ✅ 完成检查清单

### 阶段一：基础扩展（2周）
- [ ] 扩展靶点到50个
- [ ] 导入ChEMBL活性数据（至少50个靶点）
- [ ] 检索PubMed文献（每靶点200+篇）
- [ ] 补全内置靶点PDB和口袋信息
- [ ] 生成数据统计报告

### 阶段二：深度扩展（4周）
- [ ] 导入专利数据（SureChEMBL）
- [ ] 整合ADMET数据（ToxCast + hERG）
- [ ] 下载全文PDF（Unpaywall）
- [ ] 建立Building Blocks库
- [ ] 完善数据质量检查

### 阶段三：高级功能（持续）
- [ ] USPTO反应库
- [ ] 代谢数据扩展
- [ ] 临床试验数据
- [ ] 自动化更新流程
- [ ] 数据版本管理

---

**文档版本**: v1.0  
**最后更新**: 2026-07-12  
**维护者**: 小分子药物设计Agent团队
