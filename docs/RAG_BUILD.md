# RAG 建库与检索开发记录

日期：2026-07-09

本次完成 M3 的可运行 RAG MVP：文档入库、网页爬取、chunk 切分、向量化、BM25 + 向量混合召回、重排、证据编号与 API/CLI 入口。

## 1. 当前实现状态

已完成：

- 新增 RAG 包：
  - `src/medagent/rag/chunking.py`：文本清洗和 chunk 切分。
  - `src/medagent/rag/embedding.py`：本地哈希向量 + 可选 DashScope `text-embedding-v4`。
  - `src/medagent/rag/retrieval.py`：BM25 + 向量召回。
  - `src/medagent/rag/rerank.py`：本地重排 + 可选 DashScope `qwen3-rerank`。
- 新增编排服务：`src/medagent/services/rag.py`。
- `rag_chunks` 增加：
  - `embedding_json`
  - `token_count`
  - `metadata_json`
- PostgreSQL 启动迁移会尝试创建 `vector` 扩展、`embedding_vector vector(2048)` 和 `ivfflat` 索引。
- `/projects/{project_id}/ingest` 会自动：
  - 解析上传文件。
  - 入库内置靶点-药物知识。
  - 对 RAG 文本资料切 chunk、向量化并保存。
- 新增独立 RAG API：

```http
POST /projects/{project_id}/rag/build
POST /projects/{project_id}/rag/crawl
POST /projects/{project_id}/rag/query
GET  /projects/{project_id}/rag/documents
GET  /projects/{project_id}/rag/chunks
GET  /projects/{project_id}/evidence-links
```

- 新增 CLI：

```powershell
medagent rag build --project-id PROJ-...
medagent rag crawl --project-id PROJ-... --url https://example.com/review
medagent rag query --project-id PROJ-... --query "EGFR quinazoline hERG risk"
```

## 2. 数据来源

当前支持：

- 内置靶点-药物库：按项目靶点写入 `builtin_target` RAG document。
- 用户上传文本资料：
  - `.txt`
  - `.md`
  - `.markdown`
  - `.pdf`
  - `.docx`
  - `.html`
- URL 爬取：支持 `http` / `https` 静态页面。

`.smi` 和 `.smiles` 仍按种子配体导入，不直接入 RAG，避免把分子结构文件当普通文本证据。

PDF 正文解析会优先使用可选依赖 `pypdf`：

```powershell
python -m pip install -e ".[dev,rag]"
```

如果未安装 `pypdf`，系统会退回到轻量文本兜底解析，适合测试链路，不适合高质量论文抽取。

## 3. 向量化策略

默认无需 API Key：

- 使用 `local-hash-embedding`
- 维度默认 2048
- 结果写入 `rag_chunks.embedding_json`
- 检索时在应用层计算余弦相似度

配置千问/DashScope 后：

- `MEDAGENT_DASHSCOPE_API_KEY` 非空时，向量化自动切到 `text-embedding-v4`。
- 兼容模式地址默认：

```text
https://dashscope.aliyuncs.com/compatible-mode/v1
```

`.env` 示例：

```env
MEDAGENT_DASHSCOPE_API_KEY="sk-..."
MEDAGENT_EMBEDDING_MODEL="text-embedding-v4"
MEDAGENT_RAG_EMBEDDING_DIMENSION=2048
MEDAGENT_DASHSCOPE_COMPATIBLE_BASE_URL="https://dashscope.aliyuncs.com/compatible-mode/v1"
```

## 4. 重排策略

默认无需 API Key：

- 使用混合召回分数顺序作为本地重排。

配置 `qwen3-rerank` 后：

```env
MEDAGENT_DASHSCOPE_API_KEY="sk-..."
MEDAGENT_RERANK_MODEL="qwen3-rerank"
MEDAGENT_DASHSCOPE_RERANK_URL="你的 DashScope rerank endpoint"
```

说明：DashScope 的 rerank API 在不同工作空间/开通方式下 endpoint 可能不同，所以这里显式配置 `MEDAGENT_DASHSCOPE_RERANK_URL`，避免把供应商路径硬编码死。

## 5. 检索流程

每次 `POST /projects/{project_id}/rag/query` 会：

1. 对 query 向量化。
2. 向量召回 Top 80。
3. BM25 关键词召回 Top 80。
4. 合并去重并计算混合分数。
5. 使用本地或远程 rerank 得到 Top K。
6. 为返回 chunk 创建 `evidence_links` 记录。

响应中每条证据包含：

- `chunk_id`
- `document_id`
- `source_type`
- `title`
- `source`
- `page`
- `section`
- `vector_score`
- `keyword_score`
- `combined_score`
- `rerank_score`
- `evidence_id`
- `evidence_summary`
- `content`

## 6. 与排序模块的衔接

`candidate_ranking` 已读取 `evidence_links`：

- 在 `score_breakdown.rag_evidence` 中记录 `evidence_ids`、`chunk_ids`、`claim_types` 和证据数。
- 如果某分子已有 RAG evidence link，`evidence_confidence` 会增加小幅 bonus。

后续如果要做更强的文献证据加权，可以在现有 `rag_evidence` component 内扩展，不需要改前端 schema。

## 7. 已验证测试

已执行：

```text
.\.venv\Scripts\python.exe -m pytest -q
.\.venv\Scripts\python.exe -m ruff check .
```

结果：

```text
38 passed, 1 warning
All checks passed!
```

warning 来自 FastAPI/TestClient 依赖链中的 Starlette deprecation，不是业务失败。
