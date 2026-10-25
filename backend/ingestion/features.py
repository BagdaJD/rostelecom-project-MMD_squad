"""Наблюдаемые признаки и provenance; нет фиктивной стадии или геолокации."""

from dataclasses import asdict

from ingestion.matching import InitiatorReviewIndex, match_initiator
from ingestion.normalize import RawCompany
from ml.needs import load_catalog, matching_scenarios


def industry_for_okved(code: str | None) -> str | None:
    if not code:
        return None
    try:
        head = int(code.split(".")[0])
    except ValueError:
        return None
    if 1 <= head <= 3:
        return "agriculture"
    if 5 <= head <= 9 or 35 <= head <= 39:
        return "energy"
    if 10 <= head <= 33:
        return "industry"
    if 41 <= head <= 43 or head == 68:
        return "housing"
    if 45 <= head <= 47:
        return "trade"
    if 49 <= head <= 53:
        return "logistics"
    if 55 <= head <= 96:
        return "services"
    return None


def project_features(project: dict) -> dict:
    text = "\n".join(project.get(k) or "" for k in ("title", "description"))
    scenarios = matching_scenarios(text, load_catalog())
    return {
        **project,
        "industry": scenarios[0]["industry"] if scenarios else None,
        "industry_basis": "text_scenario" if scenarios else None,
    }


def company_features(companies: list[RawCompany], projects: list[dict]) -> tuple[list[dict], dict]:
    result = []
    for record in companies:
        data = record.stable_payload()
        data.update(
            {
                "industry": industry_for_okved(record.industry_code),
                "confirmed_projects": [],
                "possible_projects": [],
            }
        )
        result.append(data)
    counts = {"matched": 0, "requires_review": 0, "unmatched": 0, "unique_review_candidates": 0}
    review_index = InitiatorReviewIndex(companies)
    for project in projects:
        decision = match_initiator(project, companies, review_index=review_index)
        project["company_match"] = asdict(decision)
        counts[decision.status] += 1
        if decision.status == "requires_review" and len(decision.candidate_indices) == 1:
            counts["unique_review_candidates"] += 1
        if decision.status == "matched" and len(decision.candidate_indices) == 1:
            result[decision.candidate_indices[0]]["confirmed_projects"].append(project)
        elif decision.status == "requires_review":
            for index in decision.candidate_indices:
                result[index]["possible_projects"].append(project["external_id"])
    return result, counts
