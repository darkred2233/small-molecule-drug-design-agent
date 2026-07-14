/**
 * File Dropzone Component
 *
 * Drag-and-drop file upload with progress
 */

import { useState, useCallback, type ChangeEvent, type DragEvent } from 'react';
import { useParams } from 'react-router-dom';
import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query';
import { filesApi } from '@/api';
import { Upload, FileText, CheckCircle, XCircle, Loader2, Database } from 'lucide-react';
import { cn, formatDate } from '@/utils/helpers';

function statusLabel(status: string) {
  const labels: Record<string, string> = {
    uploaded: '已上传',
    parsing: '解析中',
    success: '已解析',
    partial_success: '部分解析',
    failed: '解析失败',
  };
  return labels[status] || status;
}

export default function FileDropzone() {
  const { projectId } = useParams();
  const queryClient = useQueryClient();
  const [isDragging, setIsDragging] = useState(false);
  const [uploadProgress, setUploadProgress] = useState<Record<string, number>>({});

  const { data: files } = useQuery({
    queryKey: ['files', projectId],
    queryFn: () => filesApi.list(projectId!),
    enabled: !!projectId,
  });

  const uploadFile = useMutation({
    mutationFn: async (file: globalThis.File) => {
      const result = await filesApi.upload(projectId!, file, (progress) => {
        setUploadProgress((prev) => ({ ...prev, [file.name]: progress }));
      });
      await filesApi.parse(projectId!, result.file_id);
      return result;
    },
    onSuccess: () => {
      queryClient.invalidateQueries({ queryKey: ['files', projectId] });
      setUploadProgress({});
    },
  });

  const ingestFiles = useMutation({
    mutationFn: () => filesApi.ingest(projectId!),
    onSuccess: () => {
      queryClient.invalidateQueries({ queryKey: ['files', projectId] });
    },
  });

  const handleDragOver = useCallback((event: DragEvent<HTMLDivElement>) => {
    event.preventDefault();
    setIsDragging(true);
  }, []);

  const handleDragLeave = useCallback((event: DragEvent<HTMLDivElement>) => {
    event.preventDefault();
    setIsDragging(false);
  }, []);

  const handleDrop = useCallback((event: DragEvent<HTMLDivElement>) => {
    event.preventDefault();
    setIsDragging(false);

    const droppedFiles = Array.from(event.dataTransfer.files);
    droppedFiles.forEach((file) => {
      uploadFile.mutate(file);
    });
  }, [uploadFile]);

  const handleFileSelect = (event: ChangeEvent<HTMLInputElement>) => {
    const selectedFiles = Array.from(event.target.files || []);
    selectedFiles.forEach((file) => {
      uploadFile.mutate(file);
    });
  };

  const getStatusIcon = (status: string) => {
    switch (status) {
      case 'success':
      case 'partial_success':
        return <CheckCircle className="h-4 w-4 text-emerald-600" />;
      case 'parsing':
        return <Loader2 className="h-4 w-4 animate-spin text-cyan-600" />;
      case 'failed':
        return <XCircle className="h-4 w-4 text-rose-600" />;
      default:
        return <FileText className="h-4 w-4 text-slate-400" />;
    }
  };

  return (
    <div className="space-y-4">
      <div
        onDragOver={handleDragOver}
        onDragLeave={handleDragLeave}
        onDrop={handleDrop}
        className={cn(
          'rounded-lg border-2 border-dashed p-8 text-center transition-colors',
          isDragging
            ? 'border-cyan-500 bg-cyan-50'
            : 'border-cyan-200 bg-white hover:border-cyan-400 hover:bg-cyan-50/40'
        )}
      >
        <input
          type="file"
          id="file-upload"
          multiple
          accept=".pdf,.docx,.md,.html,.csv,.sdf,.pdb"
          onChange={handleFileSelect}
          className="hidden"
        />
        <label htmlFor="file-upload" className="block cursor-pointer">
          <div className="mx-auto mb-4 flex h-12 w-12 items-center justify-center rounded-lg bg-cyan-50 text-cyan-700 ring-1 ring-cyan-100">
            <Upload className="h-6 w-6" />
          </div>
          <p className="text-sm font-medium text-slate-800">拖拽实验资料到此处，或点击上传</p>
          <p className="mt-2 text-xs text-slate-500">
            支持 PDF、DOCX、Markdown、HTML、CSV、SDF、PDB，用于 RAG 证据和分子导入
          </p>
        </label>
      </div>

      {Object.keys(uploadProgress).length > 0 && (
        <div className="space-y-2">
          {Object.entries(uploadProgress).map(([filename, progress]) => (
            <div key={filename} className="rounded-lg border border-cyan-100 bg-white p-3">
              <div className="mb-2 flex items-center justify-between gap-3">
                <span className="truncate text-sm font-medium text-slate-800">{filename}</span>
                <span className="text-xs text-cyan-700">{progress}%</span>
              </div>
              <div className="h-2 w-full rounded-full bg-cyan-50">
                <div
                  className="h-2 rounded-full bg-cyan-600 transition-all"
                  style={{ width: `${progress}%` }}
                />
              </div>
            </div>
          ))}
        </div>
      )}

      {files && files.length > 0 && (
        <div className="space-y-3">
          <div className="flex items-center justify-between gap-3">
            <h3 className="text-sm font-semibold text-slate-950">已上传文件 ({files.length})</h3>
            <button
              onClick={() => ingestFiles.mutate()}
              disabled={ingestFiles.isPending}
              className="inline-flex items-center gap-2 rounded-md bg-cyan-600 px-3 py-1.5 text-xs font-medium text-white shadow-sm shadow-cyan-900/20 hover:bg-cyan-700 disabled:bg-slate-300"
            >
              {ingestFiles.isPending && <Loader2 className="h-3 w-3 animate-spin" />}
              {ingestFiles.isPending ? '处理中...' : '批量导入 RAG'}
            </button>
          </div>

          <div className="space-y-2">
            {files.map((file) => (
              <div
                key={file.file_id}
                className="flex items-center gap-3 rounded-lg border border-cyan-100 bg-white p-3 shadow-sm shadow-cyan-950/5 transition-shadow hover:shadow-md"
              >
                {getStatusIcon(file.parse_status)}
                <div className="min-w-0 flex-1">
                  <div className="truncate text-sm font-medium text-slate-900">{file.filename}</div>
                  <div className="mt-1 flex flex-wrap items-center gap-3 text-xs text-slate-500">
                    <span>{file.file_type.toUpperCase()}</span>
                    {file.extracted_molecule_count !== undefined && (
                      <span>{file.extracted_molecule_count} 个分子</span>
                    )}
                    {file.extracted_chunk_count !== undefined && (
                      <span className="inline-flex items-center gap-1">
                        <Database className="h-3 w-3" />
                        {file.extracted_chunk_count} 个 chunks
                      </span>
                    )}
                    {file.created_at && <span>{formatDate(file.created_at)}</span>}
                  </div>
                </div>
                <span className={cn(
                  'rounded-full px-2.5 py-1 text-xs font-medium',
                  file.parse_status === 'success' && 'border border-emerald-200 bg-emerald-50 text-emerald-700',
                  file.parse_status === 'partial_success' && 'border border-amber-200 bg-amber-50 text-amber-700',
                  file.parse_status === 'parsing' && 'border border-cyan-200 bg-cyan-50 text-cyan-700',
                  file.parse_status === 'failed' && 'border border-rose-200 bg-rose-50 text-rose-700',
                  file.parse_status === 'uploaded' && 'border border-slate-200 bg-slate-50 text-slate-600'
                )}>
                  {statusLabel(file.parse_status)}
                </span>
              </div>
            ))}
          </div>
        </div>
      )}
    </div>
  );
}
