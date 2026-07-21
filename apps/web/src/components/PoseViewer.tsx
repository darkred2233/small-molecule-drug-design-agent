import { useEffect, useRef, useState } from 'react';
import * as $3Dmol from '3dmol';
import { Box, Download, RotateCcw } from 'lucide-react';
import { reportsApi } from '@/api/reports';
import type { DockingResult } from '@/types/workbench';

function poseType(contentDisposition: string | null): string {
  const filename = contentDisposition?.match(/filename="?([^";]+)"?/i)?.[1]?.toLowerCase() || '';
  if (filename.endsWith('.pdbqt')) return 'pdbqt';
  if (filename.endsWith('.mol2')) return 'mol2';
  if (filename.endsWith('.pdb')) return 'pdb';
  return 'sdf';
}

export function PoseViewer({ projectId, moleculeId, docking }: { projectId: string; moleculeId: string; docking?: DockingResult | null }) {
  const hostRef = useRef<HTMLDivElement>(null);
  const viewerRef = useRef<$3Dmol.GLViewer | null>(null);
  const [error, setError] = useState<string | null>(null);
  const poseUrl = reportsApi.poseUrl(projectId, moleculeId);

  const load = async () => {
    const host = hostRef.current;
    if (!host) return;
    setError(null);
    viewerRef.current?.clear();
    try {
      const response = await fetch(poseUrl);
      if (!response.ok) throw new Error(response.status === 404 ? '后端没有保存该分子的最佳 Pose 文件。' : '最佳 Pose 文件暂时无法读取。');
      const data = await response.text();
      const viewer = $3Dmol.createViewer(host, { backgroundColor: '#101d1b' });
      viewer.addModel(data, poseType(response.headers.get('content-disposition')));
      viewer.setStyle({}, { stick: { radius: 0.18, colorscheme: 'Jmol' } });
      viewer.zoomTo();
      viewer.render();
      viewerRef.current = viewer;
    } catch (loadError) { setError(loadError instanceof Error ? loadError.message : '最佳 Pose 文件暂时无法读取。'); }
  };

  useEffect(() => {
    void load();
    const resize = () => viewerRef.current?.resize();
    window.addEventListener('resize', resize);
    return () => { window.removeEventListener('resize', resize); viewerRef.current?.clear(); };
  // URL changes only when the actual molecular pose changes.
  // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [poseUrl]);

  return <div className="section-stack"><div className="pose-canvas"><div ref={hostRef} />{error && <div className="empty-state" style={{ position: 'absolute', inset: 0, color: '#c8d9d2' }}><Box size={32} /><div><strong style={{ color: '#f3faf6' }}>无法展示最佳 Pose</strong><div>{error}</div></div></div>}</div><div className="row-wrap"><button className="button" onClick={() => void load()}><RotateCcw size={15} />重新载入</button><a className="button" href={poseUrl} target="_blank" rel="noreferrer"><Download size={15} />下载 Pose</a>{docking?.pose_selection_method && <span className="subtle" style={{ margin: 0 }}>选择依据：{docking.pose_selection_method}</span>}{typeof docking?.selected_pose_rank === 'number' && <span className="subtle" style={{ margin: 0 }}>Pose 排名：{docking.selected_pose_rank}</span>}</div></div>;
}
