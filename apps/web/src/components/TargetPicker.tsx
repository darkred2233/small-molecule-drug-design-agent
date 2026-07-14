import { type ReactNode, useMemo, useState } from 'react';
import { useQuery } from '@tanstack/react-query';
import {
  Atom,
  Check,
  Database,
  FlaskConical,
  Info,
  Loader2,
  MapPin,
  Plus,
  Search,
  ShieldAlert,
  Target,
} from 'lucide-react';
import { projectsApi } from '@/api';
import type { BuiltinTarget, TargetBindingSite } from '@/types/api';
import { cn } from '@/utils/helpers';

export type TargetSelection =
  | { kind: 'builtin'; target: BuiltinTarget }
  | { kind: 'custom'; target_id: string; label: string };

interface TargetPickerProps {
  selectedTargetId?: string;
  selectedCustomTarget?: string;
  onSelect: (selection: TargetSelection) => void;
}

const ALPHABET = 'ABCDEFGHIJKLMNOPQRSTUVWXYZ'.split('');

export default function TargetPicker({
  selectedTargetId,
  selectedCustomTarget,
  onSelect,
}: TargetPickerProps) {
  const [searchQuery, setSearchQuery] = useState('');
  const [activeLetter, setActiveLetter] = useState('');

  const { data: targets = [], isLoading } = useQuery({
    queryKey: ['builtin-targets'],
    queryFn: projectsApi.getBuiltinTargets,
  });

  const selectedTarget = useMemo(
    () => targets.find((target) => target.target_id === selectedTargetId) ?? null,
    [selectedTargetId, targets]
  );

  const normalizedQuery = searchQuery.trim().toLowerCase();
  const filteredTargets = useMemo(() => {
    const result = targets.filter((target) => {
      if (!normalizedQuery) return true;
      return [
        target.name,
        target.target_id,
        target.uniprot_id ?? '',
        target.summary ?? '',
        target.pocket_summary ?? '',
        ...target.aliases,
        ...target.pdb_ids,
      ]
        .join(' ')
        .toLowerCase()
        .includes(normalizedQuery);
    });

    return result.sort((a, b) => a.name.localeCompare(b.name));
  }, [normalizedQuery, targets]);

  const availableLetters = useMemo(() => {
    return new Set(targets.map((target) => getTargetLetter(target.name)));
  }, [targets]);

  const visibleTargets = activeLetter
    ? filteredTargets.filter((target) => getTargetLetter(target.name) === activeLetter)
    : filteredTargets;

  const groupedTargets = useMemo(() => {
    return visibleTargets.reduce<Record<string, BuiltinTarget[]>>((groups, target) => {
      const letter = getTargetLetter(target.name);
      groups[letter] = groups[letter] ?? [];
      groups[letter].push(target);
      return groups;
    }, {});
  }, [visibleTargets]);

  const hasExactMatch = targets.some(
    (target) =>
      target.name.toLowerCase() === normalizedQuery ||
      target.target_id.toLowerCase() === normalizedQuery ||
      target.aliases.some((alias) => alias.toLowerCase() === normalizedQuery)
  );
  const customLabel = searchQuery.trim();

  return (
    <div className="grid gap-4 lg:grid-cols-[minmax(0,1fr)_22rem]">
      <div className="space-y-3">
        <div className="relative">
          <Search className="pointer-events-none absolute left-3 top-1/2 h-4 w-4 -translate-y-1/2 text-cyan-600" />
          <input
            type="text"
            value={searchQuery}
            onChange={(event) => {
              setSearchQuery(event.target.value);
              setActiveLetter('');
            }}
            placeholder="搜索靶点、别名、PDB 或 UniProt"
            className="h-11 w-full rounded-lg border border-cyan-200 bg-white px-4 pl-10 text-sm text-slate-900 shadow-sm shadow-cyan-950/5 focus:outline-none focus:ring-2 focus:ring-cyan-500"
          />
        </div>

        <div className="flex flex-wrap gap-1 rounded-lg border border-cyan-100 bg-cyan-50/60 p-2">
          <button
            type="button"
            onClick={() => setActiveLetter('')}
            className={cn(
              'h-7 rounded-md px-2 text-xs font-medium transition-colors',
              activeLetter === ''
                ? 'bg-cyan-700 text-white'
                : 'text-slate-600 hover:bg-white hover:text-cyan-800'
            )}
          >
            全部
          </button>
          {ALPHABET.map((letter) => {
            const enabled = availableLetters.has(letter);
            return (
              <button
                key={letter}
                type="button"
                onClick={() => enabled && setActiveLetter(activeLetter === letter ? '' : letter)}
                disabled={!enabled}
                className={cn(
                  'h-7 w-7 rounded-md text-xs font-medium transition-colors',
                  activeLetter === letter
                    ? 'bg-cyan-700 text-white'
                    : enabled
                      ? 'text-slate-600 hover:bg-white hover:text-cyan-800'
                      : 'cursor-not-allowed text-slate-300'
                )}
              >
                {letter}
              </button>
            );
          })}
        </div>

        {customLabel && !hasExactMatch && (
          <button
            type="button"
            onClick={() =>
              onSelect({
                kind: 'custom',
                target_id: buildCustomTargetId(customLabel),
                label: customLabel,
              })
            }
            className={cn(
              'flex w-full items-start gap-3 rounded-lg border p-3 text-left transition-colors',
              selectedCustomTarget === customLabel
                ? 'border-emerald-400 bg-emerald-50 ring-1 ring-emerald-400'
                : 'border-emerald-200 bg-white hover:bg-emerald-50/70'
            )}
          >
            <span className="mt-0.5 rounded-md bg-emerald-100 p-2 text-emerald-700">
              <Plus className="h-4 w-4" />
            </span>
            <span className="min-w-0 flex-1">
              <span className="block text-sm font-semibold text-slate-900">
                使用自定义靶点：{customLabel}
              </span>
              <span className="mt-1 block text-xs text-slate-500">
                项目会保留该靶点名称，后续可上传 PDB 或在对话中补充口袋信息。
              </span>
            </span>
          </button>
        )}

        <div className="max-h-[28rem] overflow-y-auto rounded-lg border border-cyan-100 bg-white">
          {isLoading ? (
            <div className="flex items-center justify-center gap-2 py-10 text-sm text-slate-500">
              <Loader2 className="h-4 w-4 animate-spin text-cyan-600" />
              正在加载靶点库
            </div>
          ) : visibleTargets.length === 0 ? (
            <div className="py-10 text-center text-sm text-slate-500">未找到匹配靶点</div>
          ) : (
            <div className="divide-y divide-cyan-50">
              {Object.entries(groupedTargets)
                .sort(([a], [b]) => a.localeCompare(b))
                .map(([letter, items]) => (
                  <div key={letter}>
                    <div className="sticky top-0 z-10 border-b border-cyan-50 bg-cyan-50 px-3 py-1 text-xs font-semibold text-cyan-800">
                      {letter}
                    </div>
                    {items.map((target) => (
                      <TargetOption
                        key={target.target_id}
                        target={target}
                        selected={selectedTargetId === target.target_id}
                        onSelect={() => onSelect({ kind: 'builtin', target })}
                      />
                    ))}
                  </div>
                ))}
            </div>
          )}
        </div>
      </div>

      <SelectionDetail target={selectedTarget} customTarget={selectedCustomTarget} />
    </div>
  );
}

