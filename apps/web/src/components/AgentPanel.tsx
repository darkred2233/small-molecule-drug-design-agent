/* eslint-disable react-refresh/only-export-components */
import { useState } from 'react';
import { useMutation, useQueryClient } from '@tanstack/react-query';
import { Bot, Send, Sparkles } from 'lucide-react';
import { useLocation, useParams } from 'react-router-dom';
import { roundsApi } from '@/api/rounds';
import type { StrategyDraft } from '@/types/workbench';

interface Message { role: 'agent' | 'user'; content: string; }

export function AgentPanel() {
  const { projectId, roundId } = useParams();
  const location = useLocation();
  const queryClient = useQueryClient();
  const strategyContext = Boolean(roundId && location.pathname.endsWith('/strategy'));
  const [prompt, setPrompt] = useState('');
  const [messages, setMessages] = useState<Message[]>([]);

  const revise = useMutation<StrategyDraft, Error, string>({
    mutationFn: (userMessage: string) => roundsApi.reviseStrategy(projectId!, roundId!, { user_message: userMessage }),
    onSuccess: (strategy) => {
      queryClient.setQueryData(['strategy', projectId, roundId], strategy);
      setMessages((current) => [...current, { role: 'agent', content: `已生成新的策略草案：${strategy.rationale || '请在中间区域核对 Campaign、Seed 和约束。'}` }]);
    },
    onError: (error) => setMessages((current) => [...current, { role: 'agent', content: error instanceof Error ? error.message : '策略修改失败。' }]),
  });

  const send = () => {
    const message = prompt.trim();
    if (!message) return;
    setMessages((current) => [...current, { role: 'user', content: message }]);
    setPrompt('');
    if (strategyContext && projectId && roundId) revise.mutate(message);
    else setMessages((current) => [...current, { role: 'agent', content: '当前页面以结果审阅为主。进入“策略审核”后，可直接用自然语言要求我调整本轮生成方法、数量、Seed 和评估边界。' }]);
  };

  const guidance = strategyContext
    ? '说明希望如何调整本轮策略。变更会先生成新草案，仍需你确认后才会执行。'
    : '我会根据当前页面的结果提供解释。策略类修改只会在“策略审核”页面形成可确认的草案。';

  return <aside className="agent-panel">
    <div className="agent-header"><Bot size={19} color="#176451" /><div><h3>中枢设计 Agent</h3><div className="subtle" style={{ marginTop: 1 }}>中文决策助手</div></div></div>
    <div className="agent-message-list">
      <div className="agent-message"><Sparkles size={14} style={{ verticalAlign: 'text-bottom', marginRight: 5 }} />{guidance}</div>
      {messages.map((message, index) => <div key={`${message.role}-${index}`} className={`agent-message ${message.role === 'user' ? 'agent-message-user' : ''}`}>{message.content}</div>)}
      {revise.isPending && <div className="agent-message">正在根据本轮数据重新安排策略…</div>}
    </div>
    <div className="agent-compose">
      <div className="field"><label htmlFor="agent-prompt">修改建议</label><textarea id="agent-prompt" value={prompt} onChange={(event) => setPrompt(event.target.value)} placeholder={strategyContext ? '例如：减少 scaffold hopping，把数量分配给上一轮排名前 3 的分子。' : '例如：解释当前排名中最高风险的分子。'} /></div>
      <button className="button button-primary" style={{ width: '100%', marginTop: 9 }} onClick={send} disabled={revise.isPending}><Send size={15} />提交给 Agent</button>
    </div>
  </aside>;
}

export function strategySummary(strategy: StrategyDraft | undefined): string {
  if (!strategy) return '尚未生成策略草案。';
  return strategy.rationale || '策略已生成，请核对后确认。';
}
