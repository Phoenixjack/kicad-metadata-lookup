from __future__ import annotations

import re
from html.parser import HTMLParser
from urllib.error import HTTPError, URLError
from urllib.parse import urlparse
from urllib.request import Request, urlopen

from .base import LookupError, ProviderPart


TIMEOUT_SECONDS = 20
BLOCKED_MARKERS = (
    "access to this page has been denied",
    "captcha",
    "blocked",
    "bot detection",
)


def scrape_product_page(url: str) -> ProviderPart:
    clean_url = url.strip()
    parsed_url = urlparse(clean_url)
    if parsed_url.scheme not in {"http", "https"} or not parsed_url.netloc:
        raise LookupError("ProductURL is not a valid HTTP or HTTPS URL.")

    html = _fetch_html(clean_url)
    fields = _extract_fields(html)
    if not fields:
        raise LookupError("No product attribute table was found on the page.")

    fields.setdefault("ProductURL", clean_url)
    fields.setdefault("ScrapeSource", parsed_url.netloc)
    return ProviderPart(
        provider="page_scrape",
        fields=fields,
        raw={"url": clean_url, "source": parsed_url.netloc},
        score=0,
    )


def parse_product_page_html(html: str, url: str = "") -> ProviderPart:
    fields = _extract_fields(html)
    if not fields:
        raise LookupError("No product attribute table was found in the supplied HTML.")
    if url:
        fields.setdefault("ProductURL", url)
        fields.setdefault("ScrapeSource", urlparse(url).netloc)
    return ProviderPart(provider="page_scrape", fields=fields, raw={"url": url}, score=0)


def _fetch_html(url: str) -> str:
    request = Request(
        url,
        headers={
            "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
            "Accept-Language": "en-US,en;q=0.9",
            "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) kicad-metadata-lookup/0.1",
        },
        method="GET",
    )
    try:
        with urlopen(request, timeout=TIMEOUT_SECONDS) as response:
            content_type = response.headers.get_content_charset() or "utf-8"
            html = response.read().decode(content_type, errors="replace")
    except HTTPError as exc:
        if exc.code in {401, 403}:
            raise LookupError("The product page blocked automated access.") from exc
        raise LookupError(f"Product page fetch failed with HTTP {exc.code}.") from exc
    except URLError as exc:
        raise LookupError(f"Product page fetch failed: {exc.reason}") from exc
    except TimeoutError as exc:
        raise LookupError("Product page fetch timed out.") from exc

    lower_html = html.casefold()
    if any(marker in lower_html for marker in BLOCKED_MARKERS):
        raise LookupError("The product page blocked automated access.")
    return html


def _extract_fields(html: str) -> dict[str, str]:
    parser = ProductPageParser()
    parser.feed(html)
    fields: dict[str, str] = {}

    for key, value in parser.field_pairs():
        normalized_key = _clean_label(key)
        normalized_value = _clean_value(value)
        if not normalized_key or not normalized_value:
            continue
        if _ignore_label(normalized_key):
            continue
        fields.setdefault(normalized_key, normalized_value)
        alias = _field_alias(normalized_key)
        if alias:
            fields.setdefault(alias, normalized_value)
    return fields


class ProductPageParser(HTMLParser):
    def __init__(self) -> None:
        super().__init__(convert_charrefs=True)
        self._in_cell = False
        self._cell_chunks: list[str] = []
        self._current_row: list[str] = []
        self.rows: list[list[str]] = []
        self._in_dt = False
        self._in_dd = False
        self._dt_chunks: list[str] = []
        self._dd_chunks: list[str] = []
        self.definition_pairs: list[tuple[str, str]] = []
        self._pending_dt = ""

    def handle_starttag(self, tag: str, attrs: list[tuple[str, str | None]]) -> None:
        if tag == "tr":
            self._current_row = []
        elif tag in {"td", "th"}:
            self._in_cell = True
            self._cell_chunks = []
        elif tag == "dt":
            self._in_dt = True
            self._dt_chunks = []
        elif tag == "dd":
            self._in_dd = True
            self._dd_chunks = []

    def handle_data(self, data: str) -> None:
        text = " ".join(data.split())
        if not text:
            return
        if self._in_cell:
            self._cell_chunks.append(text)
        if self._in_dt:
            self._dt_chunks.append(text)
        if self._in_dd:
            self._dd_chunks.append(text)

    def handle_endtag(self, tag: str) -> None:
        if tag in {"td", "th"} and self._in_cell:
            value = _clean_value(" ".join(self._cell_chunks))
            if value:
                self._current_row.append(value)
            self._in_cell = False
        elif tag == "tr":
            if self._current_row:
                self.rows.append(self._current_row)
            self._current_row = []
        elif tag == "dt" and self._in_dt:
            self._pending_dt = _clean_label(" ".join(self._dt_chunks))
            self._in_dt = False
        elif tag == "dd" and self._in_dd:
            value = _clean_value(" ".join(self._dd_chunks))
            if self._pending_dt and value:
                self.definition_pairs.append((self._pending_dt, value))
            self._pending_dt = ""
            self._in_dd = False

    def field_pairs(self) -> list[tuple[str, str]]:
        pairs: list[tuple[str, str]] = []
        for row in self.rows:
            if len(row) < 2:
                continue
            if len(row) == 2:
                pairs.append((row[0], row[1]))
                continue
            for index in range(0, len(row) - 1, 2):
                pairs.append((row[index], row[index + 1]))
        pairs.extend(self.definition_pairs)
        return pairs


def _clean_label(value: str) -> str:
    return _clean_value(value).rstrip(":")


def _clean_value(value: str) -> str:
    return re.sub(r"\s+", " ", value).strip()


def _ignore_label(label: str) -> bool:
    return label.casefold() in {"product attribute", "attribute value", "image", "qty", "quantity"}


def _field_alias(label: str) -> str:
    normalized = " ".join(label.casefold().replace("-", " ").split())
    aliases = {
        "manufacturer": "MANUFACTURER",
        "product category": "Category",
        "termination style": "TerminationStyle",
        "termination": "TerminationStyle",
        "mounting style": "MountingStyle",
        "mounting type": "MountingStyle",
        "contact plating": "ContactPlating",
        "contact finish": "ContactPlating",
        "contact material": "ContactMaterial",
        "number of positions": "PinCount",
        "number of pins": "PinCount",
        "number of contacts": "PinCount",
        "pin count": "PinCount",
        "pitch": "Pitch",
        "pitch mating": "PitchMating",
        "pitch termination": "PitchTermination",
        "orientation": "Orientation",
        "gender": "Gender",
        "series": "Series",
        "packaging": "Packaging",
        "color": "Color",
        "housing material": "HousingMaterial",
        "contact rating": "ContactRating",
        "current rating": "CurrentRating",
        "current rating amps": "CurrentRating",
        "voltage rated": "VoltageRating",
        "operating temperature": "OperatingTemperature",
        "maximum operating temperature": "MaxOperatingTemperature",
        "minimum operating temperature": "MinOperatingTemperature",
    }
    return aliases.get(normalized, "")
