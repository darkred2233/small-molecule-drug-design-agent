from sqlalchemy.orm import Session

from medagent.data.builtin_targets import load_builtin_targets
from medagent.db.models import Target, TargetDrugLibrary


def seed_builtin_targets(db: Session) -> None:
    builtin_targets = load_builtin_targets()
    for target_payload in builtin_targets:
        target = db.query(Target).filter_by(target_id=target_payload["target_id"]).one_or_none()
        if target is None:
            target = Target(
                target_id=target_payload["target_id"],
                name=target_payload["name"],
                aliases=target_payload["aliases"],
                uniprot_id=target_payload["uniprot_id"],
                species=target_payload["species"],
                pdb_ids=target_payload["pdb_ids"],
                summary=target_payload["summary"],
            )
            db.add(target)

        for drug_payload in target_payload["drugs"]:
            exists = (
                db.query(TargetDrugLibrary)
                .filter_by(
                    target_id=target_payload["target_id"],
                    drug_name=drug_payload["drug_name"],
                )
                .one_or_none()
            )
            if exists is None:
                db.add(TargetDrugLibrary(target_id=target_payload["target_id"], **drug_payload))
            else:
                for key, value in drug_payload.items():
                    setattr(exists, key, value)
    db.commit()
