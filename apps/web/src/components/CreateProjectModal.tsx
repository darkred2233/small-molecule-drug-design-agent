import { type FormEvent, useMemo, useState } from 'react';
import { useMutation, useQueryClient } from '@tanstack/react-query';
import { useNavigate } from 'react-router-dom';
import { ArrowLeft, CheckCircle2, FlaskConical, Loader2, Target, X } from 'lucide-react';
import { projectsApi } from '@/api';
import type { BuiltinDrug, BuiltinTarget, SeedLigandInput } from '@/types/api';
import { cn } from '@/utils/helpers';
import TargetPicker, { type TargetSelection } from './TargetPicker';

interface CreateProjectModalProps {
  isOpen: boolean;
  onClose: () => void;
}

export default function CreateProjectModal({ isOpen, onClose }: CreateProjectModalProps) {
  const navigate = useNavigate();
  const queryClient = useQueryClient();

  const [step, setStep] = useState<'target' | 'details'>('target');
  const [selection, setSelection] = useState<TargetSelection | null>(null);
  const [projectName, setProjectName] = useState('');
  const [objective, setObjective] = useState('');
  const [selectedSeedKeys, setSelectedSeedKeys] = useState<string[]>([]);
  const [customSeedText, setCustomSeedText] = useState('');

  const selectedTargetId = selection?.kind === 'builtin' ? selection.target.target_id : selection?.target_id;
  const selectedBuiltin = selection?.kind === 'builtin' ? selection.target : null;
  const builtinSeedDrugs = useMemo(
    () => selectedBuiltin?.drugs.filter((drug) => getDrugSmiles(drug)) ?? [],
    [selectedBuiltin]
  );
  const seedLigands = useMemo(
    () => [
      ...builtinSeedDrugs
        .filter((drug) => selectedSeedKeys.includes(seedKey(drug)))
        .map((drug): SeedLigandInput => ({
          name: drug.drug_name,
          smiles: getDrugSmiles(drug)!,
          source: selectedBuiltin ? `target_library:${selectedBuiltin.target_id}` : 'target_library',
        })),
      ...parseCustomSeeds(customSeedText),
    ],
    [builtinSeedDrugs, customSeedText, selectedBuiltin, selectedSeedKeys]
  );

  const createProject = useMutation({
    mutationFn: projectsApi.create,
    onSuccess: (project) => {
      queryClient.invalidateQueries({ queryKey: ['projects'] });
      resetForm();
      onClose();
      navigate(`/workspace/${project.project_id}`);
    },
  });

  const defaultObjective = useMemo(() => {
    if (selectedBuiltin) {
      const firstRule = selectedBuiltin.sar_rules[0]?.title;
      const firstRisk = selectedBuiltin.admet_risks[0]?.category;
      return [
        selectedBuiltin.pocket_summary,
        firstRule ? `优先满足 SAR：${firstRule}` : '',
        firstRisk ? `重点监控 ADMET：${firstRisk}` : '',
      ]
        .filter(Boolean)
        .join('\n');
    }
    if (selection?.kind === 'custom') {
      return `围绕 ${selection.label} 进行小分子设计，先补齐结构、口袋、活性分子和 ADMET 约束。`;
    }
    return '';
  }, [selectedBuiltin, selection]);

  const resetForm = () => {
    setStep('target');
    setSelection(null);
    setProjectName('');
    setObjective('');
    setSelectedSeedKeys([]);
    setCustomSeedText('');
  };

  const handleClose = () => {
    resetForm();
    onClose();
  };

  const handleTargetSelect = (nextSelection: TargetSelection) => {
    setSelection(nextSelection);
    const label = nextSelection.kind === 'builtin' ? nextSelection.target.name : nextSelection.label;
    if (!projectName.trim()) {
      setProjectName(`${label} 药物设计`);
    }
    setSelectedSeedKeys(nextSelection.kind === 'builtin' ? defaultSeedKeys(nextSelection.target) : []);
    setCustomSeedText('');
  };

  const handleNext = () => {
    if (!selection) return;
    if (!objective.trim() && defaultObjective) {
      setObjective(defaultObjective);
    }
    setStep('details');
  };

  const toggleSeed = (drug: BuiltinDrug) => {
    const key = seedKey(drug);
    setSelectedSeedKeys((current) =>
      current.includes(key) ? current.filter((item) => item !== key) : [...current, key]
    );
  };

  const handleSubmit = (event?: FormEvent) => {
    event?.preventDefault();
    if (!selection || !projectName.trim() || seedLigands.length < 1) return;

    createProject.mutate({
      name: projectName.trim(),
      target_id: selectedTargetId,
      target_name: selection.kind === 'custom' ? selection.label : undefined,
      objective: objective.trim() || undefined,
      seed_ligands: seedLigands,
    });
  };

  if (!isOpen) return null;

  return (
    <div className="fixed inset-0 z-50 flex items-center justify-center bg-slate-950/45 p-4 backdrop-blur-sm">
      <div className="flex max-h-[92vh] w-full max-w-5xl flex-col rounded-lg border border-cyan-100 bg-white shadow-xl shadow-cyan-950/20">
        <div className="flex items-center justify-between border-b border-cyan-100 px-6 py-5">
          <div className="min-w-0">
            <div className="flex items-center gap-2">
              <Target className="h-5 w-5 text-cyan-700" />
              <h2 className="text-xl font-semibold text-slate-950">新建药物设计项目</h2>
            </div>
            <div className="mt-3 flex items-center gap-2 text-xs">
              <StepPill active={step === 'target'} done={Boolean(selection)} label="选择靶点" />
              <span className="h-px w-8 bg-cyan-100" />
              <StepPill active={step === 'details'} done={false} label="样例分子" />
            </div>
          </div>
          <button
            type="button"
            onClick={handleClose}
            className="rounded-lg p-2 text-slate-500 transition-colors hover:bg-cyan-50 hover:text-cyan-800"
            aria-label="关闭"
          >
            <X className="h-5 w-5" />
          </button>
        </div>

        <div className="flex-1 overflow-y-auto p-6">
          {step === 'target' ? (
            <TargetPicker
              selectedTargetId={selectedTargetId}
              selectedCustomTarget={selection?.kind === 'custom' ? selection.label : undefined}
              onSelect={handleTargetSelect}
            />
          ) : (
            <form onSubmit={handleSubmit} className="grid gap-6 lg:grid-cols-[minmax(0,1fr)_22rem]">
              <div className="space-y-5">
                <label className="block">
                  <span className="mb-2 block text-sm font-medium text-slate-700">
                    项目名称 <span className="text-rose-500">*</span>
                  </span>
                  <input
                    type="text"
                    value={projectName}
                    onChange={(event) => setProjectName(event.target.value)}
                    placeholder="例如：EGFR 药物设计"
                    required
                    className="h-11 w-full rounded-lg border border-cyan-200 bg-white px-4 text-sm text-slate-900 shadow-sm shadow-cyan-950/5 focus:outline-none focus:ring-2 focus:ring-cyan-500"
                  />
                </label>

                <label className="block">
                  <span className="mb-2 block text-sm font-medium text-slate-700">优化目标</span>
                  <textarea
                    value={objective}
                    onChange={(event) => setObjective(event.target.value)}
                    placeholder="例如：降低 hERG 风险，保留关键 hinge 结合模式，并保持可合成性。"
                    rows={5}
                    className="w-full resize-none rounded-lg border border-cyan-200 bg-white px-4 py-3 text-sm leading-6 text-slate-900 shadow-sm shadow-cyan-950/5 focus:outline-none focus:ring-2 focus:ring-cyan-500"
                  />
                </label>

                <SeedSelectionPanel
                  builtinSeedDrugs={builtinSeedDrugs}
                  selectedSeedKeys={selectedSeedKeys}
                  customSeedText={customSeedText}
                  onToggleSeed={toggleSeed}
                  onCustomSeedTextChange={setCustomSeedText}
                />

                {seedLigands.length < 1 && (
                  <div className="rounded-lg border border-amber-200 bg-amber-50 px-3 py-2 text-sm text-amber-800">
                    至少选择或填写一个样例分子，后续生成 agent 才有 seed 可以继承。
                  </div>
                )}

                {createProject.error && (
                  <div className="rounded-lg border border-rose-200 bg-rose-50 p-3 text-sm text-rose-700">
                    创建失败，请检查后端服务和靶点参数。
                  </div>
                )}
              </div>

              <SelectedTargetPanel selection={selection} builtinTarget={selectedBuiltin} seedCount={seedLigands.length} />
            </form>
          )}
        </div>

        <div className="flex items-center justify-between border-t border-cyan-100 bg-cyan-50/50 px-6 py-4">
          <button
            type="button"
            onClick={step === 'target' ? handleClose : () => setStep('target')}
            className="secondary-action inline-flex items-center gap-2 rounded-lg px-4 py-2 text-sm font-medium"
          >
            {step === 'target' ? (
              '取消'
            ) : (
              <>
                <ArrowLeft className="h-4 w-4" />
                上一步
              </>
            )}
          </button>

          {step === 'target' ? (
            <button
              type="button"
              onClick={handleNext}
              disabled={!selection}
              className="primary-action inline-flex items-center gap-2 rounded-lg px-6 py-2 text-sm font-medium transition-colors disabled:cursor-not-allowed"
            >
              下一步
            </button>
          ) : (
            <button
              type="button"
              onClick={() => handleSubmit()}
              disabled={!selection || !projectName.trim() || seedLigands.length < 1 || createProject.isPending}
              className="primary-action inline-flex items-center gap-2 rounded-lg px-6 py-2 text-sm font-medium transition-colors disabled:cursor-not-allowed"
            >
              {createProject.isPending && <Loader2 className="h-4 w-4 animate-spin" />}
              {createProject.isPending ? '创建中' : '创建项目'}
            </button>
          )}
        </div>
      </div>
    </div>
  );
}

