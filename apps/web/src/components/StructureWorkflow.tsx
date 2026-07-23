import { useMemo, useState } from 'react';
import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query';
import { Check, Download, ScanSearch, Wrench } from 'lucide-react';
import { structuresApi } from '@/api';
import { StatusBadge } from '@/components/StatusBadge';
import type { BindingSite, ProjectStructure, StructureReadiness, UploadedFile } from '@/types/workbench';

interface StructureWorkflowProps {
  projectId: string;
  files: UploadedFile[];
}

export function StructureWorkflow({ projectId, files }: StructureWorkflowProps) {
  const queryClient = useQueryClient();
  const [pdbId, setPdbId] = useState('');
  const [sourceFileId, setSourceFileId] = useState('');
  const { data: structures = [] } = useQuery<ProjectStructure[], Error>({ queryKey: ['structures', projectId], queryFn: () => structuresApi.list(projectId) });
  const { data: sites = [] } = useQuery<BindingSite[], Error>({ queryKey: ['binding-sites', projectId], queryFn: () => structuresApi.bindingSites(projectId) });
  const { data: readiness } = useQuery<StructureReadiness, Error>({ queryKey: ['structure-readiness', projectId], queryFn: () => structuresApi.readiness(projectId) });
  const active = structures.find((item) => item.is_active) ?? null;
  const activeSites = useMemo(() => sites.filter((site) => site.project_id === projectId && site.structure_id === active?.structure_id), [active?.structure_id, projectId, sites]);
  const pdbFiles = files.filter((file) => file.filename.toLowerCase().endsWith('.pdb'));
  const refresh = () => {
    queryClient.invalidateQueries({ queryKey: ['project', projectId] });
    queryClient.invalidateQueries({ queryKey: ['structures', projectId] });
    queryClient.invalidateQueries({ queryKey: ['binding-sites', projectId] });
    queryClient.invalidateQueries({ queryKey: ['structure-readiness', projectId] });
  };
  const importRcsb = useMutation({ mutationFn: () => structuresApi.importRcsb(projectId, pdbId.trim()), onSuccess: () => { setPdbId(''); refresh(); } });
  const registerUpload = useMutation({ mutationFn: () => structuresApi.registerUpload(projectId, sourceFileId), onSuccess: () => { setSourceFileId(''); refresh(); } });
  const activate = useMutation({ mutationFn: (structureId: string) => structuresApi.activate(projectId, structureId), onSuccess: refresh });
  const predict = useMutation({ mutationFn: (structureId: string) => structuresApi.predictPockets(projectId, structureId), onSuccess: refresh });
  const prepare = useMutation({ mutationFn: (structureId: string) => structuresApi.prepare(projectId, structureId), onSuccess: refresh });
  const selectSite = useMutation({ mutationFn: (siteId: string) => structuresApi.selectBindingSite(projectId, siteId), onSuccess: refresh });
  const error = importRcsb.error || registerUpload.error || activate.error || predict.error || prepare.error || selectSite.error;

  return <section className="panel" style={{ marginTop: 18 }}>
    <div className="panel-header"><div><h2>受体结构准备</h2><p className="subtle">RCSB 实验结构或项目 PDB，经过口袋预测和受体准备后供生成与对接工具使用。</p></div><StatusBadge status={readiness?.ready ? 'completed' : active ? 'pending' : 'created'} /></div>
    <div className="panel-body stack">
      <div className="split-grid">
        <div className="stack"><strong>从 RCSB 获取</strong><div className="row"><input value={pdbId} onChange={(event) => setPdbId(event.target.value.toUpperCase())} maxLength={4} placeholder="PDB ID，例如 4ZAU" aria-label="RCSB PDB ID" /><button className="button button-primary" disabled={!/^[0-9][A-Z0-9]{3}$/.test(pdbId) || importRcsb.isPending} onClick={() => importRcsb.mutate()}><Download size={16} />获取结构</button></div></div>
        <div className="stack"><strong>采用已上传 PDB</strong><div className="row"><select value={sourceFileId} onChange={(event) => setSourceFileId(event.target.value)} aria-label="已上传 PDB"><option value="">选择项目 PDB</option>{pdbFiles.map((file) => <option key={file.file_id} value={file.file_id}>{file.filename}</option>)}</select><button className="button" disabled={!sourceFileId || registerUpload.isPending} onClick={() => registerUpload.mutate()}><Check size={16} />登记结构</button></div></div>
      </div>
      {error && <div className="notice notice-danger">{error.message}</div>}
      {structures.length > 0 && <div className="table-scroll"><table className="data-table"><thead><tr><th>结构</th><th>来源</th><th>结构摘要</th><th>状态</th><th>操作</th></tr></thead><tbody>{structures.map((structure) => <tr key={structure.structure_id}><td><strong>{structure.source_identifier}</strong><div className="subtle mono">{structure.structure_id}</div></td><td>{structure.source === 'rcsb_pdb' ? 'RCSB PDB' : '用户上传'}</td><td>{structure.metadata.experimental_method || 'PDB'}{structure.metadata.resolution ? ` · ${structure.metadata.resolution} Å` : ''}<div className="subtle">{structure.metadata.pdb_summary?.atom_count ?? 0} atoms · {(structure.metadata.pdb_summary?.chain_ids || []).join(', ') || '无链标记'}</div></td><td><StatusBadge status={structure.is_active ? 'completed' : structure.status} /></td><td><div className="row-wrap">{!structure.is_active && <button className="button" onClick={() => activate.mutate(structure.structure_id)}>设为当前</button>}{structure.is_active && <button className="button" onClick={() => predict.mutate(structure.structure_id)} disabled={predict.isPending}><ScanSearch size={15} />运行 P2Rank</button>}{structure.is_active && <button className="button" onClick={() => prepare.mutate(structure.structure_id)} disabled={prepare.isPending}><Wrench size={15} />准备 PDBQT</button>}</div></td></tr>)}</tbody></table></div>}
      {activeSites.length > 0 && <div className="table-scroll"><table className="data-table"><thead><tr><th>口袋</th><th>P2Rank</th><th>中心 / 网格</th><th>附近残基</th><th>选择</th></tr></thead><tbody>{activeSites.map((site) => <tr key={site.binding_site_id}><td><strong>Pocket {site.grid_box.p2rank_rank ?? '-'}</strong><div className="subtle mono">{site.binding_site_id}</div></td><td>{site.grid_box.p2rank_score?.toFixed(2) ?? '-'}<div className="subtle">P {site.grid_box.p2rank_probability?.toFixed(3) ?? '-'}</div></td><td className="mono">{site.grid_box.center?.map((value) => value.toFixed(1)).join(', ')}<div className="subtle">{site.grid_box.size?.map((value) => value.toFixed(1)).join(' × ')}</div></td><td>{site.key_residues.slice(0, 5).join(', ') || '-'}</td><td>{readiness?.binding_site_id === site.binding_site_id ? <StatusBadge status="completed" /> : <button className="button" onClick={() => selectSite.mutate(site.binding_site_id)} disabled={selectSite.isPending}><Check size={15} />选择</button>}</td></tr>)}</tbody></table></div>}
      <div className={readiness?.ready ? 'notice' : 'notice notice-warning'}>{readiness?.ready ? `结构输入已就绪：${readiness.binding_site_id}` : readiness?.reason_codes.join(' · ') || '请先获取或登记一个受体结构。'}</div>
    </div>
  </section>;
}
