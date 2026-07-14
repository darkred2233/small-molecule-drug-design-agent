/**
 * Chat Panel Component
 *
 * Main chat interface with message history and composer
 */

import { useState, useRef, useEffect } from 'react';
import { useParams } from 'react-router-dom';
import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query';
import { chatApi, projectsApi, assessmentApi } from '@/api';
import { useWorkspaceStore } from '@/state/workspaceStore';
import { Play, FileText, Loader2, Bot, Sparkles, Gauge } from 'lucide-react';
import ChatComposer from './ChatComposer';
import ConstraintChips from './ConstraintChips';
import DesignGuidancePanel from './DesignGuidancePanel';
import { cn } from '@/utils/helpers';
import type { AssessmentMode } from '@/types/api';

const ASSESSMENT_MODE_OPTIONS: Array<{
  id: AssessmentMode;
  label: string;
  description: string;
}> = [
  {
    id: 'fast',
    label: '快速',
    description: '只跑 RDKit 替代模型，用于快速粗筛。',
  },
  {
    id: 'external',
    label: 'Top N 细筛',
    description: '先全量 RDKit 粗筛，再只对 Top N 跑 GNINA/AiZynthFinder。',
  },
  {
    id: 'full',
    label: '全量细筛',
    description: '粗筛通过者全部尝试外部工具。',
  },
];