function SeedSelectionPanel({
  builtinSeedDrugs,
  selectedSeedKeys,
  customSeedText,
  onToggleSeed,
  onCustomSeedTextChange,
}: {
  builtinSeedDrugs: BuiltinDrug[];
  selectedSeedKeys: string[];
  customSeedText: string;
  onToggleSeed: (drug: BuiltinDrug) => void;
  onCustomSeedTextChange: (value: string) => void;
}) {
  return (
    <section className="space-y-3">
      <div>
        <h3 className="text-sm font-semibold text-slate-950">样例分子</h3>
        <p className="mt-1 text-xs leading-5 text-slate-500">
          这些分子会作为第一轮 seed；继续运行时系统会自动用上一轮排名靠前的分子补充下一轮 seed。
        </p>
      </div>

      {builtinSeedDrugs.length > 0 && (
        <div className="grid gap-2 sm:grid-cols-2">
          {builtinSeedDrugs.map((drug) => {
            const key = seedKey(drug);
            const selected = selectedSeedKeys.includes(key);
            return (
              <button
                key={key}
                type="button"
                onClick={() => onToggleSeed(drug)}
                className={cn(
                  'rounded-lg border p-3 text-left transition-colors',
                  selected
                    ? 'border-cyan-300 bg-cyan-50 text-cyan-950'
                    : 'border-slate-200 bg-white text-slate-700 hover:border-cyan-200'
                )}
              >
                <div className="flex items-center justify-between gap-3">
                  <div className="min-w-0">
                    <div className="truncate text-sm font-semibold">{drug.drug_name}</div>
                    {drug.drug_status && <div className="mt-0.5 text-xs text-slate-500">{drug.drug_status}</div>}
                  </div>
                  <span
                    className={cn(
                      'flex h-5 w-5 items-center justify-center rounded-full border',
                      selected ? 'border-cyan-600 bg-cyan-600 text-white' : 'border-slate-300 bg-white'
                    )}
                  >
                    {selected && <CheckCircle2 className="h-4 w-4" />}
                  </span>
                </div>
                <code className="mt-2 block truncate rounded bg-white/70 px-2 py-1 text-[11px] text-slate-600">
                  {getDrugSmiles(drug)}
                </code>
              </button>
            );
          })}
        </div>
      )}

      <label className="block">
        <span className="mb-2 block text-xs font-medium text-slate-600">自定义 seed SMILES</span>
        <textarea
          value={customSeedText}
          onChange={(event) => onCustomSeedTextChange(event.target.value)}
          placeholder="每行一个，可写：名称 SMILES"
          rows={4}
          className="w-full resize-none rounded-lg border border-cyan-200 bg-white px-4 py-3 font-mono text-xs leading-5 text-slate-900 shadow-sm shadow-cyan-950/5 focus:outline-none focus:ring-2 focus:ring-cyan-500"
        />
      </label>
    </section>
  );
}

