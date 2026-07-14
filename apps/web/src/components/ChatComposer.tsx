/**
 * Chat Composer Component
 *
 * Message input box with auto-grow textarea
 */

import { useState, useRef, useEffect } from 'react';
import { Send, Loader2 } from 'lucide-react';
import { useWorkspaceStore } from '@/state/workspaceStore';
import { cn } from '@/utils/helpers';

interface ChatComposerProps {
  onSend: (message: string) => void;
  disabled?: boolean;
  placeholder?: string;
  className?: string;
}

export default function ChatComposer({
  onSend,
  disabled = false,
  placeholder = '输入消息... (Enter 发送, Shift+Enter 换行)',
  className,
}: ChatComposerProps) {
  const [message, setMessage] = useState('');
  const textareaRef = useRef<HTMLTextAreaElement>(null);
  const composerDraft = useWorkspaceStore((state) => state.composerDraft);
  const clearComposerDraftAction = useWorkspaceStore((state) => state.clearComposerDraft);

  // Auto-resize textarea
  useEffect(() => {
    const textarea = textareaRef.current;
    if (textarea) {
      textarea.style.height = 'auto';
      textarea.style.height = Math.min(textarea.scrollHeight, 200) + 'px';
    }
  }, [message]);

  useEffect(() => {
    if (!composerDraft) return;
    setMessage(composerDraft.content);
    textareaRef.current?.focus();
  }, [composerDraft]);

  const handleSubmit = (e: React.FormEvent) => {
    e.preventDefault();
    if (message.trim() && !disabled) {
      onSend(message.trim());
      setMessage('');
      if (typeof clearComposerDraftAction === 'function') {
        clearComposerDraftAction();
      } else {
        useWorkspaceStore.setState({ composerDraft: null });
      }
    }
  };

  const handleKeyDown = (e: React.KeyboardEvent) => {
    if (e.key === 'Enter' && !e.shiftKey) {
      e.preventDefault();
      handleSubmit(e);
    }
  };

  return (
    <form onSubmit={handleSubmit} className={cn('border-t border-cyan-100 bg-white/90 p-4 backdrop-blur', className)}>
      <div className="mx-auto flex max-w-4xl flex-col gap-3 sm:flex-row">
        <textarea
          ref={textareaRef}
          value={message}
          onChange={(e) => setMessage(e.target.value)}
          onKeyDown={handleKeyDown}
          placeholder={placeholder}
          disabled={disabled}
          rows={1}
          className="min-h-[48px] flex-1 resize-none rounded-lg border border-cyan-200 bg-white px-4 py-3 text-sm shadow-sm shadow-cyan-950/5 focus:outline-none focus:ring-2 focus:ring-cyan-500 disabled:bg-slate-50 disabled:text-slate-400"
        />
        <button
          type="submit"
          disabled={disabled || !message.trim()}
          className="primary-action flex items-center justify-center gap-2 rounded-lg px-6 py-3 text-sm font-medium transition-colors disabled:cursor-not-allowed sm:min-w-[120px]"
        >
          {disabled ? (
            <>
              <Loader2 className="w-4 h-4 animate-spin" />
              发送中
            </>
          ) : (
            <>
              <Send className="w-4 h-4" />
              发送
            </>
          )}
        </button>
      </div>
    </form>
  );
}
