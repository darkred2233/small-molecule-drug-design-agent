/**
 * API Type Definitions
 *
 * These types match the backend API schemas
 */

// Project types
export interface Project {
  project_id: string;
  name: string;
  target_id: string | null;
  objective: string | null;
  status:
    | 'created'
    | 'pipeline_queued'
    | 'pipeline_running'
    | 'pipeline_completed'
    | 'pipeline_failed'
    | 'iterative_running'
    | 'iterative_completed';
  created_at: string;
  updated_at?: string;
}

export interface CreateProjectRequest {
  name: string;
  target_id?: string;
  target_name?: string;
  objective?: string;
  constraints?: Record<string, any>;
  seed_ligands?: SeedLigandInput[];
  generation_config?: GenerationConfig;
}

export interface SeedLigandInput {
  name?: string | null;
  smiles: string;
  source?: string | null;
  activity_value?: number | null;
  activity_unit?: string | null;
  activity_type?: string | null;
}

export interface GenerationConfig {
  strategy_counts: {
    reinvent4: number;
    crem: number;
    autogrow4: number;
  };
  generation_size: number;
  top_n: number;
  max_assessment_molecules: number;
  assessment_mode?: AssessmentMode;
  external_top_n?: number;
  generate_when_seeds_exist?: boolean;
}

// Target types
export interface BuiltinTarget {
  target_id: string;
  name: string;
  aliases: string[];
  uniprot_id: string | null;
  species: string | null;
  pdb_ids: string[];
  summary: string | null;
  pocket_summary: string | null;
  binding_sites: TargetBindingSite[];
  sar_rules: TargetSarRule[];
  admet_risks: TargetAdmetRisk[];
  seed_ligand_count: number;
  drugs: BuiltinDrug[];
}

export interface TargetBindingSite {
  binding_site_id: string;
  site_name?: string | null;
  pdb_id?: string | null;
  reference_ligand?: string | null;
  source_url?: string | null;
  grid_box?: GridBox | null;
  key_residues?: string[];
}

export interface GridBox {
  center?: number[] | null;
  size?: number[] | null;
  unit?: string | null;
  method?: string | null;
}

export interface TargetSarRule {
  rule_id?: string;
  title?: string;
  rationale?: string;
  preferred_change?: string;
  avoid?: string;
  evidence_level?: string;
}

export interface TargetAdmetRisk {
  risk_id?: string;
  category?: string;
  signal?: string;
  mitigation?: string;
  severity?: string;
}

export interface BuiltinDrug {
  drug_name: string;
  drug_status: string | null;
  mechanism: string | null;
  indication: string | null;
  smiles: string | null;
  canonical_smiles: string | null;
  isomeric_smiles: string | null;
  inchi_key: string | null;
  pubchem_cid: number | null;
  evidence_source: string | null;
}

// Chat types
export interface ChatMessage {
  message_id: string;
  role: 'user' | 'assistant';
  content: string;
  parsed_intent?: string;
  created_at: string;
}

export interface ChatRequest {
  message: string;
}

export type AgentName = 'reinvent4' | 'crem' | 'autogrow4';
export type AgentBudget = 'low' | 'medium' | 'high';
export type AgentEnabled = boolean | 'conditional';
export type RunPlanStatus = 'draft' | 'approved' | 'running' | 'completed' | 'failed';
export type ExplorationLevel = 'low' | 'medium' | 'high';
export type SynthesisRouteScope = 'disabled' | 'every_round_top_n' | 'final_round_top_n';

export interface RunPlanAgentConfig {
  enabled: AgentEnabled;
  role: string;
  budget: AgentBudget;
  requested_count: number;
  condition?: string | null;
}

export interface RunPlanEvaluation {
  mode: 'fast' | 'external_top_n' | 'full';
  top_n: number;
  use_docking: boolean;
  use_admet: boolean;
  use_synthesis: boolean;
  synthesis_route_scope: SynthesisRouteScope;
  use_filters: boolean;
}

export interface RunPlanStopping {
  min_score_improvement: number;
  max_total_molecules: number;
  max_tool_failures: number;
}

