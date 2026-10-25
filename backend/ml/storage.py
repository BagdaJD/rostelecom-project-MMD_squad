"""Хранение NLP в существующей ProjectNeed; HTTP только читает результат."""

from sqlalchemy import delete

from app.models import ProjectNeed


def replace_needs(session, project_id, predictions):
    session.execute(delete(ProjectNeed).where(ProjectNeed.project_id == project_id))
    created = []
    for prediction in predictions:
        data = prediction.as_dict() if hasattr(prediction, "as_dict") else prediction
        details = {
            k: data.get(k)
            for k in (
                "evidence_type",
                "reason",
                "semantic_similarity",
                "confidence_label",
                "data_quality",
            )
        }
        row = ProjectNeed(
            project_id=project_id,
            need_category=data["need_category"],
            probability=None,
            evidence=data.get("evidence"),
            rule_id=data.get("rule_id"),
            model_version=data["model_version"],
            details_json=details,
        )
        session.add(row)
        created.append(row)
    session.flush()
    return created
