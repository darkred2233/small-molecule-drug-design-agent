import { AlertTriangle, CheckCircle2, ChevronDown, Database } from 'lucide-react';

type JsonRecord = Record<string, unknown>;
type Primitive = string | number | boolean | null;
type PoseAtomCoordinate = {
  index: number;
  element: string;
  x: number;
  y: number;
  z: number;
};
type PoseCoordinates = {
  format?: string;
  atom_count?: number;
  returned_atom_count?: number;
  truncated?: boolean;
  atoms: PoseAtomCoordinate[];
};

const TABLE_LABELS: Record<string, string> = {
  molecules: '分子记录',
  molecule_properties: '理化性质',
  rule_filter_results: '规则过滤',
  conformer_results: '构象分析',
  docking_results: '分子对接',
  admet_results: 'ADMET 预测',
  synthesis_routes: '合成路线',
  rankings: '综合排序',
};

const FIELD_LABELS: Record<string, string> = {
  molecule_id: '分子 ID',
  smiles: 'SMILES',
  status: '状态',
  source_agent: '来源 Agent',
  scaffold: '骨架',
  mw: '分子量',
  logp: 'LogP',
  tpsa: 'TPSA',
  hbd: '氢键供体',
  hba: '氢键受体',
  sa_score: 'SA Score',
  rule_set: '规则集',
  decision: '结论',
  conformer_generated: '已生成构象',
  conformer_count: '构象数量',
  lowest_energy: '最低能量',
  strain_energy: '应变能',
  rmsd_between_conformers: '构象间 RMSD',
  vina_score: 'Vina Score',
  cnn_score: 'GNINA CNN Score',
  diffdock_confidence: 'DiffDock Confidence',
  key_hbond_count: '关键氢键数',
  clash_count: '碰撞数',
  pose_file: '姿态文件',
  pose_artifact_available: 'Pose 文件可用',
  selected_pose_rank: '采用 Pose 排名',
  pose_count: '生成 Pose 数量',
  pose_selection_method: 'Pose 选择规则',
  hERG_probability: 'hERG 概率',
  hERG_risk: 'hERG 风险',
  Ames_probability: 'Ames 概率',
  Ames_risk: 'Ames 风险',
  solubility: '溶解度',
  permeability: '渗透性',
  admet_risk_score: 'ADMET 风险分',
  route_found: '找到路线',
  route_steps: '路线步数',
  route_confidence: '路线评分',
  buyable_building_blocks: '可购买砌块',
  rank: '排名',
  pro_score: '正向得分',
  con_score: '风险得分',
  evidence_confidence: '证据完整度',
  overall_score: '综合得分',
  final_decision: '最终结论',
  tool_name: '分析工具',
  adapter_mode: '运行方式',
  route_score: '路线得分',
  runtime_seconds: '运行耗时（秒）',
  route_note: '路线说明',
  failed_rules: '未通过规则',
  warnings: '提示与警告',
  starting_materials: '起始原料',
  route_risks: '路线风险',
  external_warnings: '外部工具提示',
};

const ROUTE_DETAIL_KEYS = [
  'tool_name',
  'adapter_mode',
  'route_score',
  'runtime_seconds',
  'route_note',
];

function asRecord(value: unknown): JsonRecord | null {
  return value !== null && typeof value === 'object' && !Array.isArray(value)
    ? (value as JsonRecord)
    : null;
}

function asString(value: unknown): string | null {
  return typeof value === 'string' && value.trim() ? value : null;
}

function asPrimitiveArray(value: unknown): Primitive[] {
  if (!Array.isArray(value)) return [];
  return value.filter(
    (item): item is Primitive =>
      item === null || ['string', 'number', 'boolean'].includes(typeof item)
  );
}

function asRecordArray(value: unknown): JsonRecord[] {
  if (!Array.isArray(value)) return [];
  return value.map(asRecord).filter((item): item is JsonRecord => item !== null);
}

function isPrimitive(value: unknown): value is Primitive {
  return value === null || ['string', 'number', 'boolean'].includes(typeof value);
}

