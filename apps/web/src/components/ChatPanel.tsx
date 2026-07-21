import { useState, useRef, useEffect } from 'react';
import { useParams } from 'react-router-dom';
import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query';
import { chatApi, assessmentApi } from '@/api';
import { useWorkspaceStore } from '@/state/workspaceStore';
import { Bot, Sparkles } from 'lucide-react';
import ChatComposer from './ChatComposer';
import ConstraintChips from './ConstraintChips';
import { cn } from '@/utils/helpers';

export default function ChatPanel() {
  const { projectId } = useParams();
  const queryClient = useQueryClient();
  const { currentProject } = useWorkspaceStore();
  const messagesEndRef = useRef<HTMLDivElement>(null);

  const [messages, setMessages] = useState<Array<{ role: 'user' | 'assistant'; content: string; intent?: string }>>([]);
  const [latestPlanWarnings, setLatestPlanWarnings] = useState<string[]>([]);

  const { data: constraints } = useQuery({
    queryKey: ['constraints', projectId],
    queryFn: () => assessmentApi.getConstraints(projectId!),
    enabled: !!projectId,
  });

  const sendMessage = useMutation({
    mutationFn: (message: string) => chatApi.sendMessage(projectId!, { message }),
    onSuccess: (response, message) => {
      setMessages((prev) => [
        ...prev,
        { role: 'user', content: message },
        { role: 'assistant', content: response.reply, intent: response.intent },
      ]);
      if (response.created_constraints && response.created_constraints.length > 0) {
        queryClient.invalidateQueries({ queryKey: ['constraints', projectId] });
      }
      setLatestPlanWarnings(response.warnings ?? []);
      scrollToBottom();
    },
  });

  const scrollToBottom = () => {
    messagesEndRef.current?.scrollIntoView({ behavior: 'smooth' });
  };

  useEffect(() => {
    scrollToBottom();
  }, [messages]);

  useEffect(() => {
    setLatestPlanWarnings([]);
  }, [projectId]);

  const handleSend = (message: string) => {
    sendMessage.mutate(message);
  };

  if (!projectId || !currentProject) {
    return (
      <div className="flex h-full items-center justify-center">
        <div className="science-card max-w-md text-center">
          <div className="mx-auto mb-4 flex h-12 w-12 items-center justify-center rounded-lg bg-cyan-600 text-white">
            <Bot className="h-6 w-6" />
          </div>
          <h2 className="text-xl font-semibold text-slate-900">小分子药物设计 Agent</h2>
          <p className="mt-2 text-sm text-slate-500">请从左侧选择或创建一个项目</p>
        </div>
      </div>
    );
  }

  return (
    <div className="flex h-full flex-col">
      <div className="surface-panel border-x-0 border-t-0 px-4 py-4 sm:px-6">
        <div className="mb-3 flex flex-col gap-2 sm:flex-row sm:items-center sm:justify-between">
          <div className="min-w-0">
            <div className="flex items-center gap-2">
              <Sparkles className="h-4 w-4 text-emerald-500" />
              <h1 className="text-lg font-semibold text-slate-950">{currentProject.name}</h1>
            </div>
            {currentProject.target_id && (
              <p className="mt-1 text-sm text-cyan-700">{currentProject.target_id}</p>
            )}
          </div>
          <span className="w-fit rounded-full border border-slate-200 bg-slate-50 px-3 py-1 text-xs font-medium text-slate-600">
            {currentProject.status}
          </span>
        </div>

        {constraints && constraints.length > 0 && (
          <div className="mt-3">
            <ConstraintChips constraints={constraints} />
          </div>
        )}
        {latestPlanWarnings.length > 0 && (
          <div className="mt-3 rounded-md border border-amber-200 bg-amber-50 px-3 py-2 text-xs text-amber-800">
            {latestPlanWarnings.join(' ')}
          </div>
        )}
      </div>

      <div className="flex-1 overflow-y-auto">
        <div className="mx-auto max-w-4xl space-y-4 p-6">
          {messages.length === 0 ? (
            <div className="py-8 text-center text-sm text-slate-500">暂无对话</div>
          ) : (
            messages.map((msg, idx) => (
              <div
                key={idx}
                className={cn('chat-message', msg.role === 'user' ? 'user' : 'assistant')}
              >
                <div className="flex items-start gap-3">
                  <div
                    className={cn(
                      'flex h-8 w-8 flex-shrink-0 items-center justify-center rounded-full text-xs font-semibold',
                      msg.role === 'user' ? 'bg-white/20 text-white ring-1 ring-white/30' : 'bg-cyan-600 text-white'
                    )}
                  >
                    {msg.role === 'user' ? '你' : 'AI'}
                  </div>
                  <div className="min-w-0 flex-1">
                    {msg.intent && (
                      <span className="mb-2 inline-block rounded bg-cyan-50 px-2 py-0.5 text-xs text-cyan-800">
                        {msg.intent}
                      </span>
                    )}
                    <div
                      className={cn(
                        'whitespace-pre-wrap text-sm',
                        msg.role === 'user' ? 'text-white' : 'text-slate-800'
                      )}
                    >
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

      <ChatComposer onSend={handleSend} disabled={sendMessage.isPending} className="px-4 sm:px-6" />
    </div>
  );
}