function TargetOption({
  target,
  selected,
  onSelect,
}: {
  target: BuiltinTarget;
  selected: boolean;
  onSelect: () => void;
}) {
  const site = target.binding_sites?.[0];

  return (
    <button
      type="button"
      onClick={onSelect}
      className={cn(
        'flex w-full gap-3 px-3 py-3 text-left transition-colors',
        selected ? 'bg-cyan-50' : 'hover:bg-cyan-50/50'
      )}
    >
      <span
        className={cn(
          'mt-0.5 rounded-lg p-2',
          selected ? 'bg-cyan-600 text-white' : 'bg-cyan-50 text-cyan-700'
        )}
      >
        <Target className="h-4 w-4" />
      </span>
      <span className="min-w-0 flex-1">
        <span className="flex flex-wrap items-center gap-2">
          <span className="font-semibold text-slate-950">{target.name}</span>
          <span className="rounded bg-slate-100 px-2 py-0.5 font-mono text-[11px] text-slate-600">
            {target.target_id}
          </span>
          {selected && <Check className="h-4 w-4 text-cyan-700" />}
        </span>
        <span className="mt-1 line-clamp-2 block text-xs leading-5 text-slate-500">
          {target.pocket_summary ?? target.summary}
        </span>
        <span className="mt-2 flex flex-wrap gap-2 text-[11px]">
          {target.pdb_ids.slice(0, 3).map((pdbId) => (
            <Badge key={pdbId} tone="cyan">
              PDB {pdbId}
            </Badge>
          ))}
          <Badge tone="emerald">{target.seed_ligand_count || target.drugs.length} 个样例分子</Badge>
          {site?.key_residues?.slice(0, 2).map((residue) => (
            <Badge key={residue} tone="slate">
              {residue}
            </Badge>
          ))}
        </span>
      </span>
    </button>
  );
}