function asPoseCoordinates(value: unknown): PoseCoordinates | null {
  const record = asRecord(value);
  const atomsValue = record?.atoms;
  if (!record || !Array.isArray(atomsValue)) return null;

  const atoms = atomsValue.flatMap((item): PoseAtomCoordinate[] => {
    const atom = asRecord(item);
    if (
      !atom ||
      typeof atom.index !== 'number' ||
      typeof atom.element !== 'string' ||
      typeof atom.x !== 'number' ||
      typeof atom.y !== 'number' ||
      typeof atom.z !== 'number'
    ) {
      return [];
    }
    return [
      {
        index: atom.index,
        element: atom.element,
        x: atom.x,
        y: atom.y,
        z: atom.z,
      },
    ];
  });

  if (atoms.length === 0) return null;
  return {
    format: asString(record.format) ?? undefined,
    atom_count: typeof record.atom_count === 'number' ? record.atom_count : undefined,
    returned_atom_count:
      typeof record.returned_atom_count === 'number' ? record.returned_atom_count : undefined,
    truncated: typeof record.truncated === 'boolean' ? record.truncated : undefined,
    atoms,
  };
}

function fieldLabel(key: string) {
  return FIELD_LABELS[key] ?? key.replace(/_/g, ' ');
}

function formatValue(value: Primitive): string {
  if (value === null || value === '') return '-';
  if (typeof value === 'boolean') return value ? '是' : '否';
  if (typeof value === 'number') {
    return Number.isInteger(value)
      ? value.toLocaleString()
      : value.toLocaleString(undefined, { maximumFractionDigits: 3 });
  }
  return value;
}

function parseEvidencePayload(content: string | null): JsonRecord | null {
  if (!content) return null;
  try {
    return asRecord(JSON.parse(content));
  } catch {
    return null;
  }
}

export default function EvidenceContent({ content }: { content: string | null }) {
  const payload = parseEvidencePayload(content);

  if (!content) {
    return <p className="text-sm text-slate-500">暂无可显示的证据内容。</p>;
  }

  if (!payload) {
    return <div className="whitespace-pre-wrap break-words text-sm leading-7 text-slate-700">{content}</div>;
  }

  return <StructuredEvidence payload={payload} />;
}

function StructuredEvidence({ payload }: { payload: JsonRecord }) {
  const table = asString(payload.table);
  const routeJson = asRecord(payload.route_json);
  const poseCoordinates = asPoseCoordinates(payload.pose_coordinates);
  const labels = asPrimitiveArray(payload.labels).map(String);
  const summary = asString(routeJson?.route_summary) ?? asString(payload.summary);
  const scalarEntries = Object.entries(payload).filter(
    ([key, value]) => !['table', 'molecule_id', 'labels', 'route_json'].includes(key) && isPrimitive(value)
  ) as Array<[string, Primitive]>;
  const arrayEntries = Object.entries(payload).filter(
    ([key, value]) => key !== 'labels' && asPrimitiveArray(value).length > 0
  );
  const title = table ? TABLE_LABELS[table] ?? fieldLabel(table) : '结构化证据';

  return (
    <div className="space-y-5">
      <div className="flex items-start gap-3">
        <div className="mt-0.5 rounded-md bg-cyan-50 p-2 text-cyan-700">
          <Database className="h-4 w-4" />
        </div>
        <div className="min-w-0">
          <div className="text-sm font-semibold text-slate-950">{title}</div>
          {table && <div className="mt-0.5 text-xs text-slate-500">来源：数据库分析记录</div>}
        </div>
      </div>

      {summary && (
        <div className="border-l-2 border-cyan-500 pl-3 text-sm leading-6 text-slate-700">
          {summary}
        </div>
      )}

      {scalarEntries.length > 0 && <MetricGrid entries={scalarEntries} />}

      {arrayEntries.map(([key, value]) => (
        <PrimitiveList key={key} label={fieldLabel(key)} values={asPrimitiveArray(value)} />
      ))}

      {poseCoordinates && <PoseCoordinateTable coordinates={poseCoordinates} />}

      {routeJson && <RouteDetails route={routeJson} />}

      {labels.length > 0 && (
        <section className="border-t border-cyan-100 pt-4">
          <h4 className="text-xs font-semibold uppercase text-slate-500">分析标签</h4>
          <div className="mt-2 flex flex-wrap gap-1.5">
            {labels.map((label) => (
              <span key={label} className="rounded-md bg-slate-100 px-2 py-1 text-[11px] text-slate-600">
                {label}
              </span>
            ))}
          </div>
        </section>
      )}

      <details className="group border-t border-cyan-100 pt-4">
        <summary className="flex cursor-pointer list-none items-center justify-between text-xs font-semibold text-slate-600">
          <span>原始数据</span>
          <ChevronDown className="h-4 w-4 transition-transform group-open:rotate-180" />
        </summary>
        <pre className="mt-3 max-h-80 overflow-auto whitespace-pre-wrap break-words rounded-md bg-slate-950 p-3 text-[11px] leading-5 text-slate-100">
          {JSON.stringify(payload, null, 2)}
        </pre>
      </details>
    </div>
  );
}

