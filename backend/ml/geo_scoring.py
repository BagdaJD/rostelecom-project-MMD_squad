"""Муниципалитет × отрасль; presence без подтверждения остаётся неизвестным."""

import math
from collections import defaultdict

from ml.scoring import load_scoring_config, quartile_cut


def score_territories(
    companies: list[dict], projects: list[dict], *, presence_complete=False, config=None
) -> list[dict]:
    config = config or load_scoring_config()
    groups = defaultdict(lambda: {"companies": [], "projects": []})
    for kind, records in (("companies", companies), ("projects", projects)):
        for row in records:
            territory = row.get("municipality") or f"region:{row.get('region_code') or 'unknown'}"
            groups[(territory, row.get("industry") or "unknown")][kind].append(row)
    cells = []
    for (territory, industry), rows in sorted(groups.items()):
        cs, ps = rows["companies"], rows["projects"]
        clients = sum(c.get("client_status") == "active" for c in cs)
        budgets = [p["investment_mln_rub"] for p in ps if p.get("investment_mln_rub") is not None]
        cells.append(
            {
                "municipality": territory,
                "industry": industry,
                "aggregation_level": "region"
                if territory.startswith("region:")
                else "municipality",
                "companies_count": len(cs),
                "case_client_count": clients,
                "registry_other_count": sum(
                    c.get("source") == "fns_rsmp" and c.get("client_status") != "active" for c in cs
                ),
                "projects_count": len(ps),
                "investment_mln_rub": sum(budgets) if budgets else None,
                "investment_coverage": len(budgets) / len(ps) if ps else None,
                "revenue_growth": None,
                "financial_data_available": False,
                "presence_score": 100 * clients / len(cs) if presence_complete and cs else None,
                "presence_basis": "case_sample" if presence_complete else "unknown",
                "presence_status": "known_case_sample"
                if presence_complete and cs
                else "insufficient_presence_data",
                "limitations": [
                    "Условная клиентская база кейса не отражает реальные контракты",
                    "Счётчики отражают загруженную выборку, не весь рынок",
                ],
            }
        )
    maxima = {
        k: max((c[k] or 0 for c in cells), default=0)
        for k in ("companies_count", "projects_count", "investment_mln_rub")
    }
    weights = config["territory_weights"]
    mapping = {
        "companies": "companies_count",
        "projects": "projects_count",
        "investment": "investment_mln_rub",
    }
    for cell in cells:
        values = {
            k: (math.log1p(cell[col]) / math.log1p(maxima[col]) if maxima[col] > 0 else 0)
            if cell[col] is not None
            else None
            for k, col in mapping.items()
        }
        coverage = sum(weights[k] for k, v in values.items() if v is not None)
        cell["factors"] = [
            {
                "code": k,
                "value": v,
                "available": v is not None,
                "contribution": v * weights[k] / coverage * 100
                if v is not None and coverage
                else None,
            }
            for k, v in values.items()
        ]
        cell["potential_score"] = round(sum(f["contribution"] or 0 for f in cell["factors"]), 2)
        cell["data_quality"] = "limited"
        cell["model_version"] = config["model_version"]
    return cells


def find_white_spaces(cells: list[dict], *, minimum_size: int = 4) -> dict:
    known = [
        c
        for c in cells
        if c.get("presence_score") is not None
        and c.get("potential_score") is not None
        and c.get("industry") != "unknown"
    ]
    if not known:
        return {"status": "insufficient_presence_data", "results": []}
    # Сравниваем территории внутри отрасли, не смешивая несовместимые рынки.
    groups = defaultdict(list)
    for cell in known:
        groups[(cell.get("industry"), cell.get("aggregation_level"))].append(cell)
    output, comparisons = [], []
    for (industry, level), sample in groups.items():
        potentials = [c["potential_score"] for c in sample]
        presence = [c["presence_score"] for c in sample]
        if len(sample) < minimum_size or len(set(potentials)) < 2 or len(set(presence)) < 2:
            continue
        p75, p25 = quartile_cut(potentials, 0.75), quartile_cut(presence, 0.25)
        comparisons.append(
            {
                "industry": industry,
                "level": level,
                "n": len(sample),
                "potential_p75": p75,
                "presence_p25": p25,
            }
        )
        for cell in sample:
            if cell["potential_score"] >= p75 and cell["presence_score"] <= p25:
                output.append(
                    {
                        **cell,
                        "reason": [
                            f"Потенциал {cell['potential_score']} >= P75 {p75:.2f}",
                            f"Присутствие в выборке {cell['presence_score']:.2f} <= P25 {p25:.2f}",
                            f"Компаний: {cell['companies_count']}; "
                            f"проектов: {cell['projects_count']}",
                        ],
                    }
                )
    return {
        "status": "ok" if comparisons else "insufficient_comparison_data",
        "comparisons": comparisons,
        "results": sorted(output, key=lambda c: -c["potential_score"]),
    }
