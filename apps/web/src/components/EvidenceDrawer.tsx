/**
 * Evidence Drawer Component
 *
 * Side drawer to display RAG evidence chunks
 */

import { BookOpen, Database, X } from 'lucide-react';
import { useWorkspaceStore } from '@/state/workspaceStore';
import { useQuery } from '@tanstack/react-query';
import { ragApi } from '@/api';
import { useParams } from 'react-router-dom';

function metadataCount(metadata: Record<string, any>) {
  return metadata.chunk_count ?? metadata.chunks ?? metadata.token_count ?? '-';
}

export default function EvidenceDrawer() {
  const { projectId } = useParams();
  const { evidenceDrawerOpen, evidenceDrawerChunkId, closeEvidenceDrawer } = useWorkspaceStore();

  const { data: documents } = useQuery({
    queryKey: ['rag-documents', projectId],
    queryFn: () => ragApi.listDocuments(projectId!),
    enabled: !!projectId && evidenceDrawerOpen,
  });

  if (!evidenceDrawerOpen) return null;

  const evidenceId = evidenceDrawerChunkId;

  return (
    <>
      <button
        type="button"
        aria-label="关闭证据抽屉"
        className="fixed inset-0 z-40 bg-slate-950/40 backdrop-blur-[1px]"
        onClick={closeEvidenceDrawer}
      />

      <aside className="fixed bottom-0 right-0 top-0 z-50 flex w-96 max-w-full flex-col border-l border-cyan-100 bg-white shadow-2xl shadow-cyan-950/20">
        <div className="flex items-center justify-between border-b border-cyan-100 bg-cyan-50/60 p-4">
          <div className="flex items-center gap-2">
            <BookOpen className="h-5 w-5 text-cyan-700" />
            <h2 className="font-semibold text-slate-950">证据详情</h2>
          </div>
          <button
            onClick={closeEvidenceDrawer}
            className="rounded-md p-1 text-slate-500 hover:bg-white hover:text-cyan-700"
            title="关闭"
          >
            <X className="h-5 w-5" />
          </button>
        </div>

        <div className="flex-1 overflow-y-auto p-4">
          {evidenceId ? (
            <div className="space-y-4">
              <div className="science-card">
                <h3 className="mb-2 text-sm font-semibold text-slate-950">证据 ID</h3>
                <code className="block rounded-md bg-slate-950 px-2 py-2 text-xs text-cyan-50">
                  {evidenceId}
                </code>
              </div>

              <div className="science-card">
                <h3 className="mb-2 text-sm font-semibold text-slate-950">内容</h3>
                <div className="rounded-lg border border-dashed border-cyan-200 bg-cyan-50/50 p-3 text-sm leading-6 text-slate-600">
                  当前接口返回的是证据索引，完整 chunk 内容可在后续接入证据详情 API 后展示。
                </div>
              </div>

              {documents && documents.length > 0 && (
                <div>
                  <h3 className="mb-2 text-sm font-semibold text-slate-950">来源文档</h3>
                  <div className="space-y-2">
                    {documents.slice(0, 4).map((doc) => (
                      <div key={doc.document_id} className="rounded-lg border border-cyan-100 bg-white p-3 shadow-sm">
                        <div className="flex items-start gap-2">
                          <Database className="mt-0.5 h-4 w-4 flex-shrink-0 text-cyan-600" />
                          <div className="min-w-0">
                            <div className="truncate text-sm font-medium text-slate-900">{doc.title}</div>
                            <div className="mt-1 text-xs text-slate-500">
                              {doc.document_type} · {metadataCount(doc.metadata)} chunks
                            </div>
                            {doc.source && (
                              <div className="mt-1 truncate text-xs text-cyan-700">{doc.source}</div>
                            )}
                          </div>
                        </div>
                      </div>
                    ))}
                  </div>
                </div>
              )}
            </div>
          ) : (
            <div className="py-10 text-center text-sm text-slate-500">
              未找到证据信息
            </div>
          )}
        </div>
      </aside>
    </>
  );
}