function PoseCoordinateTable({ coordinates }: { coordinates: PoseCoordinates }) {
  return (
    <section className="border-t border-cyan-100 pt-4">
      <div className="mb-3 flex items-center justify-between gap-3">
        <div>
          <h4 className="text-xs font-semibold uppercase text-slate-500">最佳 Pose XYZ 坐标</h4>
          <div className="mt-1 text-xs text-slate-500">
            {(coordinates.format ?? 'pose').toUpperCase()} · {coordinates.atom_count ?? coordinates.atoms.length} atoms
          </div>
        </div>
        {coordinates.truncated && (
          <div className="text-right text-xs text-amber-700">
            仅显示前 {coordinates.returned_atom_count ?? coordinates.atoms.length} / {coordinates.atom_count} 个原子
          </div>
        )}
      </div>
      <div className="max-h-80 overflow-auto rounded-md border border-cyan-100">
        <table className="w-full min-w-[360px] text-left text-xs">
          <thead className="sticky top-0 bg-slate-50 text-slate-500">
            <tr>
              <th className="px-3 py-2 font-medium">#</th>
              <th className="px-3 py-2 font-medium">Atom</th>
              <th className="px-3 py-2 text-right font-medium">X</th>
              <th className="px-3 py-2 text-right font-medium">Y</th>
              <th className="px-3 py-2 text-right font-medium">Z</th>
            </tr>
          </thead>
          <tbody className="divide-y divide-slate-100 font-mono text-slate-700">
            {coordinates.atoms.map((atom) => (
              <tr key={atom.index}>
                <td className="px-3 py-1.5">{atom.index}</td>
                <td className="px-3 py-1.5">{atom.element}</td>
                <td className="px-3 py-1.5 text-right">
                  {atom.x.toLocaleString(undefined, { maximumFractionDigits: 4 })}
                </td>
                <td className="px-3 py-1.5 text-right">
                  {atom.y.toLocaleString(undefined, { maximumFractionDigits: 4 })}
                </td>
                <td className="px-3 py-1.5 text-right">
                  {atom.z.toLocaleString(undefined, { maximumFractionDigits: 4 })}
                </td>
              </tr>
            ))}
          </tbody>
        </table>
      </div>
    </section>
  );
}

function MetricGrid({ entries }: { entries: Array<[string, Primitive]> }) {
  return (
    <dl className="grid grid-cols-2 gap-x-5 gap-y-4 border-y border-cyan-100 py-4">
      {entries.map(([key, value]) => {
        const formatted = formatValue(value);
        const isLong = formatted.length > 28;
        return (
          <div key={key} className={isLong ? 'col-span-2' : undefined}>
            <dt className="text-xs text-slate-500">{fieldLabel(key)}</dt>
            <dd className="mt-1 break-words text-sm font-medium leading-6 text-slate-900">{formatted}</dd>
          </div>
        );
      })}
    </dl>
  );
}

