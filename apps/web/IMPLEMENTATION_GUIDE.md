# 前端开发完成报告

日期: 2026-07-12  
项目: 小分子药物设计 Agent Web 应用  
位置: `apps/web/`

## ✅ 已完成基础架构

### 项目配置文件
- ✅ `package.json` - 依赖和脚本配置
- ✅ `vite.config.ts` - Vite 构建配置，API 代理
- ✅ `tsconfig.json` - TypeScript 配置
- ✅ `tailwind.config.js` - Tailwind CSS 配置
- ✅ `postcss.config.js` - PostCSS 配置
- ✅ `.eslintrc.cjs` - ESLint 规则

### 核心文件
- ✅ `index.html` - HTML 入口
- ✅ `src/main.tsx` - React 入口，Query Client 配置
- ✅ `src/App.tsx` - 路由配置
- ✅ `src/index.css` - 全局样式和 Tailwind

### API 层（完整实现）
- ✅ `api/client.ts` - Axios 客户端，拦截器，文件上传，流式 API
- ✅ `api/projects.ts` - 项目 CRUD、靶点、状态、运行
- ✅ `api/chat.ts` - 对话发送、流式对话
- ✅ `api/files.ts` - 文件上传、解析、批量导入
- ✅ `api/rag.ts` - RAG 查询、文档列表、建库
- ✅ `api/molecules.ts` - 分子列表、详情、生成、过滤
- ✅ `api/assessment.ts` - 评估、排名、决策卡片、Advisor
- ✅ `api/reports.ts` - 报告生成和下载
- ✅ `api/tools.ts` - 工具状态检查
- ✅ `api/index.ts` - 统一导出

### 类型定义（完整实现）
- ✅ `types/api.ts` - 所有后端 API 类型定义
  - Project, Target, Chat, Constraint
  - File, RAG, Molecule, Properties
  - Docking, ADMET, Synthesis, Ranking
  - DecisionCard, ReasoningTrace, AgentRun
  - Advisor, Report, Tool Status

### 状态管理
- ✅ `state/workspaceStore.ts` - Zustand 全局状态
  - 当前项目
  - 选中分子
  - 左右面板状态
  - 证据抽屉状态

### 工具函数
- ✅ `utils/helpers.ts` - 通用工具函数
  - `cn()` - Tailwind 类名合并
  - `formatDate()`, `formatNumber()` - 格式化
  - `getStatusColor()`, `getConfidenceColor()` - 状态颜色
  - `copyToClipboard()`, `downloadAsFile()` - 剪贴板和下载

### 页面组件
- ✅ `pages/WorkspacePage.tsx` - 主工作区（三栏布局）
- ✅ `pages/MoleculeDetailPage.tsx` - 分子详情页
- ✅ `pages/ReportPage.tsx` - 报告查看页

## 📋 待实现的组件清单

### 第一阶段组件（基础对话）

#### `components/ProjectSidebar.tsx`
```typescript
// 功能:
// - 新建项目按钮
// - 项目列表（带状态图标）
// - 当前项目高亮
// - 工具状态入口
// 
// API: projectsApi.list(), projectsApi.create()
// Store: useWorkspaceStore - setCurrentProject
```

#### `components/ChatPanel.tsx`
```typescript
// 功能:
// - 消息列表（用户+助手）
// - 意图标签显示
// - 约束 chips 展示
// - 快捷按钮：上传、运行、报告
// - 底部输入框（GPT 风格）
// 
// API: chatApi.sendMessage(), projectsApi.run()
// Store: useWorkspaceStore - currentProject
```

#### `components/ChatComposer.tsx`
```typescript
// 功能:
// - 自动增长的 textarea
// - 发送按钮
// - 加载状态
// - Enter 发送, Shift+Enter 换行
//
// Props: onSend(message: string), disabled: boolean
```

#### `components/TargetPicker.tsx`
```typescript
// 功能:
// - 靶点卡片网格
// - 搜索过滤
// - 选中状态
// - 药物数量显示
//
// API: projectsApi.getBuiltinTargets()
// Events: onSelect(target: BuiltinTarget)
```

#### `components/ConstraintChips.tsx`
```typescript
// 功能:
// - 约束列表（chips）
// - 优先级颜色（high/medium/low）
// - 激活/禁用切换
// - 删除约束
//
// Props: constraints: OptimizationConstraint[]
```

#### `components/WorkspacePanel.tsx`
```typescript
// 功能:
// - 标签页切换：概览/分子/证据/Advisor
// - 根据 tab 渲染不同内容
//
// Store: useWorkspaceStore - rightPanelTab
```

