"""Локальные кандидаты инициаторов и публичный отчёт только с агрегатами."""

import argparse
import json
import re
from collections import Counter
from dataclasses import asdict
from pathlib import Path

from ingestion.matching import InitiatorReviewIndex, match_initiator
from ingestion.normalize import RawCompany


def matching_report(companies, projects):
    index = InitiatorReviewIndex(companies)
    local, statuses, methods = [], Counter(), Counter()
    cross_municipality = 0
    for project in projects:
        decision = match_initiator(project, companies, review_index=index)
        suggestions = index.find(project)
        statuses[decision.status] += 1
        methods[decision.method] += 1
        cross_municipality += any(not s["same_municipality"] for s in suggestions)
        local.append(
            {
                "project_id": project["external_id"],
                "initiator": project.get("initiator"),
                "municipality": project.get("municipality"),
                "decision": asdict(decision),
                "candidates": [
                    {
                        **s,
                        "name": companies[s["index"]].name,
                        "inn": companies[s["index"]].inn,
                        "municipality": companies[s["index"]].municipality,
                    }
                    for s in suggestions
                ],
            }
        )
    summary = {
        "projects": len(projects),
        "loaded_companies": len(companies),
        "statuses": dict(statuses),
        "methods": dict(methods),
        "missing_initiator_inn": sum(not p.get("initiator_inn") for p in projects),
        "group_name_mentions": sum(
            bool(re.search(r"(?:\bГК\b|групп\w*\s+компан)", p.get("initiator") or "", re.I))
            for p in projects
        ),
        "projects_with_cross_municipality_suggestions": cross_municipality,
        "threshold": 0.88,
        "interpretation": "Text similarity -> requires_review; no verified link or score uplift",
    }
    return summary, local


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--input", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    data = json.loads(args.input.read_text(encoding="utf-8"))
    fields = RawCompany.__dataclass_fields__
    companies = [
        RawCompany(**{k: v for k, v in c.items() if k in fields}) for c in data["companies"]
    ]
    summary, local = matching_report(companies, data["projects"])
    args.output.mkdir(parents=True, exist_ok=True)
    for name, payload in (("summary.json", summary), ("private-candidates.json", local)):
        (args.output / name).write_text(
            json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8"
        )
    print(json.dumps(summary))


if __name__ == "__main__":
    main()