export interface RunPlan {
  status: RunPlanStatus;
  objective: string;
  auto_run: boolean;
  max_rounds: number;
  next_round_seed_count: number;
  seed_smiles: string[];
  exploration_level: ExplorationLevel;
  agents: Record<AgentName, RunPlanAgentConfig>;
  constraints: Record<string, any>;
  evaluation: RunPlanEvaluation;
  stopping: RunPlanStopping;
  decision_trace: Array<Record<string, any>>;
  evidence_chain: Array<Record<string, any>>;
  warnings: string[];
}

export interface RunPlanChange {
  path: string;
  old_value: any;
  new_value: any;
  affects_next_round: boolean;
}

export interface RunPlanPatch {
  reason: string;
  changes: RunPlanChange[];
  requires_confirmation: boolean;
  warnings: string[];
}

export interface ChatResponse {
  reply: string;
  intent: string;
  created_constraints: string[];
  run_plan?: RunPlan | null;
  plan_patch?: RunPlanPatch | null;
  plan_diff: RunPlanChange[];
  suggested_execution: boolean;
  requires_confirmation: boolean;
  warnings: string[];
}

// Constraint types
export interface OptimizationConstraint {
  constraint_id: string;
  label: string;
  field: string | null;
  operator: string | null;
  value: string | null;
  priority: number;
  is_active?: boolean;
}

// File types
export interface UploadedFile {
  file_id: string;
  filename: string;
  file_type: string;
  parse_status: 'uploaded' | 'parsing' | 'success' | 'partial_success' | 'failed';
  extracted_molecule_count?: number;
  extracted_chunk_count?: number;
  created_at?: string;
}

// RAG types
export interface RagDocument {
  document_id: string;
  project_id?: string | null;
  title: string;
  source: string | null;
  document_type: string;
  metadata: Record<string, any>;
}

export interface RagChunk {
  chunk_id: string;
  document_id: string;
  content: string;
  page?: number;
  section?: string;
}

export interface RagChunkRead {
  chunk_id: string;
  document_id: string;
  page_number?: number;
  section?: string;
  content: string;
  embedding_model?: string;
  embedding_ref?: string;
  token_count?: number;
  metadata?: Record<string, any>;
}

export interface EvidenceLink {
  evidence_id: string;
  molecule_id: string | null;
  chunk_id: string | null;
  claim_type: string;
  confidence: number | null;
  rationale: string | null;
  document_title?: string | null;
  source?: string | null;
  page_number?: number | null;
  section?: string | null;
  content?: string | null;
}

export interface RagQueryRequest {
  query: string;
  query_type?: string;
  top_k?: number;
  molecule_id?: string;
  create_evidence?: boolean;
}

export interface RagQueryResponse {
  agent_run_id: string;
  query: string;
  query_type: string;
  retrieved_chunks: RagRetrievedChunk[];
  evidence_ids: string[];
  confidence: number | null;
  confidence_semantics: string;
  retrieval_support_score: number;
  retrieval_support_score_semantics: string;
  embedding_model: string;
  rerank_model: string | null;
  retrieval_method: string;
  missing_information: string[];
  adapter_mode: string;
}

export interface RagRetrievedChunk {
  retrieval_rank: number;
  chunk_id: string;
  document_id: string;
  source_type: string;
  title: string;
  source: string | null;
  page: number | null;
  section: string | null;
  vector_score: number;
  keyword_score: number;
  combined_score: number;
  rerank_score: number | null;
  retrieval_method: string;
  score_semantics: string;
  embedding_model: string;
  rerank_model: string | null;
  evidence_id: string | null;
  evidence_confidence: number | null;
  evidence_confidence_semantics: string;
  evidence_summary: string;
  content: string;
}

// Molecule types
export interface Molecule {
  molecule_id: string;
  smiles: string;
  inchi_key?: string;
  scaffold: string | null;
  status: string;
  labels: string[];
  source_agent: string | null;
  properties?: MoleculeProperties;
  created_at?: string;
}

export interface MoleculeProperties {
  molecule_id: string;
  mw: number | null;
  logp: number | null;
  tpsa: number | null;
  hbd: number | null;
  hba: number | null;
  sa_score: number | null;
  tool_metadata: Record<string, any>;
}

// Assessment types
export type AssessmentMode = 'fast' | 'external' | 'full';

