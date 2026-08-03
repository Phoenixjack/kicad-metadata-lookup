from __future__ import annotations

import json
from difflib import SequenceMatcher
from urllib.error import HTTPError, URLError
from urllib.parse import quote, urlencode
from urllib.request import Request, urlopen

from .base import LookupError, LookupResult, ProviderPart


TOKEN_URL = "https://api.digikey.com/v1/oauth2/token"
KEYWORD_SEARCH_URL = "https://api.digikey.com/products/v4/search/keyword"
PRODUCT_DETAILS_URL_TEMPLATE = "https://api.digikey.com/products/v4/search/{product_number}/productdetails"
TIMEOUT_SECONDS = 20
DEFAULT_TEST_QUERY = "KML-CREDENTIAL-TEST-NO-RESULTS"


def test_credentials(client_id: str, client_secret: str, query: str = "") -> LookupResult:
    token = _access_token(client_id, client_secret)
    return _keyword_search(client_id, token, query.strip() or DEFAULT_TEST_QUERY)


def lookup_part_number(client_id: str, client_secret: str, mpn: str, manufacturer: str = "") -> LookupResult:
    if len(mpn.strip()) < 2:
        raise LookupError("DigiKey part-number lookup requires at least 2 characters.")

    token = _access_token(client_id, client_secret)
    result = _product_details(client_id, token, mpn.strip(), manufacturer.strip())
    if result.parts:
        return result
    return _keyword_search(client_id, token, mpn.strip(), manufacturer.strip())


def _access_token(client_id: str, client_secret: str) -> str:
    if not client_id.strip() or not client_secret.strip():
        raise LookupError("DigiKey Client ID and Client Secret are required.")

    data = urlencode(
        {
            "client_id": client_id.strip(),
            "client_secret": client_secret.strip(),
            "grant_type": "client_credentials",
        }
    ).encode("utf-8")
    request = Request(
        TOKEN_URL,
        data=data,
        headers={
            "Accept": "application/json",
            "Content-Type": "application/x-www-form-urlencoded",
            "User-Agent": "kicad-metadata-lookup/0.1",
        },
        method="POST",
    )
    response_data = _send_json_request(request, "DigiKey token request")
    access_token = str(response_data.get("access_token", "")).strip()
    if not access_token:
        raise LookupError("DigiKey did not return an access token.")
    return access_token


def _product_details(client_id: str, token: str, mpn: str, manufacturer: str = "") -> LookupResult:
    url = PRODUCT_DETAILS_URL_TEMPLATE.format(product_number=quote(mpn, safe=""))
    request = Request(url, headers=_api_headers(client_id, token), method="GET")
    try:
        response_data = _send_json_request(request, "DigiKey product details")
    except LookupError as exc:
        message = str(exc)
        if "HTTP 404" in message:
            return LookupResult(provider="digikey", query=mpn, parts=[])
        raise

    product = response_data.get("Product")
    parts = []
    if isinstance(product, dict):
        parts.append(_normalize_product(product, mpn, manufacturer, response_data))
    return LookupResult(provider="digikey", query=mpn, parts=parts)


def _keyword_search(client_id: str, token: str, query: str, manufacturer: str = "") -> LookupResult:
    payload = {
        "Keywords": query.strip() or DEFAULT_TEST_QUERY,
        "Limit": 10,
        "Offset": 0,
    }
    request = Request(
        KEYWORD_SEARCH_URL,
        data=json.dumps(payload).encode("utf-8"),
        headers={
            **_api_headers(client_id, token),
            "Content-Type": "application/json",
        },
        method="POST",
    )
    response_data = _send_json_request(request, "DigiKey keyword search")
    products = _combined_products(response_data)
    parts = [_normalize_product(product, query, manufacturer, response_data) for product in products]
    parts.sort(key=lambda part: part.score, reverse=True)
    return LookupResult(provider="digikey", query=query, parts=parts)


def _api_headers(client_id: str, token: str) -> dict[str, str]:
    return {
        "Accept": "application/json",
        "Authorization": f"Bearer {token}",
        "User-Agent": "kicad-metadata-lookup/0.1",
        "X-DIGIKEY-Client-Id": client_id.strip(),
        "X-DIGIKEY-Locale-Site": "US",
        "X-DIGIKEY-Locale-Language": "en",
        "X-DIGIKEY-Locale-Currency": "USD",
        "X-DIGIKEY-Locale-ShipToCountry": "US",
    }


def _send_json_request(request: Request, operation_name: str) -> dict:
    try:
        with urlopen(request, timeout=TIMEOUT_SECONDS) as response:
            return json.loads(response.read().decode("utf-8"))
    except HTTPError as exc:
        detail = _http_error_detail(exc)
        raise LookupError(f"{operation_name} failed with HTTP {exc.code}{detail}.") from exc
    except URLError as exc:
        raise LookupError(f"{operation_name} failed: {exc.reason}") from exc
    except TimeoutError as exc:
        raise LookupError(f"{operation_name} timed out.") from exc
    except json.JSONDecodeError as exc:
        raise LookupError(f"{operation_name} returned a response that was not valid JSON.") from exc


def _http_error_detail(exc: HTTPError) -> str:
    try:
        payload = exc.read().decode("utf-8", errors="replace")
    except Exception:
        return ""
    if not payload:
        return ""
    try:
        data = json.loads(payload)
    except json.JSONDecodeError:
        return f": {payload[:200]}"
    for key in ("ErrorMessage", "ErrorDetails", "title", "detail", "message"):
        value = data.get(key)
        if value:
            return f": {value}"
    return ""


