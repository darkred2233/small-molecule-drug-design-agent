# 前端修复总结

## 修复的三个问题

### 1. ✅ AgentTimeline 概览界面刷新和多轮显示问题

**问题描述：**
- 概览界面刷新不及时，节点运行完了却没有及时刷新
- 多轮运行时节点连在一起显示，界面越来越长

**修复方案：**
- **提高刷新频率**：从 2000ms 改为 1000ms，确保更及时的状态更新
- **按轮次分组显示**：每一轮单独显示，轮次之间用分隔线分开
- **最新轮次优先**：按轮次降序排列（最新的在最上面）

**修改文件：**
- `apps/web/src/components/AgentTimeline.tsx`

**关键改动：**
```typescript
// 提高刷新频率
refetchInterval: (query) =>
  query.state.data?.status === 'pipeline_running' ? 1000 : false, // 从 2000ms 改为 1000ms

// 按轮次分组
const runsByIteration = status.agent_runs.reduce((acc, run) => {
  const iteration = run.iteration ?? 1;
  if (!acc[iteration]) {
    acc[iteration] = [];
  }
  acc[iteration].push(run);
  return acc;
}, {} as Record<number, typeof status.agent_runs>);

// 显示轮次分隔线
{iterations.length > 1 && (
  <div className="mb-2 flex items-center gap-2 text-xs font-semibold text-slate-600">
    <div className="h-px flex-1 bg-slate-200"></div>
    <span>第 {iteration} 轮</span>
    <div className="h-px flex-1 bg-slate-200"></div>
  </div>
)}
```

---

### 2. ✅ 证据详情API接入和显示问题

**问题描述：**
- 证据详情界面只显示 "当前接口返回的是证据索引，完整 chunk 内容可在后续接入证据详情 API 后展示"
- 从分子详情页点击证据链接不会及时显示，需要退回主界面才显示

**修复方案：**

#### 后端：添加获取单个 chunk 详情的 API

**新增 API：**
```
GET /projects/{project_id}/rag/chunks/{chunk_id}
```

**修改文件：**
- `src/medagent/api/app.py`

**代码：**
```python
@app.get(
    "/projects/{project_id}/rag/chunks/{chunk_id}",
    response_model=RagChunkRead,
    tags=["RAG"],
    summary="Get single RAG chunk detail",
)
def get_rag_chunk(
    project_id: str,
    chunk_id: str,
    db: Session = Depends(get_db),
):
    _get_project(db, project_id)
    # Get all document IDs for this project
    document_ids = [
        document_id
        for (document_id,) in db.query(RagDocument.document_id).filter_by(project_id=project_id).all()
    ]
    if not document_ids:
        raise HTTPException(status_code=404, detail="No documents found for this project")

    # Get the chunk and verify it belongs to this project
    chunk = (
        db.query(RagChunk)
        .filter(RagChunk.chunk_id == chunk_id)
        .filter(RagChunk.document_id.in_(document_ids))
        .first()
    )

    if not chunk:
        raise HTTPException(status_code=404, detail=f"Chunk {chunk_id} not found")

    return _rag_chunk_to_read(chunk)
```

#### 前端：调用API并显示完整内容

**修改文件：**
- `apps/web/src/api/rag.ts` - 添加 API 调用
- `apps/web/src/types/api.ts` - 添加类型定义
- `apps/web/src/components/EvidenceDrawer.tsx` - 更新显示组件

**关键改动：**

1. **API 调用：**
```typescript
export const ragApi = {
  // ...
  // Get single chunk detail
  getChunk: (projectId: string, chunkId: string) =>
    apiClient.get<RagChunkRead>(`/projects/${projectId}/rag/chunks/${chunkId}`),
  // ...
};
```

2. **类型定义：**
```typescript
export interface RagChunkRead {
  chunk_id: string;
  document_id: string;
  page_number?: number;
  section?: string;
  content: string;
  embedding_model?: string;
  embedding_ref?: string;
  token_count?: number;
  metadata?: Record<string, any>;
}
```

3. **EvidenceDrawer 组件更新：**
- 使用 `useQuery` 获取 chunk 详情
- 添加 `useEffect` 自动打开抽屉（修复从分子详情页点击不显示的问题）
- 显示完整的 chunk 内容、页码、章节、token数
- 显示来源文档信息

```typescript
// 修复从分子详情页点击不显示的问题
useEffect(() => {
  if (evidenceDrawerChunkId && !evidenceDrawerOpen) {
    const store = useWorkspaceStore.getState();
    store.openEvidenceDrawer(evidenceDrawerChunkId);
  }
}, [evidenceDrawerChunkId, evidenceDrawerOpen]);

// 获取 chunk 详情
const { data: chunkDetail, isLoading: isLoadingChunk } = useQuery({
  queryKey: ['rag-chunk', projectId, evidenceDrawerChunkId],
  queryFn: () => ragApi.getChunk(projectId!, evidenceDrawerChunkId!),
  enabled: !!projectId && !!evidenceDrawerChunkId && evidenceDrawerOpen,
  staleTime: 0, // 强制刷新
});
```