function StepPill({ active, done, label }: { active: boolean; done: boolean; label: string }) {
  return (
    <span
      className={cn(
        'inline-flex items-center gap-1 rounded-full border px-2.5 py-1 font-medium',
        active
          ? 'border-cyan-300 bg-cyan-50 text-cyan-800'
          : done
            ? 'border-emerald-300 bg-emerald-50 text-emerald-800'
            : 'border-slate-200 bg-slate-50 text-slate-500'
      )}
    >
      {done && <CheckCircle2 className="h-3.5 w-3.5" />}
      {label}
    </span>
  );
}

function SelectedTargetPanel({
  selection,
  builtinTarget,
  seedCount,
}: {
  selection: TargetSelection | null;
  builtinTarget: BuiltinTarget | null;
  seedCount: number;
}) {
  if (!selection) return null;

  if (selection.kind === 'custom') {
    return (
      <aside className="rounded-lg border border-emerald-200 bg-emerald-50/60 p-4">
        <div className="text-sm font-semibold text-emerald-900">自定义靶点</div>
        <div className="mt-1 text-lg font-semibold text-slate-950">{selection.label}</div>
        <div className="mt-2 rounded bg-white px-2 py-1 font-mono text-xs text-emerald-700">
          {selection.target_id}
        </div>
        <PanelMetric label="已选 seed" value={seedCount} />
        <p className="mt-3 text-sm leading-6 text-emerald-800">
          项目创建后可在对话中补充 PDB、口袋中心、参考配体或上传结构文件。
        </p>
      </aside>
    );
  }

  const site = builtinTarget?.binding_sites?.[0];

  return (
    <aside className="space-y-3 rounded-lg border border-cyan-100 bg-white p-4 shadow-sm shadow-cyan-950/5">
      <div>
        <div className="text-sm text-cyan-700">已选靶点</div>
        <div className="mt-1 text-lg font-semibold text-slate-950">{builtinTarget?.name}</div>
        <div className="mt-1 flex flex-wrap gap-2 text-xs">
          <span className="rounded bg-cyan-50 px-2 py-0.5 font-mono text-cyan-800">
            {builtinTarget?.target_id}
          </span>
          {builtinTarget?.uniprot_id && (
            <span className="rounded bg-slate-100 px-2 py-0.5 text-slate-700">
              UniProt {builtinTarget.uniprot_id}
            </span>
          )}
        </div>
      </div>

      <div className="grid grid-cols-2 gap-2 text-xs">
        <PanelMetric label="PDB" value={builtinTarget?.pdb_ids.length ?? 0} />
        <PanelMetric label="已选 seed" value={seedCount} />
        <PanelMetric label="SAR 规则" value={builtinTarget?.sar_rules.length ?? 0} />
        <PanelMetric label="ADMET 风险" value={builtinTarget?.admet_risks.length ?? 0} />
      </div>

      {site && (
        <div className="rounded-lg border border-emerald-100 bg-emerald-50/60 p-3 text-xs">
          <div className="flex items-center gap-2 font-semibold text-emerald-900">
            <FlaskConical className="h-4 w-4" />
            {site.site_name ?? site.pdb_id}
          </div>
          <div className="mt-2 space-y-1 text-slate-600">
            {site.reference_ligand && <div>参考配体：{site.reference_ligand}</div>}
            {site.grid_box?.center && <div>中心：{site.grid_box.center.map((value) => value.toFixed(2)).join(', ')}</div>}
            {site.grid_box?.size && <div>尺寸：{site.grid_box.size.map((value) => value.toFixed(2)).join(', ')}</div>}
          </div>
        </div>
      )}

      {builtinTarget?.pocket_summary && (
        <p className="text-sm leading-6 text-slate-600">{builtinTarget.pocket_summary}</p>
      )}
    </aside>
  );
}

