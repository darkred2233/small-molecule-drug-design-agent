import { useMemo, useState } from 'react';
import { useMutation, useQuery } from '@tanstack/react-query';
import { ArrowLeft, ArrowRight, FileText, FlaskConical, Target } from 'lucide-react';
import { Link, useNavigate } from 'react-router-dom';
import { projectsApi } from '@/api/projects';
import type { BuiltinTarget, Project, SeedLigandInput } from '@/types/workbench';

function parseSeeds(value: string): SeedLigandInput[] {
  return value.split(/\r?\n/).map((line) => line.trim()).filter(Boolean).map((line, index) => {
    const [smiles, ...name] = line.split(/\s+/);
    return { smiles, name: name.join(' ') || `用户 Seed ${index + 1}`, source: 'user_input' };
  });
}

export function ProjectSetupPage() {
  const navigate = useNavigate();
  const [name, setName] = useState('');
  const [targetId, setTargetId] = useState('');
  const [customTarget, setCustomTarget] = useState('');
  const [objective, setObjective] = useState('');
  const [seedText, setSeedText] = useState('');
  const [mwMax, setMwMax] = useState('500');
  const [topN, setTopN] = useState('20');
  const { data: targets = [], isLoading: targetsLoading } = useQuery<BuiltinTarget[], Error>({ queryKey: ['builtin-targets'], queryFn: projectsApi.builtinTargets });
  const seeds = useMemo(() => parseSeeds(seedText), [seedText]);
  const createProject = useMutation<Project, Error>({
    mutationFn: () => projectsApi.create({ name: name.trim(), target_id: targetId || undefined, target_name: customTarget.trim() || undefined, objective: objective.trim() || undefined, seed_ligands: seeds.length ? seeds : undefined, constraints: { mw_max: Number(mwMax) || undefined, top_n: Number(topN) || undefined, objective_source: 'user_setup' } }),
    onSuccess: (project) => navigate(`/projects/${project.project_id}/data`),
  });

  const ready = Boolean(name.trim() && (targetId || customTarget.trim()));
  return <main className="page" style={{ padding: '34px 28px', maxWidth: 1060 }}>
    <div className="page-heading"><div><p className="eyebrow">新建设计项目</p><h1>准备靶点、Seed 与设计目标</h1><p className="subtle">项目创建后仍可继续上传结构、配体和文献；首轮策略由 Agent 基于全部已知数据生成。</p></div><Link to="/projects" className="button"><ArrowLeft size={16} />返回项目</Link></div>
    <div className="section-stack">
      <section className="panel"><div className="panel-header"><div className="row"><Target size={17} color="#176451" /><h2>1. 靶点</h2></div></div><div className="panel-body form-grid"><div className="field"><label htmlFor="project-name">项目名称</label><input id="project-name" value={name} onChange={(event) => setName(event.target.value)} placeholder="例如：EGFR 选择性抑制剂探索" /></div><div className="field"><label htmlFor="target">内置靶点</label><select id="target" value={targetId} onChange={(event) => { setTargetId(event.target.value); if (event.target.value) setCustomTarget(''); }} disabled={targetsLoading}><option value="">{targetsLoading ? '正在载入靶点…' : '选择内置靶点'}</option>{targets.map((target) => <option key={target.target_id} value={target.target_id}>{target.name} · {target.target_id}</option>)}</select></div><div className="field" style={{ gridColumn: '1 / -1' }}><label htmlFor="custom-target">或输入自定义靶点名称</label><input id="custom-target" value={customTarget} onChange={(event) => { setCustomTarget(event.target.value); if (event.target.value) setTargetId(''); }} placeholder="例如：KRAS G12D 或自定义蛋白靶点" /></div></div></section>
      <section className="panel"><div className="panel-header"><div className="row"><FlaskConical size={17} color="#176451" /><h2>2. 设计目标与 Seed</h2></div></div><div className="panel-body section-stack"><div className="field"><label htmlFor="objective">用自然语言描述设计目标</label><textarea id="objective" value={objective} onChange={(event) => setObjective(event.target.value)} placeholder="例如：提高对 EGFR 的结合潜力，分子量不超过 500，尽量避免 hERG 风险，并保留结构多样性。" /></div><div className="form-grid"><div className="field"><label htmlFor="mw-max">分子量上限</label><input id="mw-max" type="number" min="100" value={mwMax} onChange={(event) => setMwMax(event.target.value)} /></div><div className="field"><label htmlFor="top-n">每轮保留候选数</label><input id="top-n" type="number" min="1" value={topN} onChange={(event) => setTopN(event.target.value)} /></div></div><div className="field"><label htmlFor="seeds">初始 Seed（每行一个，格式：SMILES 可选名称）</label><textarea id="seeds" value={seedText} onChange={(event) => setSeedText(event.target.value)} placeholder={'CCO ethanol\nc1ccccc1 benzene'} /><div className="subtle">当前识别 {seeds.length} 个 Seed。也可在下一步上传 SDF、SMI 或 CSV。</div></div></div></section>
      <section className="panel"><div className="panel-header"><div className="row"><FileText size={17} color="#176451" /><h2>3. 创建后继续补充资料</h2></div></div><div className="panel-body"><div className="notice">下一页支持上传 PDB 靶点结构、SDF/SMI/CSV 配体数据和论文资料。所有文献会以项目范围保存，并可在分子详情中追溯引用。</div></div></section>
    </div>
    {createProject.error && <div className="notice notice-danger" style={{ marginTop: 16 }}>{createProject.error instanceof Error ? createProject.error.message : '项目创建失败。'}</div>}
    <div className="row" style={{ justifyContent: 'flex-end', marginTop: 20 }}><button className="button button-primary" onClick={() => createProject.mutate()} disabled={!ready || createProject.isPending}>{createProject.isPending ? '正在创建…' : '创建项目并导入资料'} <ArrowRight size={16} /></button></div>
  </main>;
}