export interface CandidateAssessmentRunRequest {
  molecule_ids?: string[];
  max_molecules?: number;
  top_n?: number;
  assessment_mode?: AssessmentMode;
  external_top_n?: number;
  binding_site_id?: string;
  protein_file?: string;
  prepared_ligand_files?: Record<string, string>;
  grid_center?: number[];
  grid_size?: number[];
  key_residues?: string[];
  admet_properties?: string[];
  max_synthesis_steps?: number;
  prefer_buyable_building_blocks?: boolean;
}

export interface AssessmentStageSummary {
  agent_run_id: string;
  adapter_mode: string;
  requested_count: number;
  generated_count: number;
  evaluated_count: number;
  skipped_count: number;
  failed_count: number;
  molecule_ids: string[];
  skipped_molecule_ids: string[];
  failed_molecule_ids: string[];
  warnings: string[];
}

export interface CoarseScreenSummary {
  requested_count: number;
  passed_count: number;
  failed_count: number;
  passed_molecule_ids: string[];
  failed_molecule_ids: string[];
  failure_reasons_by_id: Record<string, string[]>;
}

export interface CandidateAssessmentRunResponse {
  project_id: string;
  assessment_mode: AssessmentMode;
  external_top_n: number;
  conformer: AssessmentStageSummary;
  docking: AssessmentStageSummary;
  admet: AssessmentStageSummary;
  synthesis: AssessmentStageSummary;
  ranking: AssessmentStageSummary;
  coarse_screen: CoarseScreenSummary;
  tool_status: Record<string, any>;
}

export interface DockingResult {
  molecule_id: string;
  vina_score?: number | null;
  docking_score?: number | null;
  cnn_score?: number | null;
  diffdock_confidence?: number | null;
  key_hbond_count?: number | null;
  clash_count?: number | null;
  pose_file?: string | null;
  labels?: string[];
  raw_output?: Record<string, any>;
  key_interactions?: string[];
}

export interface AdmetResult {
  hERG_risk?: string;
  Ames_risk?: string;
  CYP_inhibition?: Record<string, string>;
  DILI_risk?: string;
  solubility?: number;
  permeability?: number;
}

export interface SynthesisRoute {
  molecule_id: string;
  route_found: boolean;
  route_steps: number | null;
  route_confidence: number | null;
  buyable_building_blocks: number | null;
  labels: string[];
  route_json: SynthesisRouteDetails;
}

export interface SynthesisRouteStep {
  step: number;
  stage: string;
  input: string[];
  operation: string;
  output: string;
  rationale?: string;
}

export interface SynthesisRouteDetails {
  adapter_mode?: string | null;
  route_summary?: string | null;
  route_plan?: SynthesisRouteStep[];
  starting_materials?: string[];
  route_risks?: string[];
  route_note?: string | null;
  [key: string]: any;
}

// Ranking types
export interface Ranking {
  molecule_id: string;
  rank: number;
  overall_score: number | null;
  pro_score: number | null;
  con_score: number | null;
  evidence_confidence: number | null;
  final_decision: string;
  score_breakdown: Record<string, any>;
}

// Decision Card types
export interface DecisionCard {
  decision_id: string;
  project_id: string;
  molecule_id: string | null;
  trace_id: string | null;
  card_type: string;
  title: string;
  decision: string;
  summary: string;
  support: string[];
  risk: string[];
  next_steps: string[];
  evidence_ids: string[];
  confidence: number | null;
  provenance: Record<string, any>;
}

// Reasoning Trace types
export interface ReasoningTrace {
  trace_id: string;
  project_id: string;
  molecule_id: string | null;
  trace_type: string;
  claim: string;
  supporting_factors: string[];
  opposing_factors: string[];
  evidence_ids: string[];
  uncertainty: string | null;
  next_actions: string[];
  confidence: number | null;
  source_agent: string;
  provenance: Record<string, any>;
}

// Agent Run types
export interface AgentRun {
  agent_run_id: string;
  agent_name: string;
  model_name: string | null;
  status: string;
  iteration?: number | null;
  input_json?: Record<string, any>;
  output_json?: Record<string, any>;
  started_at?: string;
  ended_at?: string;
  error_message?: string;
}

// Advisor types
export interface AdvisorSuggestion {
  suggestion_id: string;
  summary: string;
  suggestions: Array<string | Record<string, any>>;
  next_round_constraints: Array<Record<string, any>>;
  suggested_generation_config: Record<string, any>;
}

