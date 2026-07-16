import type { DockingSummary, ReportEvidenceLink } from '@/types/api';
import { formatNumber } from '@/utils/helpers';

export function decisionTone(value: string) {
  const normalized = value.toLowerCase();
  if (normalized.includes('reject') || normalized.includes('fail') || normalized.includes('high_risk')) {
    return 'rose';
  }
  if (normalized.includes('warn') || normalized.includes('medium') || normalized.includes('reserve')) {
    return 'amber';
  }
  if (normalized.includes('recommend') || normalized.includes('pass') || normalized.includes('found') || normalized.includes('low_risk')) {
    return 'emerald';
  }
  if (normalized.includes('risk')) {
    return 'rose';
  }
  return 'cyan';
}

export function bestPoseConfirmed(docking?: DockingSummary | null) {
  if (!docking) return false;
  return Boolean(
    docking.pose_artifact_available !== false &&
      (docking.best_pose_confirmed ??
        (docking.selected_pose_rank === 1 &&
          Boolean(docking.pose_selection_method) &&
          !docking.pose_selection_method?.includes('not_confirmed')))
  );
}

export function formatBestPose(docking?: DockingSummary | null) {
  if (!docking) return '未评估';

  const score =
    docking.cnn_score != null
      ? `GNINA CNN ${formatNumber(docking.cnn_score, 3)}`
      : docking.diffdock_confidence != null
        ? `DiffDock ${formatNumber(docking.diffdock_confidence, 3)}`
        : docking.vina_score != null
          ? `Vina ${formatNumber(docking.vina_score, 2)}`
          : '分数未记录';
  const poseCount = docking.pose_count ? ` / ${docking.pose_count} poses` : '';
  const filename = poseFilename(docking.pose_file);

  if (!bestPoseConfirmed(docking)) {
    const availableRank =
      docking.selected_pose_rank == null ? '' : `；现有 #${docking.selected_pose_rank}${poseCount} · ${score}`;
    return `最佳 Pose 未确认${availableRank}`;
  }

  return [`#${docking.selected_pose_rank}${poseCount} · ${score}`, filename].filter(Boolean).join(' · ');
}

export function poseFilename(path?: string | null) {
  if (!path) return '';
  return path.split(/[\\/]/).filter(Boolean).pop() ?? path;
}

export function formatEvidenceSourceLabel(evidence: ReportEvidenceLink) {
  return evidence.document_title ?? evidence.filename ?? evidence.document_source ?? evidence.evidence_id;
}

export function formatEvidenceCitation(evidence: ReportEvidenceLink) {
  const source = evidence.filename ?? evidence.document_source ?? evidence.document_id ?? evidence.evidence_id;
  const parts = [source];
  if (evidence.page_number != null) {
    parts.push(`p.${evidence.page_number}`);
  }
  if (evidence.section) {
    parts.push(evidence.section);
  }
  return parts.filter(Boolean).join(' · ');
}

export function evidenceExcerpt(evidence: ReportEvidenceLink, maxLength = 320) {
  const text = (evidence.content ?? evidence.rationale ?? '').replace(/\s+/g, ' ').trim();
  if (!text) return '暂无证据片段';
  if (text.length <= maxLength) return text;
  return `${text.slice(0, Math.max(maxLength - 3, 0)).trim()}...`;
}
