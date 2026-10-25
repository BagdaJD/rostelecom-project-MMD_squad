"""Excel + проверенный региональный JSONL -> полный региональный scoring/matching."""

import argparse
import hashlib
import json
from datetime import date
from pathlib import Path

from ingestion.normalize import RawCompany, is_valid_inn
from ingestion.pipeline import analyze, write_result
from ingestion.review_matching import matching_report
from ingestion.sources.excel_source import read_excel
from ml.runtime import RuntimeMeasurement


def validate_combined(excel, fns_jsonl, fns_quality, output, *, as_of):
    manifest = json.loads(Path(fns_quality).read_text(encoding="utf-8"))
    if not manifest.get("complete") or manifest.get("scope") != "full_archive":
        raise ValueError("Для полного регионального прогона нужен завершённый аудит архива")
    output = Path(output)
    output.mkdir(parents=True, exist_ok=True)
    with RuntimeMeasurement() as runtime:
        data = read_excel(excel)
        records = data.companies
        count = 0
        with Path(fns_jsonl).open(encoding="utf-8") as stream:
            for line in stream:
                record = RawCompany(**json.loads(line))
                if (
                    record.region_code != "61"
                    or record.source != "fns_rsmp"
                    or not is_valid_inn(record.inn)
                ):
                    raise ValueError("JSONL содержит неподходящий источник, регион или ИНН")
                records.append(record)
                count += 1
        if count != manifest["unique_region_companies"]:
            raise ValueError("Количество JSONL-записей не совпало с полным аудитом")
        result = analyze(
            records, data.projects, as_of=as_of, quality={**data.quality, "fns": manifest}
        )
        summary, private_candidates = matching_report(
            [
                RawCompany(**{k: v for k, v in c.items() if k in RawCompany.__dataclass_fields__})
                for c in result["companies"]
            ],
            result["projects"],
        )
        (output / "private-candidates.json").write_text(
            json.dumps(private_candidates, ensure_ascii=False, indent=2), encoding="utf-8"
        )
        write_result(result, output)
        with Path(fns_jsonl).open("rb") as stream:
            normalized_hash = hashlib.file_digest(stream, "sha256").hexdigest()
    report = {
        "scope": "full_rostov_from_full_official_archive",
        "as_of": as_of.isoformat(),
        "excel_companies": len(data.companies) - count,
        "fns_companies": count,
        "combined_unique_companies": len(result["companies"]),
        "matching": summary,
        "quality": result["quality"],
        "runtime": runtime.result,
        "normalized_fns_sha256": normalized_hash,
        "territories": {
            "count": len(result["territories"]),
            "scores_min": min((c["potential_score"] for c in result["territories"]), default=None),
            "scores_max": max((c["potential_score"] for c in result["territories"]), default=None),
            "case_clients": sum(c["case_client_count"] for c in result["territories"]),
            "other_candidates": sum(c["registry_other_count"] for c in result["territories"]),
        },
        "white_spaces": result["white_spaces"],
    }
    (output / "summary.json").write_text(
        json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8"
    )
    return report


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--excel", type=Path, required=True)
    parser.add_argument("--fns-jsonl", type=Path, required=True)
    parser.add_argument("--fns-quality", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--as-of", type=date.fromisoformat, required=True)
    args = parser.parse_args()
    report = validate_combined(
        args.excel, args.fns_jsonl, args.fns_quality, args.output, as_of=args.as_of
    )
    print(
        json.dumps(
            {
                k: report[k]
                for k in (
                    "scope",
                    "excel_companies",
                    "fns_companies",
                    "combined_unique_companies",
                    "runtime",
                )
            }
        )
    )


if __name__ == "__main__":
    main()
