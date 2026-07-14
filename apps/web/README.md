# Frontend Web Application

小分子药物设计 Agent 前端应用

## 技术栈

- **框架**: Vite + React 18 + TypeScript
- **路由**: React Router v6
- **状态管理**: Zustand
- **数据获取**: TanStack Query (React Query)
- **样式**: Tailwind CSS + shadcn/ui
- **图标**: Lucide React
- **分子渲染**: SmilesDrawer
- **图表**: Recharts

## 项目结构

```
src/
├── api/              # API 客户端
├── components/       # React 组件
├── pages/           # 页面组件
├── state/           # Zustand stores
├── types/           # TypeScript 类型定义
├── utils/           # 工具函数
└── hooks/           # 自定义 React hooks
```

## 开发

```bash
# 安装依赖
npm install

# 启动开发服务器
npm run dev

# 构建生产版本
npm run build

# 预览生产构建
npm run preview

# 代码检查
npm run lint

# 运行测试
npm test

# E2E 测试
npm run test:e2e
```

## 环境变量

创建 `.env.local` 文件：

```env
VITE_API_BASE_URL=http://localhost:8000/api
```

## API 代理

开发环境下，Vite 会将 `/api` 请求代理到后端服务器（默认 `http://localhost:8000`）。

## 核心功能

### 第一阶段：项目壳和基础对话 ✅
- 三栏布局（左侧项目列表、中间对话、右侧工作台）
- 靶点选择和项目创建
- GPT 式自然语言对话
- 约束 chips 展示

### 第二阶段：工作台和文件管理
- 文件拖拽上传
- RAG 文档和证据展示
- Agent 执行时间线
- 工具状态监控

### 第三阶段：分子结果展示
- 分子表格和排名
- 分子详情页（2D 结构、性质、评分）
- DecisionCard 展示
- ReasoningTrace 和证据链
- Docking/ADMET/合成可及性结果

### 第四阶段：优化闭环和测试
- Advisor 建议面板
- 一键应用下一轮约束
- 新一轮优化
- PDF 报告查看
- Playwright E2E 测试

## 开发指南

### 添加新页面

1. 在 `src/pages/` 创建页面组件
2. 在 `App.tsx` 添加路由
3. 在页面中使用 API hooks 获取数据

### 添加新 API

1. 在 `src/api/` 创建 API 模块
2. 在 `src/types/api.ts` 添加类型定义
3. 导出到 `src/api/index.ts`

### 状态管理

使用 Zustand 管理全局状态：

```typescript
import { useWorkspaceStore } from '@/state/workspaceStore';

function MyComponent() {
  const { currentProject, setCurrentProject } = useWorkspaceStore();
  // ...
}
```

### 数据获取

使用 TanStack Query hooks：

```typescript
import { useQuery } from '@tanstack/react-query';
import { projectsApi } from '@/api';

function MyComponent() {
  const { data, isLoading } = useQuery({
    queryKey: ['projects'],
    queryFn: projectsApi.list,
  });
  // ...
}
```

## 部署

```bash
# 构建
npm run build

# 部署 dist/ 目录到静态服务器
# 或使用 Nginx/Apache 配置 SPA 路由
```

## License

Private