function PanelMetric({ label, value }: { label: string; value: number }) {
  return (
    <div className="mt-3 rounded-lg border border-cyan-100 bg-cyan-50/50 p-3">
      <div className="text-slate-500">{label}</div>
      <div className="mt-1 text-lg font-semibold text-slate-950">{value}</div>
    </div>
  );
}

function defaultSeedKeys(target: BuiltinTarget) {
  return target.drugs.filter((drug) => getDrugSmiles(drug)).slice(0, 3).map(seedKey);
}

function seedKey(drug: BuiltinDrug) {
  return drug.inchi_key || drug.drug_name || getDrugSmiles(drug) || 'seed';
}

function getDrugSmiles(drug: BuiltinDrug) {
  return drug.smiles || drug.canonical_smiles || drug.isomeric_smiles;
}

function parseCustomSeeds(value: string): SeedLigandInput[] {
  return value
    .split(/\r?\n/)
    .map((line) => line.trim())
    .filter(Boolean)
    .map((line, index) => {
      const parts = line.split(/\s+/);
      const smiles = parts[parts.length - 1];
      const name = parts.length > 1 ? parts.slice(0, -1).join(' ') : `custom-seed-${index + 1}`;
      return {
        name,
        smiles,
        source: 'project_setup_custom',
      };
    });
}