// Report types
export interface ProjectReport {
  project_summary: {
    project_id: string;
    name: string;
    target_id: string | null;
    target_name?: string | null;
    objective: string | null;
    status: string;
  };
  target_and_pocket_analysis?: TargetAndPocketAnalysis;
  candidate_summary: {
    molecule_count: number;
    ranking_count: number;
    top_molecule_count: number;
    decision_card_count?: number;
    reasoning_trace_count?: number;
    seed_ligand_count?: number;
    binding_site_count?: number;
    rule_filter_count?: number;
    admet_result_count?: number;
    synthesis_route_count?: number;
  };
  sar_overview?: SarOverview;
  admet_overview?: AdmetOverview;
  synthesis_overview?: SynthesisOverview;
  top_candidates: ReportCandidate[];
  molecule_narratives?: MoleculeNarrative[];
  final_report?: FinalChineseReport;
  self_refutation?: {
    critique_count: number;
    risk_counts?: Record<string, number>;
    decision_counts?: Record<string, number>;
  };
  advisor_suggestions?: Record<string, any>;
  sections?: string[];
  report_file?: string;
}

export interface TargetAndPocketAnalysis {
  target: {
    target_id: string | null;
    name: string | null;
    aliases?: string[];
    uniprot_id?: string | null;
    species?: string | null;
    pdb_ids?: string[];
    summary?: string | null;
    pocket_summary?: string | null;
  };
  binding_sites: ReportBindingSite[];
  seed_ligands: ReportSeedLigand[];
  counts?: {
    binding_site_count: number;
    seed_ligand_count: number;
  };
}

export interface ReportBindingSite {
  binding_site_id: string;
  target_id?: string | null;
  project_id?: string | null;
  pdb_id?: string | null;
  site_name?: string | null;
  reference_ligand?: string | null;
  source_url?: string | null;
  preparation_status?: string;
  key_residues?: string[];
  grid_box?: GridBox | null;
  labels?: string[];
  warnings?: string[];
}

export interface ReportSeedLigand {
  ligand_id: string;
  name: string | null;
  smiles: string;
  activity_value?: number | null;
  activity_unit?: string | null;
  source?: string | null;
}

export interface SarOverview {
  target_sar_rules: TargetSarRule[];
  rule_filter_statistics?: {
    result_count: number;
    decision_counts?: Record<string, number>;
    failed_rule_counts?: Record<string, number>;
    warning_counts?: Record<string, number>;
  };
  molecule_rule_findings?: RuleFilterSummary[];
}

export interface RuleFilterSummary {
  filter_result_id: string;
  project_id?: string;
  molecule_id: string;
  rule_set: string;
  decision: string;
  failed_rules: string[];
  warnings: string[];
  labels: string[];
  properties_snapshot?: Record<string, any>;
  sar_notes?: Array<string | Record<string, any>>;
  raw_output?: Record<string, any>;
}

export interface AdmetOverview {
  target_admet_risks: TargetAdmetRisk[];
  result_count: number;
  risk_counts?: Record<string, Record<string, number>>;
  high_risk_molecules?: AdmetSummary[];
}

export interface AdmetSummary {
  molecule_id: string;
  hERG?: {
    probability?: number | null;
    risk?: string | null;
  };
  Ames?: {
    probability?: number | null;
    risk?: string | null;
  };
  solubility?: string | null;
  permeability?: string | null;
  admet_risk_score?: number | null;
  CYP3A4?: unknown;
  CYP2D6?: unknown;
  DILI?: unknown;
  Pgp?: unknown;
  BBB?: unknown;
  labels?: string[];
  adapter_mode?: string | null;
  tool_name?: string | null;
  tool_version?: string | null;
  model_name?: string | null;
  model_count?: number | null;
  compute_device?: string | null;
  result_kind?: string | null;
}

export interface SynthesisOverview {
  result_count: number;
  route_found_count: number;
  route_missing_count: number;
  average_route_steps?: number | null;
  average_route_confidence?: number | null;
  label_counts?: Record<string, number>;
  routes: SynthesisSummary[];
}

