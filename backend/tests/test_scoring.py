from datetime import date

import pytest

from ingestion.features import company_features
from ingestion.normalize import RawCompany
from ml.geo_scoring import find_white_spaces, score_territories
from ml.scoring import load_scoring_config, quartile_cut, score_company

AS_OF = date(2026, 10, 24)


def profile(**kwargs):
    return {"industry": "industry", "employee_count": 20, "confirmed_projects": [], **kwargs}


def test_config_and_contributions_are_consistent():
    config = load_scoring_config()
    assert config["company_weights"] == {
        "industry_fit": 0.3,
        "company_size": 0.2,
        "investment_activity": 0.3,
        "timeliness": 0.2,
    }
    result = score_company(profile(), as_of=AS_OF)
    assert result == score_company(profile(), as_of=AS_OF)
    assert 0 <= result["score"] <= 100
    assert sum(f["contribution"] or 0 for f in result["factors"]) == pytest.approx(
        result["score"], abs=0.01
    )
    assert result["feature_coverage"] == 0.5
    assert result["factors"][2]["value"] is None


def test_more_employees_monotonically_raise_score():
    values = [
        score_company(profile(employee_count=n), as_of=AS_OF)["score"]
        for n in [0, 1, 10, 250, 1000]
    ]
    assert values == sorted(values) and values[-1] == values[-2]


def test_empty_critical_data_abstains_and_zero_is_known():
    result = score_company({}, as_of=AS_OF)
    assert result["score"] is None and result["data_quality"] == "insufficient"
    result = score_company(profile(employee_count=0), as_of=AS_OF)
    assert result["factors"][1]["available"] and result["factors"][1]["value"] == 0


def test_unconfirmed_project_never_influences_company():
    original = score_company(profile(), as_of=AS_OF)
    possible = profile(possible_projects=[{"investment_mln_rub": 100000}])
    assert score_company(possible, as_of=AS_OF) == original


def test_semantic_similarity_alone_does_not_raise_score():
    project = {"investment_mln_rub": 100, "start_year": 2026, "end_year": 2027}
    a = score_company(profile(industry="services", confirmed_projects=[project]), as_of=AS_OF)
    project = {
        **project,
        "recommendations": [
            {
                "rule_id": "inferred:semantic",
                "evidence_type": "inferred",
                "semantic_similarity": 0.999,
            }
        ],
    }
    b = score_company(profile(industry="services", confirmed_projects=[project]), as_of=AS_OF)
    assert a["score"] == b["score"] and b["nlp_influence"] == "none"


def test_nlp_context_contributes_once():
    project = {
        "investment_mln_rub": 100,
        "start_year": 2026,
        "end_year": 2027,
        "recommendations": [{"rule_id": "inferred:production", "evidence_type": "inferred"}],
    }
    one = score_company(profile(industry="services", confirmed_projects=[project]), as_of=AS_OF)
    project["recommendations"] *= 5
    repeated = score_company(
        profile(industry="services", confirmed_projects=[project]), as_of=AS_OF
    )
    assert repeated == one
    assert one["feature_coverage"] == 1


def test_quantiles_known_values_and_bounds():
    assert quartile_cut([0, 10, 20, 30], 0.75) == 22.5
    with pytest.raises(ValueError):
        quartile_cut([1, 2], 1.1)
    with pytest.raises(ValueError):
        quartile_cut([float("nan")], 0.75)


def cell(potential, presence, **kwargs):
    return {
        "potential_score": potential,
        "presence_score": presence,
        "industry": "industry",
        "aggregation_level": "municipality",
        "companies_count": 10,
        "projects_count": 1,
        **kwargs,
    }


def test_white_space_requires_known_presence_variation_and_sample():
    assert find_white_spaces([cell(100, None)])["status"] == "insufficient_presence_data"
    assert find_white_spaces([cell(100, 0)])["results"] == []
    assert find_white_spaces([cell(100, 0)] * 10)["results"] == []
    sample = [cell(10, 90), cell(20, 60), cell(30, 30), cell(100, 0)]
    result = find_white_spaces(sample)
    assert result["status"] == "ok" and len(result["results"]) == 1
    assert result["results"][0]["potential_score"] == 100


def test_territory_aggregation_has_no_fictional_finance_or_presence():
    companies = [
        {
            "municipality": "Тестовый район",
            "industry": "industry",
            "client_status": "active",
            "source": "case_excel",
        }
    ]
    result = score_territories(
        companies * 2,
        [{"municipality": "Тестовый район", "industry": "industry", "investment_mln_rub": 136}],
    )[0]
    assert result["companies_count"] == 2 and result["investment_mln_rub"] == 136
    assert result["revenue_growth"] is None and result["presence_score"] is None


def test_name_match_is_excluded_from_confirmed_features():
    company = RawCompany(source="test", external_id="1", name="ООО Тест", region_code="61")
    projects = [
        {"title": "Завод", "external_id": "p1", "initiator": "ООО Тест", "region_code": "61"}
    ]
    features, counts = company_features([company], projects)
    assert counts["requires_review"] == 1
    assert features[0]["confirmed_projects"] == []
