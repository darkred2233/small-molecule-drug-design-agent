import type { BuiltinTarget, Project } from '@/types/api';

export type DesignGoalId =
  | 'lead_optimization'
  | 'hit_finding'
  | 'scaffold_hopping'
  | 'selectivity';

export type GenerationStrategyId =
  | 'reinvent4'
  | 'crem'
  | 'rdkit'
  | 'scaffold';

export type OptimizationPriorityId =
  | 'herg'
  | 'solubility'
  | 'logp'
  | 'selectivity'
  | 'scaffold'
  | 'synthesis'
  | 'admet'
  | 'novelty';

export interface PhyschemConstraints {
  mwMin: number;
  mwMax: number;
  logpMax: number;
  tpsaMin: number;
  tpsaMax: number;
  hbdMax: number;
  hbaMax: number;
  rotbMax: number;
  saScoreMax: number;
}

export interface SeedMolecule {
  name: string;
  smiles: string;
  note?: string;
}

interface DesignGoalOption {
  id: DesignGoalId;
  label: string;
  description: string;
  promptFocus: string;
}

interface GenerationStrategyOption {
  id: GenerationStrategyId;
  label: string;
  description: string;
  promptFocus: string;
}

interface OptimizationPriorityOption {
  id: OptimizationPriorityId;
  label: string;
  promptFocus: string;
}

export const DESIGN_GOALS: DesignGoalOption[] = [
  {
    id: 'lead_optimization',
    label: 'Lead 优化',
    description: '基于已有 hit/lead，平衡活性、ADMET、选择性与合成可行性。',
    promptFocus: '围绕已知先导结构做多轮结构修饰，优先给出 SAR 假设和可验证的下一轮设计。',
  },
  {
    id: 'hit_finding',
    label: 'Hit 发现',
    description: '从靶点信息出发寻找新颖起始结构，适合早期探索。',
    promptFocus: '扩展结构多样性，给出虚拟筛选、片段增长或生成模型的候选来源。',
  },
  {
    id: 'scaffold_hopping',
    label: '骨架跃迁',
    description: '保留关键药效团，替换核心骨架以改善性质或专利空间。',
    promptFocus: '保留关键相互作用与药效团距离，提出可合成的新骨架和替换理由。',
  },
  {
    id: 'selectivity',
    label: '选择性优化',
    description: '面向同源靶点或离靶风险，寻找选择性来源。',
    promptFocus: '识别选择性口袋和离靶风险，优先生成能解释选择性差异的结构改造。',
  },
];

export const GENERATION_STRATEGIES: GenerationStrategyOption[] = [
  {
    id: 'reinvent4',
    label: 'REINVENT4 多目标生成',
    description: '适合多目标打分、较大规模探索和下一轮优化。',
    promptFocus: '使用 REINVENT4 风格的多目标优化，综合活性、ADMET、合成和新颖性得分。',
  },
  {
    id: 'crem',
    label: 'CReM 局部替换',
    description: '适合围绕 seed 分子做片段替换和 SAR 微调。',
    promptFocus: '使用 CReM 风格的局部结构替换，控制相似度并保留关键母核。',
  },
  {
    id: 'rdkit',
    label: 'RDKit 规则枚举/粗筛',
    description: '适合快速、可解释的局部枚举和粗筛约束，不等同于外部生成模型。',
    promptFocus: '使用 RDKit 规则枚举和药化过滤，快速形成可解释的粗筛候选集合。',
  },
  {
    id: 'scaffold',
    label: '骨架跃迁生成',
    description: '适合保留药效团并尝试核心骨架替换。',
    promptFocus: '执行骨架跃迁生成，保留药效团约束并评估合成路线可行性。',
  },
];

export const OPTIMIZATION_PRIORITIES: OptimizationPriorityOption[] = [
  { id: 'herg', label: '降低 hERG 风险', promptFocus: '降低 hERG 与心脏毒性风险' },
  { id: 'solubility', label: '提高溶解度', promptFocus: '提高水溶性和可开发性' },
  { id: 'logp', label: '控制 cLogP', promptFocus: '控制 cLogP 与脂溶性，避免过度疏水' },
  { id: 'selectivity', label: '提高选择性', promptFocus: '提高目标靶点选择性并降低离靶风险' },
  { id: 'scaffold', label: '保留母核/药效团', promptFocus: '保留核心母核或关键药效团相互作用' },
  { id: 'synthesis', label: '降低合成难度', promptFocus: '降低 SA score、路线步数和危险反应风险' },
  { id: 'admet', label: '综合 ADMET', promptFocus: '平衡 Ames、DILI、CYP、渗透性和代谢稳定性' },
  { id: 'novelty', label: '提高新颖性', promptFocus: '提高结构新颖性和多样性，避免过度贴近已知药物' },
];