**现在显示：**
- ✅ 完整的证据内容（之前只显示提示文字）
- ✅ 页码、章节、token 数等元信息
- ✅ 来源文档信息
- ✅ 从分子详情页点击后立即显示

---

### 3. ✅ 删除创建项目页面的生成策略配置

**问题描述：**
- 项目创建时选择的生成策略和个数实际上没有被应用
- 实际运行时使用的是界面顶部配置面板的参数
- 创建页面的配置是多余的，造成混淆

**修复方案：**
- 删除 `GenerationConfigPanel` 组件
- 替换为一个说明性提示，告知用户在项目创建后通过顶部配置面板设置

**修改文件：**
- `apps/web/src/components/CreateProjectModal.tsx`

**改动：**
```typescript
// 删除：
<GenerationConfigPanel
  strategyCounts={strategyCounts}
  topN={topN}
  generationSize={generationSize}
  maxAssessmentMolecules={Math.min(Math.max(maxAssessmentMolecules, topN), 500)}
  onStrategyCountChange={updateStrategyCount}
  onTopNChange={(value) => setTopN(clampInteger(value, 1, 500))}
/>

// 替换为：
<div className="rounded-lg border border-cyan-100 bg-cyan-50/30 p-4">
  <div className="text-sm text-slate-700">
    <p className="font-medium">💡 生成策略配置说明</p>
    <p className="mt-2 text-slate-600">
      生成策略和分子数量将在项目创建后，通过界面顶部的配置面板进行调整。
      每次生成时会使用当前的配置参数。
    </p>
  </div>
</div>
```

---

## 测试建议

### 测试 1：AgentTimeline 刷新和多轮显示

1. 创建一个新项目
2. 运行分子生成任务
3. 观察概览界面：
   - ✅ 节点状态应该在 1 秒内更新
   - ✅ 看到 "第 1 轮" 的分隔线
4. 再次运行生成（第二轮）
5. 观察概览界面：
   - ✅ 看到 "第 2 轮" 和 "第 1 轮" 分隔线
   - ✅ 第 2 轮在上面，第 1 轮在下面
   - ✅ 两轮之间清晰分隔，不会混在一起

### 测试 2：证据详情显示

**测试 2a：从主界面点击证据**
1. 在主界面找到有证据链接的分子
2. 点击证据 ID（如 `DB:SYNTHESIS:MOL-xxx`）
3. 检查右侧抽屉：
   - ✅ 立即打开
   - ✅ 显示完整的证据内容（不是提示文字）
   - ✅ 显示页码、章节、token 数
   - ✅ 显示来源文档信息

**测试 2b：从分子详情页点击证据**
1. 点击分子进入详情页
2. 找到证据链接并点击
3. 检查：
   - ✅ 立即打开右侧证据抽屉（不需要退回主界面）
   - ✅ 显示完整内容

### 测试 3：创建项目页面

1. 点击"创建新项目"
2. 观察表单：
   - ✅ 不再有生成策略个数的配置选项
   - ✅ 看到说明文字："生成策略和分子数量将在项目创建后，通过界面顶部的配置面板进行调整"
3. 创建项目后：
   - ✅ 使用顶部配置面板设置生成策略
   - ✅ 运行生成任务，验证使用的是顶部配置的参数

---

## 需要重启的服务

**后端**（添加了新的 API）：
```cmd
cd C:\Users\zhihong\Desktop\small-molecule-drug-design-agent
set PYTHONPATH=src
.venv\Scripts\python.exe -m uvicorn medagent.api.app:create_app --factory --host 127.0.0.1 --port 8000 --reload
```

**前端**（修改了组件）：
```cmd
cd C:\Users\zhihong\Desktop\small-molecule-drug-design-agent\apps\web
npm run dev
```

---

## 修改的文件总结

### 后端（1 个文件）
- `src/medagent/api/app.py` - 添加获取单个 chunk 详情的 API

### 前端（4 个文件）
- `apps/web/src/components/AgentTimeline.tsx` - 提高刷新频率，按轮次分组显示
- `apps/web/src/components/EvidenceDrawer.tsx` - 调用新 API 显示完整内容，修复显示时机
- `apps/web/src/components/CreateProjectModal.tsx` - 删除生成策略配置
- `apps/web/src/api/rag.ts` - 添加 getChunk API 调用
- `apps/web/src/types/api.ts` - 添加 RagChunkRead 类型定义

---

## 完成状态

✅ **问题 1**: AgentTimeline 刷新和多轮显示 - 已修复  
✅ **问题 2**: 证据详情 API 接入和显示 - 已修复  
✅ **问题 3**: 删除创建项目的生成策略配置 - 已修复  

所有修改已完成，请重启前后端服务后测试！
