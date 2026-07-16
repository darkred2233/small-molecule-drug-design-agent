"""
Self-Refutation Agent (DEPRECATED)

⚠️ 此文件已废弃！请使用 services/self_refutation.py

原因：
- 架构冲突：此 Agent 版本与 services 版本并行存在，导致数据不一致
- LLM 质询功能在 services 版本中，存入 Critique 表
- RankerAgent 已改为直接读取 Critique 表

迁移指南：
1. 使用 services.self_refutation.generate_project_critiques() 生成反驳
2. 从 Critique 表读取反驳结果
3. Critique 表包含完整的 LLM 质询数据（llm_critique_json）

示例：
```python
# 旧用法 (已废弃)
from medagent.agents.self_refutation import SelfRefutationAgent
agent = SelfRefutationAgent(db)
refutations = agent.batch_refute(project, molecules)

# 新用法 (推荐)
from medagent.services.self_refutation import generate_project_critiques
from medagent.db.models import Critique

# 1. 生成反驳（Pipeline 中已调用）
generate_project_critiques(db, project, settings, max_molecules=50)

# 2. 读取反驳结果
critiques = db.query(Critique).filter(
    Critique.molecule_id.in_([m.molecule_id for m in molecules])
).all()

# 3. 使用反驳数据
for critique in critiques:
    con_score = critique.con_score  # 包含 LLM 调整
    risk_level = critique.risk_level  # high/medium/low
    decision = critique.refutation_decision  # reject/reserve/pass
    llm_result = critique.llm_critique_json  # LLM 完整质询结果
```

如果需要兼容旧代码，可以使用以下 Facade 类（不推荐）：
"""

from dataclasses import dataclass, field

from sqlalchemy.orm import Session

from medagent.db.models import Critique, Molecule, Project


@dataclass
class RefutationPoint:
    """反驳点（已废弃，仅为兼容）"""
    category: str
    severity: str
    title: str
    description: str
    evidence: list[str] = field(default_factory=list)
    recommendation: str | None = None


@dataclass
class RefutationResult:
    """反驳结果（已废弃，仅为兼容）"""
    molecule_id: str
    overall_assessment: str
    confidence: float = 0.0
    refutation_points: list[RefutationPoint] = field(default_factory=list)
    strengths: list[str] = field(default_factory=list)
    weaknesses: list[str] = field(default_factory=list)
    recommendation: str = ""

    @property
    def confidence_score(self) -> float:
        return self.confidence

    @confidence_score.setter
    def confidence_score(self, value: float) -> None:
        self.confidence = value


class SelfRefutationAgent:
    """
    DEPRECATED 自我反驳Agent（已废弃）

    ⚠️ 此类已废弃，请使用 services/self_refutation.py + Critique 表

    保留此类仅为向后兼容，不建议使用。
    """

    def __init__(self, db: Session):
        self.db = db
        import warnings
        warnings.warn(
            "SelfRefutationAgent is deprecated. "
            "Use services.self_refutation.generate_project_critiques() "
            "and read from Critique table instead.",
            DeprecationWarning,
            stacklevel=2
        )

    def refute_molecule(
        self,
        project: Project,
        molecule: Molecule,
        strict_mode: bool = False,
    ) -> RefutationResult:
        """
        对单个分子进行反驳（已废弃）

        请改用：
        - 调用 generate_project_critiques() 生成反驳
        - 从 Critique 表读取结果
        """
        # 尝试从 Critique 表读取
        critique = self.db.query(Critique).filter_by(
            molecule_id=molecule.molecule_id
        ).first()

        if critique:
            return self._critique_to_refutation(critique)

        # 如果没有，返回空结果
        return RefutationResult(
            molecule_id=molecule.molecule_id,
            overall_assessment="unknown",
            confidence=0.0,
            recommendation="请先运行 generate_project_critiques() 生成反驳结果"
        )

    def batch_refute(
        self,
        project: Project,
        molecules: list[Molecule],
        strict_mode: bool = False,
    ) -> list[RefutationResult]:
        """
        批量反驳（已废弃）

        请改用：
        - 调用 generate_project_critiques() 生成反驳
        - 从 Critique 表批量读取结果
        """
        molecule_ids = [m.molecule_id for m in molecules]
        critiques = self.db.query(Critique).filter(
            Critique.molecule_id.in_(molecule_ids)
        ).all()

        critique_map = {c.molecule_id: c for c in critiques}

        results = []
        for molecule in molecules:
            critique = critique_map.get(molecule.molecule_id)
            if critique:
                results.append(self._critique_to_refutation(critique))
            else:
                results.append(RefutationResult(
                    molecule_id=molecule.molecule_id,
                    overall_assessment="unknown",
                    confidence=0.0,
                ))

        return results

    def _critique_to_refutation(self, critique: Critique) -> RefutationResult:
        """将 Critique 转换为 RefutationResult（兼容层）"""

        # 解析风险级别为 overall_assessment
        assessment_map = {
            "high": "rejected",
            "medium": "questionable",
            "low": "acceptable",
        }
        overall_assessment = assessment_map.get(critique.risk_level, "unknown")

        # 从 con_score 推断置信度
        confidence = min(100, critique.con_score or 0) / 100

        # 构建反驳点（简化版）
        refutation_points = []
        if critique.llm_critique_json:
            llm_critique = critique.llm_critique_json

            # 隐藏风险
            for risk in llm_critique.get("hidden_risks", []):
                refutation_points.append(RefutationPoint(
                    category="hidden_risk",
                    severity="high",
                    title="隐藏风险",
                    description=risk,
                ))

            # 证据质疑
            for concern in llm_critique.get("evidence_concerns", []):
                refutation_points.append(RefutationPoint(
                    category="evidence",
                    severity="medium",
                    title="证据质疑",
                    description=concern,
                ))

        return RefutationResult(
            molecule_id=critique.molecule_id,
            overall_assessment=overall_assessment,
            confidence=confidence,
            refutation_points=refutation_points,
            strengths=[],
            weaknesses=[critique.reason] if critique.reason else [],
            recommendation=critique.refutation_decision or "unknown",
        )
