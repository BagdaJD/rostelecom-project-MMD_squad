"""Потоковый локальный XML/ZIP РМСП. Схема ФНС structure-12052026.xsd.

Регион берётся из СведМН/@КодРегион, не из первых цифр ИНН.
ZIP читается без распаковки. Синтаксически повреждённый XML прекращает свой member,
ошибка фиксируется; ошибки отдельных записей не прекращают обработку остальных.
"""

from collections import Counter
from collections.abc import Iterator
from pathlib import Path
from zipfile import BadZipFile, ZipFile

from lxml import etree

from ingestion.geography import municipality
from ingestion.normalize import (
    RawCompany,
    clean_text,
    integer,
    is_valid_inn,
    is_valid_ogrn,
    iso_date,
)

SOURCE_URL = "https://www.nalog.gov.ru/opendata/7707329152-rsmp/"


def _first(element, name):
    return next((e for e in element.iter() if etree.QName(e).localname == name), None)


class LocalFnsSource:
    def __init__(self, path: str | Path, region_code="61", dump_date: str | None = None):
        self.path = Path(path)
        self.region_code = region_code
        self.dump_date = dump_date
        self.counts = Counter()
        self.errors: list[dict] = []

    def _error(self, details):
        if len(self.errors) < 100:
            self.errors.append(details)

    def _records(self, stream, member: str) -> Iterator[RawCompany]:
        try:
            context = etree.iterparse(
                stream,
                events=("end",),
                tag="{*}Документ",
                resolve_entities=False,
                no_network=True,
                load_dtd=False,
                huge_tree=False,
            )
            for _, doc in context:
                if etree.QName(doc).localname != "Документ":
                    continue
                self.counts["documents"] += 1
                try:
                    record = self._parse(doc, member)
                    if record is not None:
                        if not is_valid_inn(record.inn):
                            self.counts["invalid_inn"] += 1
                            raise ValueError("invalid_inn")
                        self.counts["valid_inn"] += 1
                        if record.ogrn and not is_valid_ogrn(record.ogrn):
                            self.counts["invalid_ogrn"] += 1
                        self.counts["accepted"] += 1
                        yield record
                except (ValueError, TypeError, KeyError):
                    self.counts["invalid_records"] += 1
                    self._error(
                        {"member": member, "line": doc.sourceline, "code": "invalid_record"}
                    )
                finally:
                    doc.clear()
                    while doc.getprevious() is not None:
                        del doc.getparent()[0]
            self.counts["completed_xml_members"] += 1
        except etree.XMLSyntaxError as exc:
            self.counts["malformed_members"] += 1
            self._error({"member": member, "line": exc.lineno, "code": "malformed_xml"})

    def _parse(self, doc, member) -> RawCompany | None:
        address = _first(doc, "СведМН")
        region = address.get("КодРегион") if address is not None else None
        if region != self.region_code:
            self.counts["other_or_missing_region"] += 1
            return None
        org, person = _first(doc, "ОргВклМСП"), _first(doc, "ИПВклМСП")
        if org is None and person is None:
            raise ValueError("missing_subject")
        if org is not None:
            name = org.get("НаимОрг") or org.get("НаимОргСокр")
            inn, ogrn = org.get("ИННЮЛ"), org.get("ОГРН")
        else:
            fio = _first(person, "ФИОИП")
            name = (
                " ".join(fio.get(k, "") for k in ("Фамилия", "Имя", "Отчество"))
                if (fio is not None)
                else None
            )
            inn, ogrn = person.get("ИННФЛ"), person.get("ОГРНИП")
        if not clean_text(name) or not (inn or ogrn):
            raise ValueError("missing_identity")
        district, city = _first(address, "Район"), _first(address, "Город")
        okved = _first(doc, "СвОКВЭДОсн")
        return RawCompany(
            source="fns_rsmp",
            external_id=doc.get("ИдДок") or f"{member}:{inn or ogrn}",
            name=name.strip(),
            inn=inn,
            ogrn=ogrn,
            region_code=region,
            municipality=municipality(
                district.get("Наим") if district is not None else None,
                city.get("Наим") if city is not None else None,
                region_code=region,
            ),
            industry_code=okved.get("КодОКВЭД") if okved is not None else None,
            okved_description=okved.get("НаимОКВЭД") if okved is not None else None,
            employee_count=integer(doc.get("ССЧР")),
            subject_type="Юридическое лицо"
            if org is not None
            else "Индивидуальный предприниматель",
            sme_category={
                "1": "Микропредприятие",
                "2": "Малое предприятие",
                "3": "Среднее предприятие",
            }.get(doc.get("КатСубМСП")),
            included_at=iso_date(doc.get("ДатаВклМСП")),
            dump_date=self.dump_date or iso_date(doc.get("ДатаСост")),
            client_status="unknown",
            source_url=SOURCE_URL,
            license_note="Локальная открытая выгрузка РМСП ФНС; источник указан",
        )

    def iter_companies(self) -> Iterator[RawCompany]:
        self.counts.clear()
        self.errors.clear()
        if self.path.suffix.lower() == ".zip":
            try:
                with ZipFile(self.path) as archive:
                    for member in archive.infolist():
                        if member.filename.lower().endswith(".xml") and not member.is_dir():
                            with archive.open(member) as stream:
                                yield from self._records(stream, member.filename)
            except BadZipFile:
                self.errors.append({"code": "bad_zip"})
        else:
            with self.path.open("rb") as stream:
                yield from self._records(stream, self.path.name)