function SelectionDetail({
  target,
  customTarget,
}: {
  target: BuiltinTarget | null;
  customTarget?: string;
}) {
  if (!target && !customTarget) {
    return (
      <aside className="rounded-lg border border-dashed border-cyan-200 bg-cyan-50/40 p-4 text-sm text-slate-500">
        <div className="flex items-center gap-2 font-medium text-slate-700">
          <Info className="h-4 w-4 text-cyan-700" />
          等待选择靶点
        </div>
        <p className="mt-2 leading-6">
          选择后这里会显示代表 PDB、口袋网格、关键残基、SAR 规则和 ADMET 风险。
        </p>
      </aside>
    );
  }

  if (!target) {
    return (
      <aside className="rounded-lg border border-emerald-200 bg-emerald-50/60 p-4">
        <div className="flex items-center gap-2 text-sm font-semibold text-emerald-900">
          <Plus className="h-4 w-4" />
          {customTarget}
        </div>
        <p className="mt-2 text-sm leading-6 text-emerald-800">
          自定义靶点已选中。创建项目后可继续上传结构文件、给出口袋坐标或让 Agent 在对话中补齐假设。
        </p>
      </aside>
    );
  }

  const site = target.binding_sites?.[0];

  return (
    <aside className="space-y-3 rounded-lg border border-cyan-100 bg-white p-4 shadow-sm shadow-cyan-950/5">
      <div>
        <div className="flex items-center gap-2 text-sm font-semibold text-slate-950">
          <Atom className="h-4 w-4 text-cyan-700" />
          {target.name}
        </div>
        <p className="mt-2 text-xs leading-5 text-slate-500">{target.summary}</p>
      </div>

      <div className="grid grid-cols-2 gap-2 text-xs">
        <DetailMetric icon={<Database className="h-3.5 w-3.5" />} label="样例分子" value={target.seed_ligand_count || target.drugs.length} />
        <DetailMetric icon={<MapPin className="h-3.5 w-3.5" />} label="PDB" value={target.pdb_ids.length} />
        <DetailMetric icon={<FlaskConical className="h-3.5 w-3.5" />} label="SAR" value={target.sar_rules.length} />
        <DetailMetric icon={<ShieldAlert className="h-3.5 w-3.5" />} label="ADMET" value={target.admet_risks.length} />
      </div>

      {site && <PocketSummary site={site} />}

      <div className="space-y-2">
        {target.sar_rules.slice(0, 2).map((rule) => (
          <div key={rule.rule_id ?? rule.title} className="rounded-lg border border-cyan-100 bg-cyan-50/50 p-3">
            <div className="text-xs font-semibold text-cyan-900">{rule.title}</div>
            <div className="mt-1 text-[11px] leading-4 text-slate-600">{rule.preferred_change}</div>
          </div>
        ))}
      </div>

      {target.admet_risks.length > 0 && (
        <div className="flex flex-wrap gap-2">
          {target.admet_risks.map((risk) => (
            <Badge key={risk.risk_id ?? risk.category} tone={risk.severity === 'high' ? 'rose' : 'amber'}>
              {risk.category}: {risk.severity}
            </Badge>
          ))}
        </div>
      )}
    </aside>
  );
}

