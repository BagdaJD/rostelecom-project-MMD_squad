"""Только валидные идентификаторы разрешают автоматическое объединение."""

from collections import defaultdict
from dataclasses import dataclass, replace
from difflib import SequenceMatcher

from ingestion.normalize import (
    RawCompany,
    is_valid_inn,
    is_valid_ogrn,
    normalize_name,
    payload_hash,
)


@dataclass(frozen=True)
class EntityMatch:
    status: str
    method: str
    confidence: float
    candidate_indices: tuple[int, ...] = ()


def match_company(record: RawCompany, candidates: list[RawCompany]) -> EntityMatch:
    if is_valid_inn(record.inn):
        indices = tuple(i for i, c in enumerate(candidates) if c.inn == record.inn)
        if indices:
            if len(indices) > 1:
                return EntityMatch("requires_review", "multiple_identifiers", 0, indices)
            # Даже совпадение ИНН не разрешает конфликт второго валидного идентификатора.
            if is_valid_ogrn(record.ogrn) and any(
                is_valid_ogrn(candidates[i].ogrn) and candidates[i].ogrn != record.ogrn
                for i in indices
            ):
                return EntityMatch("requires_review", "identifier_conflict", 0, indices)
            return EntityMatch("matched", "inn", 1, indices)
    if is_valid_ogrn(record.ogrn):
        indices = tuple(i for i, c in enumerate(candidates) if c.ogrn == record.ogrn)
        if indices:
            if len(indices) > 1:
                return EntityMatch("requires_review", "multiple_identifiers", 0, indices)
            if is_valid_inn(record.inn) and any(
                is_valid_inn(candidates[i].inn) and candidates[i].inn != record.inn for i in indices
            ):
                return EntityMatch("requires_review", "identifier_conflict", 0, indices)
            return EntityMatch("matched", "ogrn", 1, indices)
    name = normalize_name(record.name)
    possible = tuple(
        i
        for i, c in enumerate(candidates)
        if name
        and normalize_name(c.name) == name
        and record.region_code
        and record.region_code == c.region_code
        and (not record.municipality or record.municipality == c.municipality)
    )
    return (
        EntityMatch("requires_review", "name_territory", 0.75, possible)
        if possible
        else (EntityMatch("unmatched", "new", 0))
    )


class InitiatorReviewIndex:
    """Индекс кандидатов для review; регистрации и место проекта могут различаться."""

    def __init__(self, candidates):
        self.candidates = candidates
        self.names = [normalize_name(c.name) for c in candidates]
        self.exact, self.tokens = defaultdict(list), defaultdict(set)
        self.noise = {"гк", "группа", "компаний", "компания", "ростов", "дон", "юг"}
        for i, company in enumerate(candidates):
            self.exact[(company.region_code, self.names[i])].append(i)
            for token in self.names[i].split():
                if len(token) >= 3 and token not in self.noise:
                    self.tokens[(company.region_code, token)].add(i)

    def find(self, project, *, threshold=0.88, top_k=5):
        name, region = normalize_name(project.get("initiator")), project.get("region_code")
        if not name or not region:
            return []
        possible = set(self.exact.get((region, name), []))
        significant = {t for t in name.split() if len(t) >= 3 and t not in self.noise}
        buckets = [
            self.tokens[(region, token)] for token in significant if (region, token) in self.tokens
        ]
        for bucket in sorted(buckets, key=len)[:2]:
            possible.update(bucket)
        result = []
        for index in possible:
            candidate_name = self.names[index]
            score = max(
                SequenceMatcher(None, name, candidate_name, autojunk=False).ratio(),
                SequenceMatcher(
                    None,
                    " ".join(sorted(name.split())),
                    " ".join(sorted(candidate_name.split())),
                    autojunk=False,
                ).ratio(),
            )
            if score < threshold:
                continue
            company = self.candidates[index]
            result.append(
                {
                    "index": index,
                    "text_similarity": score,
                    "exact_name": name == candidate_name,
                    "same_municipality": bool(project.get("municipality"))
                    and project["municipality"] == company.municipality,
                }
            )
        return sorted(
            result, key=lambda r: (-r["text_similarity"], not r["same_municipality"], r["index"])
        )[:top_k]


def match_initiator(
    project: dict, candidates: list[RawCompany], *, review_index=None
) -> EntityMatch:
    record = RawCompany(
        source=project.get("source", "project"),
        external_id=project.get("external_id"),
        name=project.get("initiator") or "",
        inn=project.get("initiator_inn"),
        ogrn=project.get("initiator_ogrn"),
        region_code=project.get("region_code"),
        municipality=project.get("municipality"),
    )
    if review_index is not None and not is_valid_inn(record.inn) and not is_valid_ogrn(record.ogrn):
        exact = tuple(
            i
            for i in review_index.exact.get((record.region_code, normalize_name(record.name)), [])
            if not record.municipality or record.municipality == candidates[i].municipality
        )
        decision = (
            EntityMatch("requires_review", "name_territory", 0.75, exact)
            if exact
            else (EntityMatch("unmatched", "new", 0))
        )
    else:
        decision = match_company(record, candidates)
    if decision.status != "unmatched":
        return decision
    suggestions = (review_index or InitiatorReviewIndex(candidates)).find(project)
    if suggestions:
        return EntityMatch(
            "requires_review",
            "name_review",
            0.75 * suggestions[0]["text_similarity"],
            tuple(s["index"] for s in suggestions),
        )
    return decision


def unique_companies(records: list[RawCompany]) -> tuple[list[RawCompany], dict]:
    unique: list[RawCompany] = []
    counts = {"identifier_matches": 0, "requires_review": 0, "duplicates": 0}
    identities: dict[tuple, int] = {}
    by_inn, by_ogrn, by_name = {}, {}, {}
    for record in records:
        source_key = (record.source, record.external_id, payload_hash(record.stable_payload()))
        if source_key in identities:
            counts["duplicates"] += 1
            continue
        # Индексы не допускают квадратичного сканирования локальной выгрузки региона.
        name_key = (normalize_name(record.name), record.region_code)
        possible = set(by_inn.get(record.inn, [])) | set(by_ogrn.get(record.ogrn, []))
        possible.update(by_name.get(name_key, []))
        indices = sorted(possible)
        decision = match_company(record, [unique[i] for i in indices])
        if decision.status == "matched":
            counts["identifier_matches"] += 1
            counts["duplicates"] += 1
            previous = unique[indices[decision.candidate_indices[0]]]
            # Excel — условная клиентская база; ФНС не отменяет этот статус.
            if record.client_status == "active":
                previous.client_status = "active"
            for field in ("employee_count", "municipality", "sme_category", "industry_code"):
                if getattr(previous, field) is None:
                    setattr(previous, field, getattr(record, field))
        else:
            counts["requires_review"] += decision.status == "requires_review"
            unique.append(replace(record))
            index = len(unique) - 1
            if is_valid_inn(record.inn):
                by_inn.setdefault(record.inn, []).append(index)
            if is_valid_ogrn(record.ogrn):
                by_ogrn.setdefault(record.ogrn, []).append(index)
            by_name.setdefault(name_key, []).append(index)
        identities[source_key] = len(unique) - 1
    return unique, counts