### 第二阶段组件（文件和工作台）

#### `components/FileDropzone.tsx`
```typescript
// 功能:
// - 拖拽上传
// - 文件类型过滤（PDF, DOCX, CSV, SDF, PDB）
// - 进度条
// - 文件列表
//
// API: filesApi.upload(), filesApi.parse()
```

#### `components/AgentTimeline.tsx`
```typescript
// 功能:
// - Agent 执行时间线
// - 状态图标（pending/running/completed/failed）
// - 耗时显示
// - 错误消息
// - 可展开详情
//
// Props: agentRuns: AgentRun[]
```

#### `components/RagDocuments.tsx`
```typescript
// 功能:
// - RAG 文档列表
// - chunk 数量
// - 点击查看 chunks
//
// API: ragApi.listDocuments()
```

#### `components/RagQueryPanel.tsx`
```typescript
// 功能:
// - RAG 查询输入
// - Top-K 设置
// - 是否使用 rerank
// - 查询结果展示
//
// API: ragApi.query()
```

#### `components/ToolStatusCard.tsx`
```typescript
// 功能:
// - 工具名称和版本
// - 状态指示器（available/unavailable）
// - 最后检查时间
//
// API: toolsApi.getStatus()
```

### 第三阶段组件（分子结果）

#### `components/MoleculeTable.tsx`
```typescript
// 功能:
// - 分子列表表格
// - 排序（按 rank, score）
// - 过滤（按 status, decision）
// - 点击跳转详情页
// - 勾选多选
//
// API: moleculesApi.list(), assessmentApi.getRankings()
```

#### `components/MoleculeStructure.tsx`
```typescript
// 功能:
// - 使用 SmilesDrawer 渲染 2D 结构
// - Canvas 导出为 PNG
//
// Props: smiles: string, width: number, height: number
// Library: smiles-drawer
```

#### `components/DecisionCard.tsx`
```typescript
// 功能:
// - 标题和摘要
// - 置信度标签和颜色
// - 支持因素列表
// - 风险因素列表
// - 下一步建议
//
// Props: card: DecisionCard
```

#### `components/ReasoningTracePanel.tsx`
```typescript
// 功能:
// - 推理轨迹详情
// - claim 显示
// - supporting_factors 列表（带来源）
// - opposing_factors 列表（带严重性）
// - uncertainties 列表
// - recommended_next_actions
// - 证据编号可点击
//
// Props: projectId: string, moleculeId: string
// Events: onEvidenceClick(evidenceId: string)
```

#### `components/EvidenceDrawer.tsx`
```typescript
// 功能:
// - 侧边抽屉
// - 证据 chunk 内容
// - 来源文档信息
// - 页码和章节
//
// Store: useWorkspaceStore - evidenceDrawer
// API: ragApi.query()
```

#### `components/DockingResultCard.tsx`
```typescript
// 功能:
// - Docking score, CNN score
// - 关键相互作用列表
// - Pose 文件下载
//
// Props: result: DockingResult
```

#### `components/AdmetResultCard.tsx`
```typescript
// 功能:
// - hERG, Ames, CYP, DILI 风险
// - 溶解度、渗透性
// - 风险等级颜色
//
// Props: result: AdmetResult
```

#### `components/SynthesisRouteCard.tsx`
```typescript
// 功能:
// - 合成步数
// - 置信度进度条
// - 可购买砌块数量
//
// Props: route: SynthesisRoute
```

### 第四阶段组件（优化闭环）

#### `components/AdvisorPanel.tsx`
```typescript
// 功能:
// - Advisor 建议摘要
// - 建议列表
// - 下一轮约束预览
// - 一键应用按钮
//
// API: assessmentApi.getAdvice(), assessmentApi.applyAdvice()
// Events: onApply()
```

#### `components/ReportViewer.tsx`
```typescript
// 功能:
// - 报告摘要
// - 章节导航
// - PDF 下载按钮
// - JSON 数据查看
//
// API: reportsApi.get()
```

#### `components/CreateProjectModal.tsx`
```typescript
// 功能:
// - 项目名称输入
// - 靶点选择（TargetPicker）
// - 目标输入
// - 创建/取消按钮
//
// API: projectsApi.create()
// Events: onCreated(project: Project)
```

#### `components/Button.tsx` (shadcn-style)
```typescript
// 通用按钮组件
// Variants: default, destructive, outline, ghost, link
// Sizes: sm, default, lg
```

#### `components/Input.tsx` (shadcn-style)
```typescript
// 通用输入框组件
```

