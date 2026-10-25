"""Локальные пакетные команды; без доступа к БД до явного import-db."""

import argparse
import json
import sys
from datetime import date
from pathlib import Path

from ingestion.normalize import RawCompany
from ingestion.pipeline import analyze, run_pipeline, write_result
from ingestion.sources.excel_source import read_excel
from ingestion.sources.fns_source import LocalFnsSource
from ml.embeddings import EmbeddingConfig, SemanticRanker
from ml.evaluation import annotation_template
from ml.needs import load_catalog
from ml.recommender import HybridRecommender


def main():
    if hasattr(sys.stdout, "reconfigure"):
        sys.stdout.reconfigure(encoding="utf-8")
    parser = argparse.ArgumentParser(description=__doc__)
    commands = parser.add_subparsers(dest="command", required=True)
    run = commands.add_parser("run", help="Excel + optional FNS -> NLP -> scoring -> artifacts")
    run.add_argument("--excel", type=Path, required=True)
    run.add_argument("--fns", type=Path)
    excel = commands.add_parser("excel", help="Только нормализация Excel")
    excel.add_argument("--excel", type=Path, required=True)
    fns = commands.add_parser("fns", help="Потоковый XML/ZIP -> JSONL")
    fns.add_argument("--path", type=Path, required=True)
    fns.add_argument("--region", default="61")
    fns.add_argument("--dump-date")
    for name in ("nlp", "score", "import-db", "annotation-template"):
        sub = commands.add_parser(name)
        sub.add_argument("--input", type=Path, required=True)
    for name, sub in commands.choices.items():
        if name != "import-db":
            sub.add_argument("--output", type=Path, required=True)
        if name in ("run", "nlp", "score"):
            sub.add_argument("--as-of", type=date.fromisoformat, required=True)
            sub.add_argument("--semantic", action="store_true")
            sub.add_argument("--model-path")
            sub.add_argument("--revision", default="main")
            sub.add_argument("--threshold", type=float, default=0.84)
            sub.add_argument("--catalog", type=Path)
    args = parser.parse_args()
    if args.command == "fns":
        source = LocalFnsSource(args.path, args.region, args.dump_date)
        args.output.parent.mkdir(parents=True, exist_ok=True)
        with args.output.open("w", encoding="utf-8") as stream:
            for company in source.iter_companies():
                stream.write(json.dumps(company.stable_payload(), ensure_ascii=False) + "\n")
        print(
            json.dumps({"counts": dict(source.counts), "errors": source.errors}, ensure_ascii=False)
        )
        return
    if args.command == "excel":
        data = read_excel(args.excel)
        write_result(
            {
                "format_version": "mmd-pipeline-1",
                "companies": [c.stable_payload() for c in data.companies],
                "projects": data.projects,
                "quality": data.quality,
            },
            args.output,
        )
        print(json.dumps(data.quality, ensure_ascii=False))
        return
    if args.command in ("import-db", "annotation-template"):
        data = json.loads(args.input.read_text(encoding="utf-8"))
        if args.command == "annotation-template":
            args.output.parent.mkdir(parents=True, exist_ok=True)
            args.output.write_text(
                json.dumps(annotation_template(data["projects"]), ensure_ascii=False, indent=2),
                encoding="utf-8",
            )
        else:
            from app.db.session import SessionLocal
            from ingestion.persistence import import_result

            with SessionLocal.begin() as session:
                print(json.dumps(import_result(session, data)))
        return
    ranker = (
        SemanticRanker(
            load_catalog(args.catalog),
            EmbeddingConfig(
                model_path=args.model_path, revision=args.revision, threshold=args.threshold
            ),
        )
        if args.semantic
        else None
    )
    recommender = HybridRecommender(ranker, args.catalog)
    if args.command == "run":
        result = run_pipeline(args.excel, fns=args.fns, as_of=args.as_of, recommender=recommender)
    else:
        data = json.loads(args.input.read_text(encoding="utf-8"))
        fields = RawCompany.__dataclass_fields__
        companies = [
            RawCompany(**{k: v for k, v in c.items() if k in fields})
            for c in data.get("source_records", data["companies"])
        ]
        result = analyze(
            companies,
            data["projects"],
            as_of=args.as_of,
            recommender=recommender,
            quality=data.get("quality"),
            reuse_recommendations=args.command == "score",
        )
        if args.command == "score" and data.get("configuration"):
            result["configuration"]["embedding"] = data["configuration"].get("embedding")
    write_result(result, args.output)
    print(json.dumps(result["quality"], ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
