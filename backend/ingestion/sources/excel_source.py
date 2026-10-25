"""Чтение двух листов кейса; листы калькулятора даже не загружаются."""

import re
from collections import Counter
from dataclasses import dataclass
from pathlib import Path
from time import perf_counter

import pandas as pd

from ingestion.geography import municipality, normalize_municipality
from ingestion.normalize import (
    RawCompany,
    clean_text,
    identifier,
    integer,
    is_valid_inn,
    iso_date,
    number,
    payload_hash,
)


@dataclass
class ExcelData:
    companies: list[RawCompany]
    projects: list[dict]
    quality: dict


def _column(columns, prefix):
    return next((c for c in columns if str(c).strip().startswith(prefix)), None)


def read_excel(path: Path | str, *, placeholder_fields: tuple[str, ...] = ()) -> ExcelData:
    start = perf_counter()
    path = Path(path)
    companies, projects = [], []
    quality = {"source": path.name, "sheets": {}, "warnings": [], "errors": []}
    with pd.ExcelFile(path, engine="openpyxl") as book:
        for sheet in book.sheet_names:
            if sheet.startswith("МОД3_"):
                continue
            headers = pd.read_excel(book, sheet_name=sheet, nrows=0).columns
            company_sheet = all(h in headers for h in ("ИНН", "ОГРН", "Тип субъекта"))
            project_sheet = (
                all(
                    h in headers
                    for h in (
                        "Муниципальное образование",
                        "Инициатор инвестиционного проекта",
                    )
                )
                and _column(headers, "Название и суть") is not None
            )
            if not (company_sheet or project_sheet):
                continue
            df = pd.read_excel(book, sheet_name=sheet, dtype=str, keep_default_na=False)
            df = df.loc[df.apply(lambda r: any(clean_text(v) for v in r), axis=1)]
            quality["sheets"][sheet] = {
                "rows": len(df),
                "missing": {c: sum(clean_text(v) is None for v in df[c]) for c in df},
                "placeholder_136": {
                    c: sum(str(v).strip() in ("136", "136.0") for v in df[c])
                    for c in ("Район", "Город", "Населенный пункт", "Телефон", "E-mail", "WWW")
                    if c in df
                },
            }
            for row_index, row in df.iterrows():
                external_id = f"{sheet}:{clean_text(row.get('№ п/п')) or row_index + 2}"
                if company_sheet:
                    raw_region = clean_text(row.get("Регион"))
                    region = re.match(r"([0-9]{2})\b", raw_region or "")
                    region_code = region[1] if region else None
                    okved = clean_text(row.get("Основной вид деятельности"))
                    parts = re.match(r"([0-9]{2}(?:\.[0-9]{1,2}){0,2})\s*(.*)", okved or "")
                    district = clean_text(
                        row.get("Район"), placeholder_136="Район" in placeholder_fields
                    )
                    city = clean_text(
                        row.get("Город"), placeholder_136="Город" in placeholder_fields
                    )
                    companies.append(
                        RawCompany(
                            source="case_excel",
                            external_id=external_id,
                            name=clean_text(row.get("Наименование / ФИО")) or "",
                            inn=identifier(row.get("ИНН")),
                            ogrn=identifier(row.get("ОГРН")),
                            industry_code=parts[1] if parts else None,
                            okved_description=parts[2] if parts else okved,
                            region_code=region_code,
                            municipality=municipality(district, city, region_code=region_code),
                            subject_type=clean_text(row.get("Тип субъекта")),
                            sme_category=clean_text(row.get("Категория")),
                            employee_count=integer(row.get(_column(headers, "Среднесписочная"))),
                            included_at=iso_date(row.get("Дата включения в реестр")),
                            excluded_at=iso_date(row.get("Дата исключения из реестра")),
                            client_status="active",
                            license_note="Условные клиенты кейса; не корпоративная CRM",
                        )
                    )
                else:
                    title = clean_text(row.get(_column(headers, "Название и суть")))
                    if not title:
                        quality["errors"].append(
                            {"row": int(row_index) + 2, "code": "missing_title"}
                        )
                        continue
                    start_year, end_year = (
                        integer(row.get("Начало")),
                        integer(row.get("Ввод в эксплуатацию")),
                    )
                    projects.append(
                        {
                            "source": "case_excel",
                            "external_id": external_id,
                            "title": title,
                            "description": None,
                            "initiator": clean_text(row.get("Инициатор инвестиционного проекта")),
                            "initiator_inn": None,
                            "municipality": normalize_municipality(
                                row.get("Муниципальное образование")
                            ),
                            "region_code": "61",
                            "start_year": start_year,
                            "end_year": end_year,
                            "planned_start": None,
                            "planned_end": None,
                            "date_precision": "year",
                            "investment_mln_rub": number(row.get("Всего (млн руб.)")),
                            "new_jobs": integer(
                                row.get(_column(headers, "Количество новых рабочих"))
                            ),
                            "stage": "unknown",
                            "coordinates": None,
                        }
                    )
    if not companies or not projects:
        raise ValueError("Не найдены непустые листы компаний и инвестиционных проектов")
    inns = Counter(c.inn for c in companies if c.inn)
    valid = sum(is_valid_inn(c.inn) for c in companies)
    quality.update(
        {
            "source_companies": len(companies),
            "source_projects": len(projects),
            "unique_inn": len(inns),
            "valid_inn": valid,
            "invalid_inn": len(companies) - valid,
            "valid_inn_percent": round(100 * valid / len(companies), 3),
            "duplicate_inn_rows": sum(n - 1 for n in inns.values()),
            "duplicate_projects": len(projects) - len({payload_hash(p) for p in projects}),
            "excel_seconds": perf_counter() - start,
        }
    )
    return ExcelData(companies, projects, quality)