function PocketSummary({ site }: { site: TargetBindingSite }) {
  const center = formatVector(site.grid_box?.center);
  const size = formatVector(site.grid_box?.size);

  return (
    <div className="rounded-lg border border-emerald-100 bg-emerald-50/60 p-3 text-xs">
      <div className="flex items-center justify-between gap-2">
        <span className="font-semibold text-emerald-900">{site.site_name ?? site.pdb_id}</span>
        {site.pdb_id && <Badge tone="emerald">{site.pdb_id}</Badge>}
      </div>
      <div className="mt-2 grid gap-1 text-slate-600">
        {site.reference_ligand && <span>参考配体：{site.reference_ligand}</span>}
        {center && <span>中心：{center}</span>}
        {size && <span>尺寸：{size}</span>}
      </div>
      {site.key_residues && site.key_residues.length > 0 && (
        <div className="mt-2 flex flex-wrap gap-1">
          {site.key_residues.slice(0, 6).map((residue) => (
            <span key={residue} className="rounded bg-white px-1.5 py-0.5 text-[11px] text-emerald-800">
              {residue}
            </span>
          ))}
        </div>
      )}
    </div>
  );
}

function DetailMetric({
  icon,
  label,
  value,
}: {
  icon: ReactNode;
  label: string;
  value: number;
}) {
  return (
    <div className="rounded-lg border border-cyan-100 bg-cyan-50/40 p-2">
      <div className="flex items-center gap-1 text-cyan-700">
        {icon}
        <span>{label}</span>
      </div>
      <div className="mt-1 text-base font-semibold text-slate-950">{value}</div>
    </div>
  );
}

function Badge({ children, tone }: { children: ReactNode; tone: 'cyan' | 'emerald' | 'slate' | 'amber' | 'rose' }) {
  const tones = {
    cyan: 'border-cyan-200 bg-cyan-50 text-cyan-800',
    emerald: 'border-emerald-200 bg-emerald-50 text-emerald-800',
    slate: 'border-slate-200 bg-slate-50 text-slate-700',
    amber: 'border-amber-200 bg-amber-50 text-amber-800',
    rose: 'border-rose-200 bg-rose-50 text-rose-800',
  };

  return (
    <span className={cn('inline-flex items-center rounded-md border px-2 py-0.5 text-[11px] font-medium', tones[tone])}>
      {children}
    </span>
  );
}

function getTargetLetter(name: string) {
  const letter = name.trim().charAt(0).toUpperCase();
  return /^[A-Z]$/.test(letter) ? letter : '#';
}

function buildCustomTargetId(label: string) {
  const normalized = label
    .trim()
    .toUpperCase()
    .replace(/[^A-Z0-9]+/g, '-')
    .replace(/^-+|-+$/g, '');
  const hash = Array.from(label).reduce((value, char) => value + char.charCodeAt(0), 0).toString(36).toUpperCase();
  return `CUSTOM-${normalized || 'TARGET'}-${hash.slice(0, 5)}`;
}

function formatVector(values?: number[] | null) {
  if (!values || values.length === 0) return '';
  return values.map((value) => value.toFixed(2)).join(', ');
}