function PrimitiveList({ label, values }: { label: string; values: Primitive[] }) {
  const warningLike = /风险|警告|未通过/.test(label);
  return (
    <section className="border-t border-cyan-100 pt-4">
      <h4 className="text-xs font-semibold uppercase text-slate-500">{label}</h4>
      <div className="mt-2 space-y-2">
        {values.map((value, index) => (
          <div key={`${String(value)}-${index}`} className="flex items-start gap-2 text-sm leading-6 text-slate-700">
            {warningLike ? (
              <AlertTriangle className="mt-1 h-3.5 w-3.5 flex-none text-amber-600" />
            ) : (
              <CheckCircle2 className="mt-1 h-3.5 w-3.5 flex-none text-emerald-600" />
            )}
            <span>{formatValue(value)}</span>
          </div>
        ))}
      </div>
    </section>
  );
}

function RouteDetails({ route }: { route: JsonRecord }) {
  const metrics = ROUTE_DETAIL_KEYS.flatMap((key) =>
    isPrimitive(route[key]) ? ([[key, route[key]]] as Array<[string, Primitive]>) : []
  );
  const materials = asPrimitiveArray(route.starting_materials).map(String);
  const risks = asPrimitiveArray(route.route_risks).map(String);
  const warnings = asPrimitiveArray(route.external_warnings).map(String);
  const plan = asRecordArray(route.route_plan);

  return (
    <div className="space-y-5">
      {metrics.length > 0 && (
        <section>
          <h4 className="mb-3 text-xs font-semibold uppercase text-slate-500">路线参数</h4>
          <MetricGrid entries={metrics} />
        </section>
      )}

      {materials.length > 0 && (
        <section className="border-t border-cyan-100 pt-4">
          <h4 className="text-xs font-semibold uppercase text-slate-500">起始原料</h4>
          <div className="mt-2 flex flex-wrap gap-1.5">
            {materials.map((material) => (
              <span key={material} className="rounded-md border border-cyan-100 bg-cyan-50 px-2 py-1 text-xs text-cyan-900">
                {material}
              </span>
            ))}
          </div>
        </section>
      )}

      {plan.length > 0 && (
        <section className="border-t border-cyan-100 pt-4">
          <h4 className="text-xs font-semibold uppercase text-slate-500">合成步骤</h4>
          <ol className="mt-3 space-y-4">
            {plan.map((step, index) => {
              const stepNumber = isPrimitive(step.step) ? formatValue(step.step) : String(index + 1);
              const stage = asString(step.stage) ?? `步骤 ${index + 1}`;
              const operation = asString(step.operation);
              const output = asString(step.output);
              return (
                <li key={`${stepNumber}-${stage}`} className="flex gap-3">
                  <div className="flex h-6 w-6 flex-none items-center justify-center rounded-full bg-cyan-700 text-xs font-semibold text-white">
                    {stepNumber}
                  </div>
                  <div className="min-w-0 border-b border-slate-100 pb-4 last:border-b-0">
                    <div className="text-sm font-semibold text-slate-900">{stage}</div>
                    {operation && <p className="mt-1 text-sm leading-6 text-slate-700">{operation}</p>}
                    {output && <p className="mt-1 text-xs leading-5 text-slate-500">产物：{output}</p>}
                  </div>
                </li>
              );
            })}
          </ol>
        </section>
      )}

      {(risks.length > 0 || warnings.length > 0) && (
        <section className="border-t border-cyan-100 pt-4">
          <h4 className="text-xs font-semibold uppercase text-slate-500">风险与提示</h4>
          <div className="mt-2 space-y-2">
            {[...risks, ...warnings].map((item) => {
              const isClear = /^no major\b/i.test(item);
              return (
                <div key={item} className={`flex items-start gap-2 text-sm leading-6 ${isClear ? 'text-emerald-700' : 'text-amber-800'}`}>
                  {isClear ? (
                    <CheckCircle2 className="mt-1 h-4 w-4 flex-none" />
                  ) : (
                    <AlertTriangle className="mt-1 h-4 w-4 flex-none" />
                  )}
                  <span>{item}</span>
                </div>
              );
            })}
          </div>
        </section>
      )}
    </div>
  );
}
