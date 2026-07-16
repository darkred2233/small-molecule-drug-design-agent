/**
 * Evidence Drawer Component
 *
 * Side drawer to display RAG evidence chunks
 */

import { BookOpen, Database, X } from 'lucide-react';
import { useWorkspaceStore } from '@/state/workspaceStore';
import { useQuery } from '@tanstack/react-query';
import { ragApi } from '@/api';
import { useMatch } from 'react-router-dom';
import type { EvidenceLink } from '@/types/api';
import EvidenceContent from './EvidenceContent';

function metadataCount(metadata: Record<string, any>) {
  return metadata.chunk_count ?? metadata.chunks ?? metadata.token_count ?? '-';
}

function evidenceTypeLabel(claimType: string) {
  const normalized = claimType.replace(/^database_/, '');
  const labels: Record<string, string> = {
    molecule: '分子记录',
    properties: '理化性质',
    rule_filter: '规则过滤',
    conformer: '构象分析',
    docking: '分子对接',
    admet: 'ADMET 预测',
    synthesis: '合成路线',
    ranking: '综合排序',
  };
  return labels[normalized] ?? claimType;
}

function evidenceConfidencePresentation(evidence: EvidenceLink) {
  const score =
    typeof evidence.confidence === 'number' &&
    Number.isFinite(evidence.confidence) &&
    evidence.confidence >= 0 &&
    evidence.confidence <= 1
      ? evidence.confidence
      : null;

  if (evidence.claim_type === 'database_synthesis' && score !== null) {
    return {
      label: '路线评分',
      value: score.toFixed(3),
      scored: true,
      title: '工具生成的归一化路线评分，不代表实验成功率',
    };
  }
  if (evidence.claim_type === 'database_ranking' && score !== null) {
    return {
      label: '证据完整度',
      value: score.toFixed(3),
      scored: true,
      title: '当前评估流程中可用证据的加权完整度',
    };
  }
  if (evidence.claim_type.startsWith('database_')) {
    return { label: '数据库记录', value: null, scored: false, title: undefined };
  }
  if (score !== null) {
    return {
      label: '检索相关度',
      value: score.toFixed(3),
      scored: true,
      title: 'RAG 检索排序分数，不代表内容正确率',
    };
  }
  return { label: 'RAG 文档证据', value: null, scored: false, title: undefined };
}