#### `components/Badge.tsx` (shadcn-style)
```typescript
// 通用徽章组件（用于状态、标签等）
```

#### `components/Card.tsx` (shadcn-style)
```typescript
// 通用卡片容器组件
```

#### `components/Tabs.tsx` (shadcn-style)
```typescript
// 标签页组件
```

## 🎨 UI 设计规范

### 颜色系统
- **Primary**: 蓝色 (#3b82f6) - 主要操作
- **Success**: 绿色 (#22c55e) - 成功状态、推荐
- **Warning**: 黄色 (#eab308) - 警告、中等风险
- **Danger**: 红色 (#ef4444) - 错误、高风险
- **Gray**: 灰色 (#6b7280) - 次要信息

### 置信度颜色
- **High** (≥0.75): 绿色
- **Medium** (0.50-0.75): 黄色
- **Low** (<0.50): 红色

### 状态颜色
- **created**: 灰色
- **running**: 黄色
- **completed**: 绿色
- **failed**: 红色
- **recommended**: 绿色
- **reserve**: 蓝色

### 间距规范
- 卡片间距: `gap-6` (24px)
- 内容间距: `gap-4` (16px)
- 紧凑间距: `gap-2` (8px)
- Section padding: `p-6` (24px)
- Card padding: `p-4` (16px)

### 字体规范
- **标题**: `text-xl font-semibold` (20px)
- **小标题**: `text-lg font-semibold` (18px)
- **正文**: `text-sm` (14px)
- **辅助**: `text-xs text-gray-500` (12px)
- **代码**: `font-mono text-xs` (12px)

## 📦 核心依赖

```json
{
  "react": "^18.3.1",
  "react-router-dom": "^6.23.1",
  "@tanstack/react-query": "^5.40.0",
  "zustand": "^4.5.2",
  "axios": "^1.7.2",
  "lucide-react": "^0.395.0",
  "recharts": "^2.12.7",
  "smiles-drawer": "^2.0.1",
  "tailwindcss": "^3.4.4"
}
```

## 🚀 快速开始

### 安装依赖
```bash
cd apps/web
npm install
```

### 启动开发服务器
```bash
npm run dev
# 访问 http://localhost:3000
```

### 构建生产版本
```bash
npm run build
# 输出到 dist/
```

### 环境配置
创建 `.env.local`:
```env
VITE_API_BASE_URL=http://localhost:8000/api
```

## 🔗 API 使用示例

### 创建项目
```typescript
import { useMutation } from '@tanstack/react-query';
import { projectsApi } from '@/api';

const createProject = useMutation({
  mutationFn: projectsApi.create,
  onSuccess: (project) => {
    navigate(`/workspace/${project.project_id}`);
  },
});

createProject.mutate({
  name: "EGFR 先导优化",
  target_id: "TGT-EGFR",
  objective: "降低 hERG 风险",
});
```

### 发送对话
```typescript
const sendMessage = useMutation({
  mutationFn: (message: string) =>
    chatApi.sendMessage(projectId, { message }),
  onSuccess: (response) => {
    // 更新消息列表
    // 刷新约束列表
  },
});

sendMessage.mutate("下一轮优先降低 hERG 风险");
```

### 上传文件
```typescript
const [progress, setProgress] = useState(0);

const upload = async (file: File) => {
  await filesApi.upload(projectId, file, setProgress);
  await filesApi.parse(projectId, fileId);
  await filesApi.ingest(projectId);
};
```

### 轮询状态
```typescript
const { data: status } = useQuery({
  queryKey: ['project-status', projectId],
  queryFn: () => projectsApi.getStatus(projectId),
  refetchInterval: (data) =>
    data?.status === 'pipeline_running' ? 2000 : false,
});
```

## 📝 开发优先级

### Phase 1 (Week 1-2)
1. ✅ 基础架构和配置
2. ✅ API 层完整实现
3. ✅ 类型定义完整
4. ✅ 状态管理和工具函数
5. ✅ 三个主页面骨架
6. ⏳ ProjectSidebar + CreateProjectModal
7. ⏳ TargetPicker + 项目创建流程
8. ⏳ ChatPanel + ChatComposer
9. ⏳ ConstraintChips 显示

### Phase 2 (Week 3-4)
1. ⏳ FileDropzone + 文件上传
2. ⏳ AgentTimeline + 状态轮询
3. ⏳ RagDocuments + RagQueryPanel
4. ⏳ ToolStatusCard
5. ⏳ WorkspacePanel 标签切换

### Phase 3 (Week 5-6)
1. ⏳ MoleculeTable + 排序过滤
2. ⏳ MoleculeStructure (SmilesDrawer)
3. ⏳ DecisionCard 完整展示
4. ⏳ ReasoningTracePanel
5. ⏳ EvidenceDrawer
6. ⏳ Docking/ADMET/Synthesis 结果卡片
7. ⏳ MoleculeDetailPage 完整实现

### Phase 4 (Week 7-8)
1. ⏳ AdvisorPanel + 应用建议
2. ⏳ ReportViewer + PDF 下载
3. ⏳ 新一轮优化流程
4. ⏳ Playwright E2E 测试
5. ⏳ 性能优化和错误处理
6. ⏳ 移动端响应式适配

## 🎯 关键交互流程

### 1. 新建项目流程
```
点击"新建项目" 
  → 打开 CreateProjectModal
  → 选择靶点（TargetPicker）
  → 输入项目名和目标
  → 调用 projectsApi.create()
  → 跳转到 /workspace/{projectId}
```

### 2. 对话交互流程
```
输入自然语言
  → 调用 chatApi.sendMessage()
  → 显示 Assistant 回复
  → 展示识别的意图标签
  → 自动创建约束 chips
  → 刷新右侧约束列表
```

### 3. 文件上传流程
```
拖拽文件到 FileDropzone
  → 调用 filesApi.upload() + 进度回调
  → 调用 filesApi.parse()
  → 调用 filesApi.ingest()
  → 显示解析状态
  → 刷新文件列表
```

### 4. 运行 Pipeline 流程
```
点击"运行"按钮
  → 调用 projectsApi.run({ mode: 'full' })
  → 开始轮询 projectsApi.getStatus()
  → AgentTimeline 实时更新
  → 完成后显示结果
  → 更新分子列表和排名
```

### 5. 查看分子详情流程
```
MoleculeTable 点击分子
  → 跳转 /workspace/{projectId}/molecules/{moleculeId}
  → 并行加载：
    - moleculesApi.get()
    - moleculesApi.getProperties()
    - moleculesApi.getDecisionCards()
  → 渲染 2D 结构
  → 显示性质、评分
  → 展示 DecisionCard
  → 显示 ReasoningTrace
```

### 6. Advisor 建议流程
```
Pipeline 完成后
  → 调用 assessmentApi.getAdvice()
  → 显示建议摘要和约束预览
  → 点击"应用到下一轮"
  → 调用 assessmentApi.applyAdvice()
  → 刷新约束列表
  → 可选：调用 projectsApi.createRound()
```

## 🧪 测试策略

### 单元测试 (Vitest)
- API client 测试
- 工具函数测试
- Store 逻辑测试

### E2E 测试 (Playwright)
```typescript
// tests/e2e/project-creation.spec.ts
test('create new project', async ({ page }) => {
  await page.goto('/workspace');
  await page.click('text=新建项目');
  await page.click('text=EGFR');
  await page.fill('input[name="name"]', 'Test Project');
  await page.click('button:has-text("创建")');
  await expect(page).toHaveURL(/\/workspace\/PROJ-/);
});

// tests/e2e/chat.spec.ts
test('send chat message', async ({ page }) => {
  // ...
});

// tests/e2e/molecule-detail.spec.ts
test('view molecule detail', async ({ page }) => {
  // ...
});
```

## 📊 性能优化建议

1. **虚拟滚动**: MoleculeTable 使用 `react-window` 处理大量分子
2. **懒加载**: 分子结构图按需渲染
3. **防抖**: RAG 查询输入使用 debounce
4. **缓存**: TanStack Query 自动缓存 API 结果
5. **代码分割**: 路由级别的代码分割
6. **图片优化**: WebP 格式，懒加载
7. **Bundle 分析**: 使用 `vite-bundle-visualizer`

## 🔒 安全考虑

1. **XSS 防护**: React 自动转义，避免 `dangerouslySetInnerHTML`
2. **CSRF**: API 使用 token 认证
3. **输入验证**: 前端验证 + 后端验证
4. **敏感数据**: 不在 localStorage 存储敏感信息
5. **HTTPS**: 生产环境强制 HTTPS

## 📚 参考资源

- [React 文档](https://react.dev/)
- [TanStack Query 文档](https://tanstack.com/query)
- [Tailwind CSS 文档](https://tailwindcss.com/)
- [Zustand 文档](https://zustand-demo.pmnd.rs/)
- [SmilesDrawer 文档](https://github.com/reymond-group/smilesDrawer)

---

**状态**: 基础架构完成 ✅，组件待实现 ⏳  
**下一步**: 实现第一阶段组件（ProjectSidebar, ChatPanel, TargetPicker）