export interface SynthesisSummary {
  molecule_id: string;
  route_found: boolean;
  route_steps?: number | null;
  route_confidence?: number | null;
  buyable_building_blocks?: number | null;
  SA_score?: number | null;
  SCScore?: number | null;
  estimated_route_feasible?: boolean | null;
  estimated_route_steps?: number | null;
  estimated_route_confidence?: number | null;
  estimated_buyable_building_blocks?: number | null;
  hazardous_reaction_count?: number | null;
  protecting_group_count?: number | null;
  route_summary?: string | null;
  route_plan?: SynthesisRouteStep[];
  starting_materials?: string[];
  route_risks?: string[];
  route_note?: string | null;
  adapter_mode?: string | null;
  result_kind?: string | null;
  route_metadata?: Record<string, any> | null;
  has_reaction_tree?: boolean;
  labels?: string[];
}

export interface PoseAtomCoordinate {
  index: number;
  element: string;
  x: number;
  y: number;
  z: number;
}

export interface PoseCoordinates {
  format: string;
  atom_count: number;
  returned_atom_count: number;
  truncated: boolean;
  atoms: PoseAtomCoordinate[];
}

export interface DockingSummary {
  vina_score?: number | null;
  cnn_score?: number | null;
  diffdock_confidence?: number | null;
  key_hbond_count?: number | null;
  clash_count?: number | null;
  pose_file?: string | null;
  pose_artifact_available?: boolean;
  pose_coordinates?: PoseCoordinates | null;
  selected_pose_rank?: number | null;
  pose_count?: number | null;
  pose_selection_method?: string | null;
  best_pose_confirmed?: boolean;
  labels?: string[];
  raw_output?: Record<string, any>;
}

export interface ReportCandidate {
  rank: number;
  molecule_id: string;
  smiles: string | null;
  generation_source_agent?: string | null;
  generation_method?: string | null;
  overall_score: number | null;
  pro_score?: number | null;
  con_score?: number | null;
  evidence_confidence?: number | null;
  ranking_score_semantics?: string;
  evidence_confidence_semantics?: string;
  final_decision: string;
  risk_level?: string | null;
  refutation_decision?: string | null;
  rule_filter?: RuleFilterSummary[];
  docking?: DockingSummary | null;
  admet?: AdmetSummary | null;
  synthesis?: SynthesisSummary | null;
  evidence_chain?: ReportEvidenceLink[];
  refutation_chain?: Record<string, any> | null;
  narrative?: MoleculeNarrative;
}

export interface MoleculeNarrative {
  molecule_id: string;
  rank?: number | null;
  summary: string;
  why_it_matters?: string;
  structure_change?: string;
  strengths: string[];
  risks: string[];
  next_round_suggestions: string[];
  evidence_refs: NarrativeEvidenceRef[];
  provenance?: Record<string, any>;
}

export interface NarrativeEvidenceRef {
  type: string;
  source?: string | null;
  molecule_id?: string | null;
  summary?: string | null;
  artifact_path?: string | null;
  score?: number | string | null;
  metadata?: Record<string, any>;
}

export interface FinalChineseReport {
  title: string;
  language?: string;
  generation_mode?: string;
  schema_version?: string;
  generated_at?: string;
  project_objective?: string | null;
  executive_summary: string[];
  run_plan_summary?: Record<string, any>;
  round_summaries?: Array<Record<string, any>>;
  top_molecules?: Array<Record<string, any>>;
  sar_summary?: Record<string, any>;
  docking_summary?: Record<string, any>;
  admet_summary?: Record<string, any>;
  synthesis_summary?: Record<string, any>;
  rag_evidence_summary?: Record<string, any>;
  failures_and_uncertainties?: string[];
  next_steps?: string[];
  citations?: Array<Record<string, any>>;
  provenance?: Record<string, any>;
}

export interface ReportEvidenceLink {
  evidence_id: string;
  chunk_id: string | null;
  document_id?: string | null;
  document_title?: string | null;
  document_source?: string | null;
  document_type?: string | null;
  filename?: string | null;
  page_number?: number | null;
  section?: string | null;
  chunk_index?: number | null;
  claim_type: string;
  evidence_confidence: number | null;
  evidence_confidence_semantics: string;
  rationale: string | null;
  content?: string | null;
}

// Pipeline Status
export interface PipelineStatus {
  project_id: string;
  status: string;
  current_step?: string;
  agent_runs: AgentRun[];
}

// Tool Status
export interface ToolStatus {
  tool_name: string;
  status: 'available' | 'unavailable' | 'unknown';
  version?: string;
  last_check?: string;
}
