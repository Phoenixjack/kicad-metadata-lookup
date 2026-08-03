from __future__ import annotations

import json
from difflib import SequenceMatcher
from urllib.error import HTTPError, URLError
from urllib.parse import urlencode
from urllib.request import Request, urlopen

from .base import LookupError, LookupResult, ProviderPart


SEARCH_URL = "https://api.mouser.com/api/v1/search/partnumber"
TIMEOUT_SECONDS = 20


def lookup_part_number(api_key: str, mpn: str, manufacturer: str = "") -> LookupResult:
    if not api_key.strip():
        raise LookupError("Mouser API key is not configured.")
    if len(mpn.strip()) < 3:
        raise LookupError("Mouser part-number lookup requires at least 3 characters.")

    payload = {
        "SearchByPartRequest": {
            "mouserPartNumber": mpn.strip(),
            "partSearchOptions": "Exact",
        }
    }
    data = json.dumps(payload).encode("utf-8")
    url = f"{SEARCH_URL}?{urlencode({'apiKey': api_key.strip()})}"
    request = Request(
        url,
        data=data,
        headers={
            "Accept": "application/json",
            "Content-Type": "application/json",
            "User-Agent": "kicad-metadata-lookup/0.1",
        },
        method="POST",
    )

    try:
        with urlopen(request, timeout=TIMEOUT_SECONDS) as response:
            response_data = json.loads(response.read().decode("utf-8"))
    except HTTPError as exc:
        raise LookupError(f"Mouser lookup failed with HTTP {exc.code}.") from exc
    except URLError as exc:
        raise LookupError(f"Mouser lookup failed: {exc.reason}") from exc
    except TimeoutError as exc:
        raise LookupError("Mouser lookup timed out.") from exc
    except json.JSONDecodeError as exc:
        raise LookupError("Mouser returned a response that was not valid JSON.") from exc

    errors = response_data.get("Errors") or []
    if errors:
        messages = [
            str(error.get("Message", "")).strip()
            for error in errors
            if isinstance(error, dict) and str(error.get("Message", "")).strip()
        ]
        raise LookupError("; ".join(messages) or "Mouser returned an error.")

    search_results = response_data.get("SearchResults") or {}
    raw_parts = search_results.get("Parts") or []
    if not isinstance(raw_parts, list):
        raw_parts = []

    parts = [
        _normalize_part(part, mpn.strip(), manufacturer.strip())
        for part in raw_parts
        if isinstance(part, dict)
    ]
    parts.sort(key=lambda part: part.score, reverse=True)
    return LookupResult(provider="mouser", query=mpn.strip(), parts=parts)


def _normalize_part(part: dict, mpn: str, manufacturer: str) -> ProviderPart:
    fields = {
        "Value": _value(part, "ManufacturerPartNumber"),
        "MANUFACTURER": _value(part, "Manufacturer") or _value(part, "ActualMfrName"),
        "Description": _value(part, "Description"),
        "Datasheet": _value(part, "DataSheetUrl"),
        "ProductURL": _value(part, "ProductDetailUrl"),
        "MouserPartNumber": _value(part, "MouserPartNumber"),
        "Category": _value(part, "Category") or _value(part, "MouserProductCategory"),
        "LifecycleStatus": _value(part, "LifecycleStatus"),
        "RoHS": _value(part, "ROHSStatus") or _value(part, "RohsStatus"),
        "Availability": _value(part, "Availability"),
        "AvailabilityInStock": _value(part, "AvailabilityInStock"),
        "LeadTime": _value(part, "LeadTime"),
        "MinOrderQty": _value(part, "Min"),
        "OrderMultiple": _value(part, "Mult"),
    }

    _add_product_attributes(fields, part)
    _drop_empty(fields)
    return ProviderPart(
        provider="mouser",
        fields=fields,
        raw=part,
        score=_score_part(part, mpn, manufacturer),
    )


def _add_product_attributes(fields: dict[str, str], part: dict) -> None:
    attributes = part.get("ProductAttributes") or []
    if not isinstance(attributes, list):
        return
    for attribute in attributes:
        if not isinstance(attribute, dict):
            continue
        name = _value(attribute, "AttributeName")
        value = _value(attribute, "AttributeValue")
        if not name or not value:
            continue
        normalized_name = f"Attribute: {name}"
        fields.setdefault(normalized_name, value)


def _score_part(part: dict, mpn: str, manufacturer: str) -> int:
    score = 0
    returned_mpn = _value(part, "ManufacturerPartNumber")
    returned_manufacturer = _value(part, "Manufacturer") or _value(part, "ActualMfrName")

    if returned_mpn.casefold() == mpn.casefold():
        score += 100
    else:
        score += int(SequenceMatcher(None, returned_mpn.casefold(), mpn.casefold()).ratio() * 40)

    if manufacturer:
        if returned_manufacturer.casefold() == manufacturer.casefold():
            score += 50
        else:
            score += int(
                SequenceMatcher(
                    None,
                    returned_manufacturer.casefold(),
                    manufacturer.casefold(),
                ).ratio()
                * 20
            )

    if _value(part, "LifecycleStatus").casefold() == "active":
        score += 5
    if _value(part, "AvailabilityInStock"):
        score += 3
    return score


def _value(mapping: dict, key: str) -> str:
    value = mapping.get(key, "")
    if value is None:
        return ""
    return str(value).strip()


def _drop_empty(fields: dict[str, str]) -> None:
    for key in list(fields):
        if not fields[key]:
            del fields[key]