export const DEFAULT_PHYSCHEM_CONSTRAINTS: PhyschemConstraints = {
  mwMin: 200,
  mwMax: 500,
  logpMax: 4.5,
  tpsaMin: 40,
  tpsaMax: 120,
  hbdMax: 4,
  hbaMax: 10,
  rotbMax: 8,
  saScoreMax: 4.5,
};

export function getDefaultPriorityIdsForGoal(goalId: DesignGoalId): OptimizationPriorityId[] {
  if (goalId === 'hit_finding') return ['novelty', 'admet', 'synthesis'];
  if (goalId === 'scaffold_hopping') return ['scaffold', 'synthesis', 'logp'];
  if (goalId === 'selectivity') return ['selectivity', 'herg', 'admet'];
  return ['herg', 'solubility', 'logp', 'synthesis'];
}

export interface BuildDesignPromptInput {
  project: Project | null;
  target?: BuiltinTarget | null;
  goalId: DesignGoalId;
  strategyId: GenerationStrategyId;
  priorityIds: OptimizationPriorityId[];
  constraints: PhyschemConstraints;
  selectedSeeds: SeedMolecule[];
  customSeedSmiles?: string;
}

export function buildDesignPrompt({
  project,
  target,
  goalId,
  strategyId,
  priorityIds,
  constraints,
  selectedSeeds,
  customSeedSmiles,
}: BuildDesignPromptInput): string {
  const goal = DESIGN_GOALS.find((item) => item.id === goalId) ?? DESIGN_GOALS[0];
  const strategy =
    GENERATION_STRATEGIES.find((item) => item.id === strategyId) ?? GENERATION_STRATEGIES[0];
  const priorities = priorityIds
    .map((id) => OPTIMIZATION_PRIORITIES.find((item) => item.id === id)?.promptFocus)
    .filter(Boolean);

  const targetLabel = target
    ? `${target.name} (${target.target_id})`
    : project?.target_id
      ? project.target_id
      : '未设置靶点';
  const pdbLine = target?.pdb_ids?.length ? `可用 PDB：${target.pdb_ids.slice(0, 4).join(', ')}` : '';
  const projectObjective = project?.objective ? `项目原始目标：${project.objective}` : '';
  const customSeeds = customSeedSmiles
    ?.split(/\r?\n/)
    .map((line) => line.trim())
    .filter(Boolean) ?? [];
  const seedLines = [
    ...selectedSeeds.map((seed) => `- ${seed.name}: ${seed.smiles}${seed.note ? ` (${seed.note})` : ''}`),
    ...customSeeds.map((smiles) => `- 自定义 SMILES: ${smiles}`),
  ];

  return [
    `请作为小分子药物设计 Agent，为当前项目制定一轮「${goal.label}」方案。`,
    '',
    `靶点：${targetLabel}`,
    pdbLine,
    projectObjective,
    '',
    `设计目标：${goal.promptFocus}`,
    `生成策略：${strategy.promptFocus}`,
    `优化优先级：${priorities.length > 0 ? priorities.join('；') : '请根据项目目标自动判断'}`,
    '',
    '物化与可开发性约束：',
    `- MW: ${constraints.mwMin}-${constraints.mwMax}`,
    `- cLogP: <= ${constraints.logpMax}`,
    `- TPSA: ${constraints.tpsaMin}-${constraints.tpsaMax}`,
    `- HBD/HBA: <= ${constraints.hbdMax} / <= ${constraints.hbaMax}`,
    `- RotB: <= ${constraints.rotbMax}`,
    `- SA score: <= ${constraints.saScoreMax}`,
    seedLines.length > 0 ? '' : undefined,
    seedLines.length > 0 ? '种子/参考分子：' : undefined,
    ...seedLines,
    '',
    '请输出：',
    '1. 解析后的可执行约束清单。',
    '2. 推荐 pipeline：种子导入、分子生成、结构校验、ADMET、对接、逆合成、排序、自我反驳和报告。',
    '3. 每一步的输入、输出、失败风险和需要人工确认的选择。',
    '4. 用可解释推理摘要说明为什么这样设计，并列出证据链和不确定性。',
  ]
    .filter((line): line is string => line !== undefined)
    .join('\n');
}