export default function EvidenceDrawer() {
  const projectRoute = useMatch('/workspace/:projectId/*');
  const projectId = projectRoute?.params.projectId;
  const { evidenceDrawerOpen, evidenceDrawerChunkId, closeEvidenceDrawer } = useWorkspaceStore();

  const {
    data: evidenceLink,
    isLoading: isLoadingEvidence,
    isError: isEvidenceError,
  } = useQuery({
    queryKey: ['evidence-link', projectId, evidenceDrawerChunkId],
    queryFn: () => ragApi.getEvidenceLink(projectId!, evidenceDrawerChunkId!),
    enabled: !!projectId && !!evidenceDrawerChunkId && evidenceDrawerOpen,
    retry: false,
  });

  const {
    data: chunkDetail,
    isLoading: isLoadingChunk,
    isError: isChunkError,
  } = useQuery({
    queryKey: ['rag-chunk', projectId, evidenceLink?.chunk_id],
    queryFn: () => ragApi.getChunk(projectId!, evidenceLink!.chunk_id!),
    enabled: !!projectId && !!evidenceLink?.chunk_id && evidenceDrawerOpen,
    staleTime: 0,
  });

  const { data: documents } = useQuery({
    queryKey: ['rag-documents', projectId],
    queryFn: () => ragApi.listDocuments(projectId!),
    enabled: !!projectId && !!chunkDetail?.document_id && evidenceDrawerOpen,
  });

  if (!evidenceDrawerOpen) return null;

  const evidenceId = evidenceDrawerChunkId;
  const isLoading = isLoadingEvidence || isLoadingChunk;
  const hasError = isEvidenceError || isChunkError;
  const evidenceContent = chunkDetail?.content ?? evidenceLink?.rationale ?? null;
  const confidencePresentation = evidenceLink
    ? evidenceConfidencePresentation(evidenceLink)
    : null;

  // Find the source document for the chunk
  const sourceDocument = chunkDetail
    ? documents?.find((doc) => doc.document_id === chunkDetail.document_id)
    : null;

  return (
    <>
      <button
        type="button"
        aria-label="关闭证据抽屉"
        className="fixed inset-0 z-40 bg-slate-950/40 backdrop-blur-[1px]"
        onClick={closeEvidenceDrawer}
      />

      <aside className="fixed bottom-0 right-0 top-0 z-50 flex w-full flex-col border-l border-cyan-100 bg-white shadow-2xl shadow-cyan-950/20 sm:w-[34rem]">
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

              {isLoading ? (
                <div className="science-card">
                  <div className="py-8 text-center text-sm text-slate-500">加载中...</div>
                </div>
              ) : hasError ? (
                <div className="science-card">
                  <div className="border-l-2 border-rose-500 pl-3 text-sm leading-6 text-rose-700">
                    证据详情加载失败，请稍后重试。
                  </div>
                </div>
              ) : evidenceLink ? (
                <>
                  <div className="science-card">
                    <div className="flex items-start justify-between gap-4">
                      <div>
                        <div className="text-xs font-medium text-slate-500">证据类型</div>
                        <div className="mt-1 text-base font-semibold text-slate-950">
                          {evidenceTypeLabel(evidenceLink.claim_type)}
                        </div>
                      </div>
                      {confidencePresentation && (
                        <div
                          title={confidencePresentation.title}
                          className={
                            confidencePresentation.scored
                              ? 'rounded-md bg-emerald-50 px-2 py-1 text-xs font-semibold text-emerald-700'
                              : 'rounded-md bg-cyan-50 px-2 py-1 text-xs font-semibold text-cyan-700'
                          }
                        >
                          {confidencePresentation.label}
                          {confidencePresentation.value !== null && ` ${confidencePresentation.value}`}
                        </div>
                      )}
                    </div>
                    {evidenceLink.molecule_id && (
                      <div className="mt-3 border-t border-cyan-100 pt-3 text-xs text-slate-500">
                        关联分子：<span className="font-medium text-slate-700">{evidenceLink.molecule_id}</span>
                      </div>
                    )}
                  </div>

                  <div className="science-card">
                    <h3 className="mb-2 text-sm font-semibold text-slate-950">证据内容</h3>
                    <EvidenceContent content={evidenceContent} />
                    {(chunkDetail?.page_number || chunkDetail?.section || chunkDetail?.token_count) && (
                      <div className="mt-4 flex flex-wrap gap-x-4 gap-y-1 border-t border-cyan-100 pt-3 text-xs text-slate-500">
                        {chunkDetail.page_number && <span>页码：{chunkDetail.page_number}</span>}
                        {chunkDetail.section && <span>章节：{chunkDetail.section}</span>}
                        {chunkDetail.token_count && <span>Token：{chunkDetail.token_count}</span>}
                      </div>
                    )}
                  </div>

                  {sourceDocument && (
                    <div className="science-card">
                      <h3 className="mb-2 text-sm font-semibold text-slate-950">来源文档</h3>
                      <div className="rounded-lg border border-cyan-100 bg-white p-3 shadow-sm">
                        <div className="flex items-start gap-2">
                          <Database className="mt-0.5 h-4 w-4 flex-shrink-0 text-cyan-600" />
                          <div className="min-w-0">
                            <div className="truncate text-sm font-medium text-slate-900">
                              {sourceDocument.title}
                            </div>
                            <div className="mt-1 text-xs text-slate-500">
                              {sourceDocument.document_type} · {metadataCount(sourceDocument.metadata)} chunks
                            </div>
                            {sourceDocument.source && (
                              <div className="mt-1 truncate text-xs text-cyan-700">
                                {sourceDocument.source}
                              </div>
                            )}
                          </div>
                        </div>
                      </div>
                    </div>
                  )}
                </>
              ) : (
                <div className="science-card">
                  <div className="rounded-lg border border-dashed border-amber-200 bg-amber-50/50 p-3 text-sm text-amber-700">
                    未找到证据详情
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
