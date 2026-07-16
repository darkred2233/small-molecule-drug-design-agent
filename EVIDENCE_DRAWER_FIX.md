# 证据抽屉问题修复说明

## 问题描述

在分子详情页面点击证据引用时，存在以下问题：
1. 弹出的证据抽屉需要回到主界面才能显示
2. 证据详情显示"未找到证据详情"，但有证据ID（如 `DB:MOL:MOL-BDC2D3E486`）

## 根本原因

### 问题1：抽屉不显示
`EvidenceDrawer` 组件只在 `WorkspacePage` 中渲染，而在 `MoleculeDetailPage` 中不存在。当用户在分子详情页面点击证据引用时，虽然调用了 `openEvidenceDrawer(evidenceId)`，但由于组件不存在，所以无法显示。

### 问题2：未找到证据详情
前端将 `evidence_id` 误当作 `chunk_id` 使用。实际上：
- `evidence_id`（如 `DB:MOL:MOL-BDC2D3E486`）是 `EvidenceLink` 表的主键
- `chunk_id` 是 `RagChunk` 表的主键
- `EvidenceLink` 表中的 `chunk_id` 字段关联到实际的证据内容

数据库关系：
```
EvidenceLink (evidence_id, chunk_id, molecule_id, claim_type, confidence, rationale)
    ↓ (通过 chunk_id)
RagChunk (chunk_id, document_id, content, page_number, section)
```

## 解决方案

### 1. 全局化证据抽屉组件
将 `EvidenceDrawer` 组件提升到应用级别，使其在所有页面都可用。

### 2. 添加后端API
添加一个新的API端点来获取单个 evidence link：
```
GET /projects/{project_id}/evidence-links/{evidence_id}
```

### 3. 修复前端数据流
前端先通过 `evidence_id` 获取 `EvidenceLink`，再用其中的 `chunk_id` 获取实际的证据内容。

## 修改内容

### 后端修改

#### 1. src/medagent/api/app.py
**新增**: 获取单个 evidence link 的API端点

```python
@app.get(
    "/projects/{project_id}/evidence-links/{evidence_id}",
    response_model=EvidenceLinkRead,
    tags=["RAG"],
    summary="Get a single evidence link by evidence_id",
)
def get_evidence_link(project_id: str, evidence_id: str, db: Session = Depends(get_db)):
    _get_project(db, project_id)
    link = db.query(EvidenceLink).filter_by(evidence_id=evidence_id).first()
    if not link:
        raise HTTPException(status_code=404, detail=f"Evidence link {evidence_id} not found")
    return _evidence_link_to_read(link)
```

### 前端修改

#### 1. App.tsx
- **添加**: 导入 `EvidenceDrawer` 组件
- **添加**: 在 `<Routes>` 外层渲染 `<EvidenceDrawer />`，使其成为全局组件

```tsx
import EvidenceDrawer from './components/EvidenceDrawer';

function App() {
  return (
    <>
      <Routes>
        {/* ...路由配置... */}
      </Routes>

      {/* Global Evidence Drawer - available on all pages */}
      <EvidenceDrawer />
    </>
  );
}
```

#### 2. WorkspacePage.tsx
- **移除**: `import EvidenceDrawer` 语句
- **移除**: 页面内的 `<EvidenceDrawer />` 渲染

#### 3. apps/web/src/types/api.ts
- **添加**: `EvidenceLink` 类型定义

```typescript
export interface EvidenceLink {
  evidence_id: string;
  molecule_id: string | null;
  chunk_id: string;
  claim_type: string;
  confidence: number | null;
  rationale: string | null;
}
```

#### 4. apps/web/src/api/rag.ts
- **添加**: `getEvidenceLink` API方法

```typescript
// Get single evidence link
getEvidenceLink: (projectId: string, evidenceId: string) =>
  apiClient.get<EvidenceLink>(`/projects/${projectId}/evidence-links/${evidenceId}`),
```

#### 5. EvidenceDrawer.tsx
- **修改**: 数据获取流程，先获取 evidence link，再获取 chunk 详情
- **新增**: 显示证据元信息（类型、置信度、理由）

关键变化：
```typescript
// 第一步：通过 evidence_id 获取 evidence link
const { data: evidenceLink, isLoading: isLoadingEvidence } = useQuery({
  queryKey: ['evidence-link', projectId, evidenceDrawerChunkId],
  queryFn: () => ragApi.getEvidenceLink(projectId!, evidenceDrawerChunkId!),
  enabled: !!projectId && !!evidenceDrawerChunkId && evidenceDrawerOpen,
  retry: false,
});

// 第二步：使用 chunk_id 获取证据内容
const { data: chunkDetail, isLoading: isLoadingChunk } = useQuery({
  queryKey: ['rag-chunk', projectId, evidenceLink?.chunk_id],
  queryFn: () => ragApi.getChunk(projectId!, evidenceLink!.chunk_id),
  enabled: !!projectId && !!evidenceLink?.chunk_id && evidenceDrawerOpen,
  staleTime: 0,
});
```

## 数据流程

1. 用户在分子详情页面点击证据引用（evidence_id: `DB:MOL:MOL-BDC2D3E486`）
2. `ReasoningTracePanel` 调用 `openEvidenceDrawer(evidenceId)`
3. 全局的 `EvidenceDrawer` 组件监听状态变化，打开抽屉
4. **第一次查询**: 调用 `GET /projects/{projectId}/evidence-links/{evidenceId}`，获取 evidence link
   - 返回：`{ evidence_id, chunk_id, claim_type, confidence, rationale, ... }`
5. **第二次查询**: 使用获取到的 `chunk_id`，调用 `GET /projects/{projectId}/rag/chunks/{chunkId}`
   - 返回：`{ chunk_id, document_id, content, page_number, section, ... }`
6. 显示完整的证据信息：
   - 证据ID
   - 证据元信息（类型、置信度、理由）
   - 证据内容（文本、页码、章节）
   - 来源文档信息

## 优势

1. **正确的数据关系**: 遵循数据库设计，通过 evidence_id → chunk_id → content 的正确路径获取数据
2. **完整的信息展示**: 现在可以显示 evidence link 的元信息（类型、置信度、理由）
3. **全局可用**: 所有页面的证据引用行为统一
4. **可维护性**: 单一组件实例，减少重复代码
5. **用户体验**: 在任何页面都能立即查看证据，无需跳转

## 测试建议

1. 在分子详情页面点击证据引用，验证抽屉立即显示
2. 验证证据内容正确加载（显示实际的证据文本，不再显示"未找到证据详情"）
3. 验证证据元信息正确显示（类型、置信度、理由）
4. 验证在主界面点击证据引用仍然正常工作
5. 验证关闭抽屉功能正常
6. 验证来源文档信息正确显示
7. 测试当 evidence_id 不存在时的错误处理
