/**
 * Molecule Table Component
 *
 * Sortable and filterable table of molecules
 */

import { useState, useMemo } from 'react';
import { useParams, Link } from 'react-router-dom';
import { useQuery } from '@tanstack/react-query';
import { moleculesApi, assessmentApi } from '@/api';
import { ArrowUpDown, ExternalLink, FlaskConical, Trophy } from 'lucide-react';
import { cn, getStatusColor, formatNumber } from '@/utils/helpers';
import type { Molecule } from '@/types/api';

export default function MoleculeTable() {
  const { projectId } = useParams();
  const [sortField, setSortField] = useState<'rank' | 'overall_score'>('rank');
  const [sortDirection, setSortDirection] = useState<'asc' | 'desc'>('asc');
  const { data: molecules } = useQuery({
    queryKey: ['molecules', projectId],
    queryFn: () => moleculesApi.list(projectId!),
    enabled: !!projectId,
  });

  const { data: rankings } = useQuery({
    queryKey: ['rankings', projectId],
    queryFn: () => assessmentApi.getRankings(projectId!),
    enabled: !!projectId,
  });

  const displayMolecules = useMemo(() => {
    if (!rankings || !molecules) return [];
    const moleculeMap = new Map<string, Molecule>();
    molecules.forEach((molecule) => moleculeMap.set(molecule.molecule_id, molecule));

    return [...rankings].sort((a, b) => {
      if (sortField === 'rank') {
        return sortDirection === 'asc' ? a.rank - b.rank : b.rank - a.rank;
      }

      const valA = a.overall_score ?? -999;
      const valB = b.overall_score ?? -999;
      return sortDirection === 'asc' ? valA - valB : valB - valA;
    }).map((ranking) => ({
      ranking,
      molecule: moleculeMap.get(ranking.molecule_id),
    }));
  }, [molecules, rankings, sortField, sortDirection]);

  const toggleSort = (field: 'rank' | 'overall_score') => {
    if (sortField === field) {
      setSortDirection(sortDirection === 'asc' ? 'desc' : 'asc');
    } else {
      setSortField(field);
      setSortDirection('asc');
    }
  };

  if (!molecules || molecules.length === 0) {
    return (
      <div className="science-card py-10 text-center text-sm text-slate-500">
        <FlaskConical className="mx-auto mb-3 h-10 w-10 text-cyan-200" />
        <p className="font-medium text-slate-700">暂无候选分子</p>
        <p className="mt-1 text-xs">运行分子生成与评估流程后查看结果。</p>
      </div>
    );
  }

  if (!rankings || rankings.length === 0) {
    return (
      <div className="science-card py-10 text-center text-sm text-slate-500">
        <Trophy className="mx-auto mb-3 h-10 w-10 text-cyan-200" />
        <p className="font-medium text-slate-700">暂无 Top 候选</p>
        <p className="mt-1 text-xs">完成综合排序后，这里只展示你选择的 Top N 分子。</p>
      </div>
    );
  }

  return (
    <div className="space-y-4">
      <div className="rounded-lg border border-cyan-100 bg-cyan-50/50 p-3 text-xs leading-5 text-slate-600">
        当前只展示综合排序保留的 Top {rankings.length} 分子；全部生成与筛除情况请看“失败库”。
      </div>

      <div className="overflow-hidden rounded-lg border border-cyan-100 bg-white shadow-sm shadow-cyan-950/5">
        <div className="overflow-x-auto">
          <table className="w-full text-sm">
            <thead className="border-b border-cyan-100 bg-cyan-50/70">
              <tr>
                <th
                  onClick={() => toggleSort('rank')}
                  className="cursor-pointer px-4 py-3 text-left font-medium text-slate-700 hover:bg-cyan-100/60"
                >
                  <div className="flex items-center gap-2">
                    排名
                    <ArrowUpDown className="h-3 w-3" />
                  </div>
                </th>
                <th className="px-4 py-3 text-left font-medium text-slate-700">分子 ID</th>
                <th className="px-4 py-3 text-left font-medium text-slate-700">SMILES</th>
                <th
                  onClick={() => toggleSort('overall_score')}
                  className="cursor-pointer px-4 py-3 text-right font-medium text-slate-700 hover:bg-cyan-100/60"
                >
                  <div className="flex items-center justify-end gap-2">
                    总分
                    <ArrowUpDown className="h-3 w-3" />
                  </div>
                </th>
                <th className="px-4 py-3 text-left font-medium text-slate-700">状态</th>
                <th className="px-4 py-3 text-left font-medium text-slate-700">操作</th>
              </tr>
            </thead>
            <tbody>
              {displayMolecules.map(({ molecule, ranking }) => {
                const moleculeId = molecule?.molecule_id ?? ranking.molecule_id;
                return (
                  <tr key={moleculeId} className="border-b border-cyan-50 hover:bg-cyan-50/40">
                    <td className="px-4 py-3">
                      <span className="font-semibold text-slate-950">#{ranking.rank}</span>
                    </td>
                    <td className="px-4 py-3">
                      <code className="rounded bg-slate-100 px-2 py-1 text-xs text-slate-700">
                        {moleculeId}
                      </code>
                    </td>
                    <td className="px-4 py-3">
                      <code className="block max-w-md truncate text-xs text-slate-600">
                        {molecule?.smiles ?? '-'}
                      </code>
                    </td>
                    <td className="px-4 py-3 text-right">
                      {ranking.overall_score != null ? (
                        <span className="font-medium text-cyan-800">{formatNumber(ranking.overall_score)}</span>
                      ) : (
                        <span className="text-slate-400">-</span>
                      )}
                    </td>
                    <td className="px-4 py-3">
                      {molecule ? (
                        <span className={cn('rounded-full px-2.5 py-1 text-xs font-medium', getStatusColor(molecule.status))}>
                          {molecule.status}
                        </span>
                      ) : (
                        <span className="text-slate-400">-</span>
                      )}
                    </td>
                    <td className="px-4 py-3">
                      <Link
                        to={`/workspace/${projectId}/molecules/${moleculeId}`}
                        className="inline-flex items-center gap-1 text-cyan-700 hover:text-cyan-800"
                      >
                        查看详情
                        <ExternalLink className="h-3 w-3" />
                      </Link>
                    </td>
                  </tr>
                );
              })}
            </tbody>
          </table>
        </div>
      </div>

      <div className="text-center text-xs text-slate-500">
        显示 Top {displayMolecules.length} / 总候选 {molecules.length} 个分子
      </div>
    </div>
  );
}
