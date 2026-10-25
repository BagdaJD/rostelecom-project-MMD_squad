"""Согласование написаний, без геокодирования и вымышленных координат."""

import json
import re
from functools import lru_cache
from pathlib import Path

from ingestion.normalize import clean_text


@lru_cache
def directory() -> dict:
    return json.loads(Path(__file__).with_name("municipalities.json").read_text(encoding="utf-8"))


def municipality(district=None, city=None, *, region_code="61") -> str | None:
    district, city = clean_text(district), clean_text(city)
    if district:
        text = district.lower().replace("ё", "е").strip()
        text = re.sub(r"\s+(?:р-н|район|муниципальный район)$", "", text)
        return text.capitalize() + " район"
    if city:
        text = city.lower().replace("ё", "е")
        text = re.sub(r"^(?:г\.\s*|город\s+)", "", text).strip()
        if text.endswith(("район", "р-н")):
            return municipality(text, region_code=region_code)
        if region_code == "61":
            if text in directory()["city_districts"]:
                return directory()["city_districts"][text]
            if text not in directory()["urban_okrugs"]:
                return None
        return "г. " + text.capitalize()
    return None


def normalize_municipality(value: str | None, region_code="61") -> str | None:
    text = clean_text(value)
    if not text:
        return None
    if re.search(r"(?:район|р-н)$", text, flags=re.I):
        return municipality(text, region_code=region_code)
    return municipality(city=text, region_code=region_code)