def _combined_products(response_data: dict) -> list[dict]:
    products: list[dict] = []
    seen: set[str] = set()
    for section in ("ExactMatches", "Products"):
        values = response_data.get(section) or []
        if not isinstance(values, list):
            continue
        for product in values:
            if not isinstance(product, dict):
                continue
            key = _value(product, "ManufacturerProductNumber") or _value(product, "ProductUrl")
            if key and key in seen:
                continue
            if key:
                seen.add(key)
            products.append(product)
    return products


def _normalize_product(product: dict, query: str, manufacturer: str, response_data: dict) -> ProviderPart:
    description = _mapping(product.get("Description"))
    manufacturer_data = _mapping(product.get("Manufacturer"))
    category = _mapping(product.get("Category"))
    series = _mapping(product.get("Series"))
    status = _mapping(product.get("ProductStatus"))
    classifications = _mapping(product.get("Classifications"))
    variation = _first_variation(product)
    package_type = _mapping(variation.get("PackageType"))

    fields = {
        "Value": _value(product, "ManufacturerProductNumber"),
        "MANUFACTURER": _value(manufacturer_data, "Name"),
        "Description": _value(description, "DetailedDescription") or _value(description, "ProductDescription"),
        "Datasheet": _value(product, "DatasheetUrl"),
        "ProductURL": _value(product, "ProductUrl"),
        "ImageURL": _value(product, "PhotoUrl"),
        "DigiKeyPartNumber": _value(variation, "DigiKeyProductNumber"),
        "Category": _value(category, "Name"),
        "Series": _value(series, "Name"),
        "LifecycleStatus": _value(status, "Status"),
        "Availability": _value(product, "QuantityAvailable"),
        "UnitPrice": _value(product, "UnitPrice"),
        "LeadTime": _value(product, "ManufacturerLeadWeeks"),
        "Package": _value(package_type, "Name"),
        "Packaging": _value(package_type, "Name"),
        "MinOrderQty": _value(variation, "MinimumOrderQuantity"),
        "StandardPackage": _value(variation, "StandardPackage"),
        "RoHS": _value(classifications, "RohsStatus"),
        "REACH": _value(classifications, "ReachStatus"),
        "MSL": _value(classifications, "MoistureSensitivityLevel"),
        "ECCN": _value(classifications, "ExportControlClassNumber"),
        "HTSUS": _value(classifications, "HtsusCode"),
    }

    _add_parameters(fields, product)
    _drop_empty(fields)
    return ProviderPart(
        provider="digikey",
        fields=fields,
        raw=product,
        score=_score_product(product, query, manufacturer, response_data),
    )


def _add_parameters(fields: dict[str, str], product: dict) -> None:
    parameters = product.get("Parameters") or []
    if not isinstance(parameters, list):
        return
    for parameter in parameters:
        if not isinstance(parameter, dict):
            continue
        name = _value(parameter, "ParameterText")
        value = _value(parameter, "ValueText")
        if not name or not value:
            continue
        fields.setdefault(name, value)
        alias = _parameter_alias(name)
        if alias:
            fields.setdefault(alias, value)


def _parameter_alias(name: str) -> str:
    normalized = " ".join(name.casefold().replace("-", " ").split())
    aliases = {
        "number of positions": "PinCount",
        "number of pins": "PinCount",
        "number of contacts": "PinCount",
        "pitch": "Pitch",
        "pitch mating": "PitchMating",
        "pitch termination": "PitchTermination",
        "mounting type": "MountingStyle",
        "mounting feature": "MountingFeature",
        "connector type": "ConnectorType",
        "contact type": "ContactType",
        "contact finish": "ContactPlating",
        "contact material": "ContactMaterial",
        "termination": "TerminationStyle",
        "termination style": "TerminationStyle",
    }
    return aliases.get(normalized, "")


def _score_product(product: dict, query: str, manufacturer: str, response_data: dict) -> int:
    score = 0
    returned_mpn = _value(product, "ManufacturerProductNumber")
    returned_manufacturer = _value(_mapping(product.get("Manufacturer")), "Name")

    if returned_mpn.casefold() == query.casefold():
        score += 100
    else:
        score += int(SequenceMatcher(None, returned_mpn.casefold(), query.casefold()).ratio() * 40)

    if manufacturer:
        if returned_manufacturer.casefold() == manufacturer.casefold():
            score += 50
        else:
            score += int(
                SequenceMatcher(None, returned_manufacturer.casefold(), manufacturer.casefold()).ratio() * 20
            )

    if product in response_data.get("ExactMatches", []):
        score += 25
    return score


def _first_variation(product: dict) -> dict:
    variations = product.get("ProductVariations") or []
    if isinstance(variations, list):
        for variation in variations:
            if isinstance(variation, dict):
                return variation
    return {}


def _mapping(value: object) -> dict:
    return value if isinstance(value, dict) else {}


def _value(mapping: dict, key: str) -> str:
    value = mapping.get(key, "")
    if value is None:
        return ""
    return str(value).strip()


def _drop_empty(fields: dict[str, str]) -> None:
    for key in list(fields):
        if not fields[key]:
            del fields[key]