export default function ChatPanel() {
  const { projectId } = useParams();
  const queryClient = useQueryClient();
  const { currentProject } = useWorkspaceStore();
  const messagesEndRef = useRef<HTMLDivElement>(null);

  const [messages, setMessages] = useState<Array<{ role: 'user' | 'assistant'; content: string; intent?: string }>>([]);
  const [assessmentMode, setAssessmentMode] = useState<AssessmentMode>('external');
  const [externalTopN, setExternalTopN] = useState(10);

  // Load constraints
  const { data: constraints } = useQuery({
    queryKey: ['constraints', projectId],
    queryFn: () => assessmentApi.getConstraints(projectId!),
    enabled: !!projectId,
  });

  // Send message mutation
  const sendMessage = useMutation({
    mutationFn: (message: string) => chatApi.sendMessage(projectId!, { message }),
    onSuccess: (response, message) => {
      setMessages((prev) => [
        ...prev,
        { role: 'user', content: message },
        { role: 'assistant', content: response.reply, intent: response.intent },
      ]);
      // Refresh constraints if new ones were created
      if (response.created_constraints && response.created_constraints.length > 0) {
        queryClient.invalidateQueries({ queryKey: ['constraints', projectId] });
      }
      scrollToBottom();
    },
  });

  // Run pipeline mutation
  const runPipeline = useMutation({
    mutationFn: ({
      mode,
      generationConfig,
    }: {
      mode: 'dry_run' | 'full';
      generationConfig?: Record<string, any>;
    }) => projectsApi.run(projectId!, mode, generationConfig),
    onSuccess: () => {
      queryClient.invalidateQueries({ queryKey: ['project-status', projectId] });
      setMessages((prev) => [
        ...prev,
        { role: 'assistant', content: '已启动流程，请查看右侧工作台的执行进度。' },
      ]);
    },
  });

  const scrollToBottom = () => {
    messagesEndRef.current?.scrollIntoView({ behavior: 'smooth' });
  };

  useEffect(() => {
    scrollToBottom();
  }, [messages]);

  const handleSend = (message: string) => {
    sendMessage.mutate(message);
  };

  const handleRunDryRun = () => {
    runPipeline.mutate({ mode: 'dry_run' });
  };

  const handleRunFull = () => {
    runPipeline.mutate({
      mode: 'full',
      generationConfig: {
        assessment_mode: assessmentMode,
        external_top_n: externalTopN,
      },
    });
  };

  if (!projectId || !currentProject) {
    return (
      <div className="flex h-full items-center justify-center">
        <div className="science-card max-w-md text-center">
          <div className="mx-auto mb-4 flex h-12 w-12 items-center justify-center rounded-lg bg-cyan-600 text-white">
            <Bot className="h-6 w-6" />
          </div>
          <h2 className="text-xl font-semibold text-slate-900">欢迎使用小分子药物设计 Agent</h2>
          <p className="mt-2 text-sm text-slate-500">请从左侧选择或创建一个项目</p>
        </div>
      </div>
    );
  }

  return (
    <div className="flex flex-col h-full">
      {/* Header */}
      <div className="surface-panel border-x-0 border-t-0 px-4 py-4 sm:px-6">
        <div className="flex flex-col gap-3 sm:flex-row sm:items-center sm:justify-between">
          <div className="min-w-0">
            <div className="flex items-center gap-2">
              <Sparkles className="h-4 w-4 text-emerald-500" />
              <h1 className="text-lg font-semibold text-slate-950">{currentProject.name}</h1>
            </div>
            {currentProject.target_id && (
              <p className="mt-1 text-sm text-cyan-700">{currentProject.target_id}</p>
            )}
          </div>
          <div className="flex flex-col gap-2 sm:items-end">
            <div className="flex flex-wrap items-center gap-2 rounded-lg border border-cyan-100 bg-white px-2 py-2 shadow-sm shadow-cyan-950/5">
              <div className="flex items-center gap-1 pr-1 text-xs font-medium text-slate-600">
                <Gauge className="h-3.5 w-3.5 text-cyan-700" />
                评估深度
              </div>
              <div className="flex rounded-md border border-slate-200 bg-slate-50 p-0.5">
                {ASSESSMENT_MODE_OPTIONS.map((option) => (
                  <button
                    key={option.id}
                    type="button"
                    title={option.description}
                    onClick={() => setAssessmentMode(option.id)}
                    className={cn(
                      'h-7 min-w-[58px] rounded px-2 text-xs font-medium transition-colors',
                      assessmentMode === option.id
                        ? 'bg-cyan-600 text-white shadow-sm'
                        : 'text-slate-600 hover:bg-white hover:text-cyan-800'
                    )}
                  >
                    {option.label}
                  </button>
                ))}
              </div>
              <label className="flex items-center gap-1 text-xs text-slate-600">
                Top N
                <input
                  type="number"
                  min={1}
                  max={100}
                  value={externalTopN}
                  onChange={(event) =>
                    setExternalTopN(Math.max(1, Math.min(100, Number(event.target.value) || 1)))
                  }
                  disabled={assessmentMode !== 'external'}
                  className="h-7 w-16 rounded border border-slate-200 bg-white px-2 text-xs text-slate-800 disabled:bg-slate-100 disabled:text-slate-400"
                />
              </label>
            </div>
            <div className="flex flex-wrap items-center gap-2">
              <button
                onClick={handleRunDryRun}
                disabled={runPipeline.isPending}
                className="secondary-action flex items-center justify-center gap-2 rounded-lg px-4 py-2 text-sm font-medium transition-colors"
              >
                <FileText className="w-4 h-4" />
                Dry Run
              </button>
              <button
                onClick={handleRunFull}
                disabled={runPipeline.isPending}
                className="primary-action flex items-center justify-center gap-2 rounded-lg px-4 py-2 text-sm font-medium transition-colors"
              >
                {runPipeline.isPending ? (
                  <Loader2 className="w-4 h-4 animate-spin" />
                ) : (
                  <Play className="w-4 h-4" />
                )}
                运行流程
              </button>
            </div>
          </div>
        </div>

        {/* Constraints */}
        {constraints && constraints.length > 0 && (
          <div className="mt-4">
            <h3 className="mb-2 text-sm font-medium text-slate-700">当前约束</h3>
            <ConstraintChips constraints={constraints} />
          </div>
        )}
      </div>

      {/* Messages */}
      <div className="flex-1 overflow-y-auto">
        <div className="max-w-4xl mx-auto p-6 space-y-4">
          {messages.length === 0 ? (
            <div className="mx-auto max-w-4xl py-6">
              <div className="mx-auto mb-4 flex h-12 w-12 items-center justify-center rounded-lg border border-cyan-200 bg-white text-cyan-700 shadow-sm">
                <Bot className="h-6 w-6" />
              </div>
              <div className="mb-5 text-center">
                <p className="text-sm font-medium text-slate-700">
                  像和 GPT 对话一样描述目标，也可以先用下面的向导生成一轮药物设计指令。
                </p>
                <p className="mt-1 text-xs text-slate-500">
                  向导会把靶点、设计目标、种子分子、物化约束和 pipeline 步骤整理成 Agent 可执行的需求。
                </p>
              </div>
              <DesignGuidancePanel
                project={currentProject}
                variant="compact"
                onSendPrompt={handleSend}
              />
            </div>
          ) : (
            messages.map((msg, idx) => (
              <div
                key={idx}
                className={cn(
                  'chat-message',
                  msg.role === 'user' ? 'user' : 'assistant'
                )}
              >
                <div className="flex items-start gap-3">
                  <div
                    className={cn(
                      'w-8 h-8 rounded-full flex items-center justify-center text-xs font-semibold flex-shrink-0',
                      msg.role === 'user' ? 'bg-white/20 text-white ring-1 ring-white/30' : 'bg-cyan-600 text-white'
                    )}
                  >
                    {msg.role === 'user' ? '你' : 'AI'}
                  </div>
                  <div className="flex-1 min-w-0">
                    {msg.intent && (
                      <span className="mb-2 inline-block rounded bg-cyan-50 px-2 py-0.5 text-xs text-cyan-800">
                        {msg.intent}
                      </span>
                    )}
                    <div className={cn(
                      'whitespace-pre-wrap text-sm',
                      msg.role === 'user' ? 'text-white' : 'text-slate-800'
                    )}>
                      {msg.content}
                    </div>
                  </div>
                </div>
              </div>
            ))
          )}
          <div ref={messagesEndRef} />
        </div>
      </div>

      {/* Composer */}
      <ChatComposer
        onSend={handleSend}
        disabled={sendMessage.isPending}
        className="px-4 sm:px-6"
      />
    </div>
  );
}
