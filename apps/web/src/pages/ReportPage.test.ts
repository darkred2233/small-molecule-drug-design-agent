import { describe, expect, it } from 'vitest';
import {
  bestPoseConfirmed,
  evidenceExcerpt,
  formatBestPose,
  formatEvidenceCitation,
  formatEvidenceSourceLabel,
  decisionTone,
} from '@/utils/reportPresentation';

describe('report status tone mapping', () => {
  it('treats high-risk ADMET labels as risk, not success', () => {
    expect(decisionTone('high_risk')).toBe('rose');
    expect(decisionTone('hERG_high_risk')).toBe('rose');
    expect(decisionTone('low_risk')).toBe('emerald');
  });

  it('formats confirmed best pose with rank, count, score, and file name', () => {
    const docking = {
      diffdock_confidence: 1.25,
      pose_file: 'C:/runs/poses/MOL-1_rank1_confidence1.25.sdf',
      pose_artifact_available: true,
      selected_pose_rank: 1,
      pose_count: 10,
      pose_selection_method: 'diffdock_rank_1_by_confidence',
      best_pose_confirmed: true,
    };

    expect(bestPoseConfirmed(docking)).toBe(true);
    expect(formatBestPose(docking)).toContain('#1 / 10 poses');
    expect(formatBestPose(docking)).toContain('DiffDock 1.250');
    expect(formatBestPose(docking)).toContain('MOL-1_rank1_confidence1.25.sdf');
  });

  it('formats RAG literature evidence citation and excerpt', () => {
    const evidence = {
      evidence_id: 'EVD-1',
      chunk_id: 'CHK-1',
      document_title: 'EGFR uploaded evidence',
      filename: 'egfr_evidence.pdf',
      page_number: 7,
      section: 'Results',
      claim_type: 'candidate_support',
      evidence_confidence: null,
      evidence_confidence_semantics: 'not_calibrated',
      rationale: 'Computational support only.',
      content: 'The compound showed an EGFR-relevant computational signal.',
    };

    expect(formatEvidenceSourceLabel(evidence)).toBe('EGFR uploaded evidence');
    expect(formatEvidenceCitation(evidence)).toBe('egfr_evidence.pdf · p.7 · Results');
    expect(evidenceExcerpt(evidence)).toContain('EGFR-relevant computational signal');
  });
});
