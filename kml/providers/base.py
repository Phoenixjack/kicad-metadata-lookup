from __future__ import annotations

from dataclasses import dataclass, field


class LookupError(Exception):
    """Raised when a provider lookup cannot return usable results."""


@dataclass(frozen=True)
class ProviderPart:
    provider: str
    fields: dict[str, str]
    raw: dict
    score: int = 0


@dataclass(frozen=True)
class LookupResult:
    provider: str
    query: str
    parts: list[ProviderPart] = field(default_factory=list)
