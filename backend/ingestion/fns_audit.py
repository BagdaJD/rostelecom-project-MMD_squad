"""Потоковый аудит настоящего XML/ZIP ФНС и локальный нормализованный JSONL."""

import argparse
import hashlib
import json
from collections import Counter
from pathlib import Path
from zipfile import ZipFile

from ingestion.sources.excel_source import read_excel
from ingestion.sources.fns_source import LocalFnsSource
from ml.runtime import RuntimeMeasurement


def audit_fns(path, excel, output, *, limit=None):
    path, output = Path(path), Path(output)
    output.mkdir(parents=True, exist_ok=True)
    clients = {c.inn for c in read_excel(excel).companies}
    source = LocalFnsSource(path)
    seen, overlaps = set(), set()
    coverage, categories, regions, dates = Counter(), Counter(), Counter(), Counter()
    duplicates = 0
    with RuntimeMeasurement() as runtime:
        with path.open("rb") as stream:
            sha = hashlib.file_digest(stream, "sha256").hexdigest()
        records = source.iter_companies()
        try:
            with (output / "companies.jsonl").open("w", encoding="utf-8") as stream:
                for record in records:
                    if record.inn in seen:
                        duplicates += 1
                        continue
                    seen.add(record.inn)
                    if record.inn in clients:
                        overlaps.add(record.inn)
                    payload = record.stable_payload()
                    stream.write(json.dumps(payload, ensure_ascii=False) + "\n")
                    for field in (
                        "industry_code",
                        "sme_category",
                        "employee_count",
                        "municipality",
                    ):
                        coverage[field] += payload.get(field) is not None
                    categories[record.sme_category or "unknown"] += 1
                    regions[record.region_code] += 1
                    dates[record.dump_date or "unknown"] += 1
                    if len(seen) % 10000 == 0:
                        print(
                            json.dumps(
                                {
                                    "accepted_unique": len(seen),
                                    "scanned_documents": source.counts["documents"],
                                    "rss_bytes": runtime.process.memory_info().rss,
                                }
                            ),
                            flush=True,
                        )
                    if limit and len(seen) >= limit:
                        break
        finally:
            records.close()
    if path.suffix.lower() == ".zip":
        with ZipFile(path) as archive:
            members = [i for i in archive.infolist() if i.filename.lower().endswith(".xml")]
            xml_count, uncompressed_bytes = len(members), sum(i.file_size for i in members)
    else:
        xml_count, uncompressed_bytes = 1, path.stat().st_size
    complete = not limit and source.counts["completed_xml_members"] == xml_count
    result = {
        "scope": "full_archive" if complete else "technical_partial",
        "complete": complete,
        "input_file": path.name,
        "input_bytes": path.stat().st_size,
        "sha256": sha,
        "xml_members": xml_count,
        "xml_uncompressed_bytes": uncompressed_bytes,
        "source_url": "https://www.nalog.gov.ru/opendata/7707329152-rsmp/",
        "counts": dict(source.counts),
        "unique_region_companies": len(seen),
        "duplicate_inn_rows": duplicates,
        "excel_matches": len(overlaps),
        "new_unique_candidates": len(seen - clients),
        "combined_unique_companies": len(seen | clients),
        "feature_coverage": {k: n / len(seen) if seen else None for k, n in coverage.items()},
        "sme_categories": dict(categories),
        "regions": dict(regions),
        "dump_dates": dict(dates),
        "errors": source.errors,
        "runtime": runtime.result,
        "crc_validation": "All XML streams read to EOF by zipfile" if complete else "partial only",
    }
    (output / "quality.json").write_text(
        json.dumps(result, ensure_ascii=False, indent=2), encoding="utf-8"
    )
    return result


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--input", type=Path, required=True)
    parser.add_argument("--excel", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--limit", type=int)
    args = parser.parse_args()
    if args.limit is not None and args.limit <= 0:
        parser.error("--limit должен быть положительным")
    print(json.dumps(audit_fns(args.input, args.excel, args.output, limit=args.limit), indent=2))


if __name__ == "__main__":
    main()
