export interface Project {
  project_id: string;
  name: string;
  target_id: string | null;
  target_name?: string | null;
  objective: string | null;
  status: string;
  created_at: string;
  updated_at?: string | null;
}

export interface BuiltinTarget {
  target_id: string;
  name: string;
  aliases: string[];
  uniprot_id: string | null;
  species: string | null;
  pdb_ids: string[];
  summary: string | null;
  pocket_summary: string | null;
  seed_ligand_count: number;
}

export interface SeedLigandInput {
  name?: string;
  smiles: string;
  source?: string;
  activity_value?: number;
  activity_unit?: string;
  activity_type?: string;
}

export interface CreateProjectInput {
  name: string;
  target_id?: string;
  target_name?: string;
  objective?: string;
  constraints?: Record<string, unknown>;
  seed_ligands?: SeedLigandInput[];
}

export interface ProjectRound {
  round_id: string;
  project_id: string;
  round_number: number;
  status: string;
  parent_round_id: string | null;
  user_conditions_json: Record<string, unknown> | null;
  execution_config_snapshot_json: Record<string, unknown> | null;
  started_at: string | null;
  completed_at: string | null;
  created_at: string;
}

export interface SeedPolicy {
  source: 'all_seeds' | 'top_from_previous' | 'mixed' | string;
  top_n: number | null;
  molecule_ids: string[];
  description: string | null;
}

export interface PropertyConstraints {
  mw_range: number[] | null;
  logp_range: number[] | null;
  tpsa_range: number[] | null;
  hbd_range: number[] | null;
  hba_range: number[] | null;
}

export interface AssessmentConfig {
  mode: string;
  top_n: number | null;
  skip_docking: boolean;
  skip_admet: boolean;
  skip_synthesis: boolean;
}

export interface StrategyDraft {
  round_id: string;
  round_number: number;
  objective: string;
  campaign_config: Record<string, CampaignConfig>;
  seed_policy: SeedPolicy | null;
  property_constraints: PropertyConstraints | null;
  assessment_config: AssessmentConfig | null;
  rationale: string;
  warnings: string[];
  requires_user_confirmation: boolean;
  created_at: string;
}

export interface CampaignConfig {
  enabled?: boolean;
  num_molecules?: number;
  sample_count?: number;
  mode?: string;
  edit_depth?: number;
  generations?: number;
  search_intensity?: string;
  [key: string]: unknown;
}

export interface CampaignRun {
  campaign_run_id: string;
  round_id: string;
  project_id: string;
  method: string;
  status: string;
  config_json: Record<string, unknown> | null;
  resource_bundle_json: Record<string, unknown> | null;
  input_molecule_ids: string[];
  output_molecule_ids: string[];
  metrics_json: Record<string, unknown> | null;
  warnings_json: string[];
  started_at: string | null;
  completed_at: string | null;
  created_at: string;
}

export interface Molecule {
  molecule_id: string;
  smiles: string;
  inchi_key?: string | null;
  scaffold: string | null;
  status: string;
  labels: string[];
  source_agent: string | null;
  round_id?: string | null;
  campaign_run_id?: string | null;
  generation_method?: string | null;
  parent_molecule_ids?: string[];
  provenance_json?: Record<string, unknown>;
  generation_metadata_json?: Record<string, unknown>;
}

export interface MoleculeProperties {
  molecule_id: string;
  mw: number | null;
  logp: number | null;
  tpsa: number | null;
  hbd: number | null;
  hba: number | null;
  sa_score: number | null;
  tool_metadata: Record<string, unknown>;
}

export interface Ranking {
  molecule_id: string;
  rank: number;
  overall_score: number | null;
  pro_score: number | null;
  con_score: number | null;
  evidence_confidence: number | null;
  final_decision: string;
  score_breakdown: Record<string, unknown>;
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
  pose_artifact_available?: boolean;
  pose_coordinates?: PoseCoordinates | null;
  selected_pose_rank?: number | null;
  pose_count?: number | null;
  pose_selection_method?: string | null;
  best_pose_confirmed?: boolean;
  labels?: string[];
  raw_output?: Record<string, unknown>;
  key_interactions?: string[];
}

export interface PoseCoordinates {
  format: string;
  atom_count: number;
  returned_atom_count: number;
  truncated: boolean;
  atoms: Array<{ index: number; element: string; x: number; y: number; z: number }>;
}

export interface AdmetResult {
  molecule_id: string;
  hERG_risk?: string | null;
  Ames_risk?: string | null;
  DILI_risk?: string | null;
  solubility?: number | null;
  permeability?: number | null;
  [key: string]: unknown;
}

export interface SynthesisRoute {
  molecule_id: string;
  route_found: boolean;
  route_steps: number | null;
  route_confidence: number | null;
  buyable_building_blocks: number | null;
  labels: string[];
  route_json: Record<string, unknown>;
}

export interface RoundSummary {
  round_id: string;
  round_number: number;
  status: string;
  started_at: string | null;
  completed_at: string | null;
  molecule_count: number;
  docking_count: number;
  admet_count: number;
  synthesis_count: number;
  ranking_count: number;
  execution_progress: {
    agent_run_id: string;
    agent_name: string;
    status: string;
    stage: string;
    message: string;
    total_molecules: number | null;
    completed_molecules: number | null;
    percent: number | null;
  } | null;
  top_molecules: Array<{ molecule_id: string; rank: number; overall_score: number | null; final_decision: string }>;
  campaigns: Array<{ campaign_run_id: string; method: string; status: string; output_count: number }>;
}

export interface UploadedFile {
  file_id: string;
  filename: string;
  file_type: string;
  parse_status: string;
  extracted_molecule_count?: number | null;
  extracted_chunk_count?: number | null;
  created_at?: string | null;
}

export interface ProjectResource {
  resource_id: string;
  project_id: string | null;
  target_id: string | null;
  resource_type: string;
  scope: string;
  name: string;
  file_path: string | null;
  metadata_json: Record<string, unknown> | null;
  confidence_level: string | null;
  source_url: string | null;
}

export interface TargetLigand {
  target_ligand_id: string;
  target_id: string;
  name: string | null;
  smiles: string;
  canonical_smiles?: string | null;
  inchi_key?: string | null;
  activity_value?: number | null;
  activity_unit?: string | null;
  activity_type?: string | null;
  pchembl_value?: number | null;
  assay_type?: string | null;
  source: string;
  source_id?: string | null;
  confidence_level: string;
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

export interface RagDocument {
  document_id: string;
  project_id?: string | null;
  title: string;
  source: string | null;
  document_type: string;
  metadata: Record<string, unknown>;
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
}

export interface ReportCandidate {
  rank: number;
  molecule_id: string;
  smiles: string | null;
  generation_source_agent?: string | null;
  generation_method?: string | null;
  overall_score: number | null;
  final_decision: string;
  docking?: DockingResult | null;
  evidence_chain?: EvidenceLink[];
  narrative?: MoleculeNarrative;
}

export interface ProjectReport {
  project_summary: { project_id: string; name: string; target_id: string | null; target_name?: string | null; objective: string | null; status: string };
  candidate_summary: { molecule_count: number; ranking_count: number; top_molecule_count: number };
  top_candidates: ReportCandidate[];
  final_report?: {
    title: string;
    language?: string;
    executive_summary: string[];
    failures_and_uncertainties?: string[];
    next_steps?: string[];
    citations?: Array<Record<string, unknown>>;
  };
}

export interface ToolStatus { tool_name: string; status: 'available' | 'unavailable' | 'unknown'; version?: string; last_check?: string; }
