from __future__ import annotations

import copy
import json
import shutil
from dataclasses import dataclass
from pathlib import Path
from typing import Any


PROJECT_ROOT = Path(__file__).resolve().parent.parent
PRIVATE_DATA_PATH = PROJECT_ROOT / "kml_private_data.json"
PRIVATE_DATA_EXAMPLE_PATH = PROJECT_ROOT / "kml_private_data.example.json"


@dataclass(frozen=True)
class ProviderStatus:
    name: str
    enabled: bool
    configured: bool


def ensure_private_data_file() -> None:
    if PRIVATE_DATA_PATH.exists():
        return
    shutil.copy2(PRIVATE_DATA_EXAMPLE_PATH, PRIVATE_DATA_PATH)


def load_private_data() -> dict[str, Any]:
    ensure_private_data_file()
    with PRIVATE_DATA_PATH.open("r", encoding="utf-8") as file:
        data = json.load(file)
    if not isinstance(data, dict):
        raise ValueError(f"{PRIVATE_DATA_PATH.name} must contain a JSON object.")
    return data


def save_private_data(data: dict[str, Any]) -> None:
    with PRIVATE_DATA_PATH.open("w", encoding="utf-8") as file:
        json.dump(data, file, indent=2)
        file.write("\n")


def provider_statuses(private_data: dict[str, Any]) -> list[ProviderStatus]:
    api_integrations = private_data.get("api_integrations", {})
    if not isinstance(api_integrations, dict):
        return []

    providers = api_integrations.get("providers", {})
    if not isinstance(providers, dict):
        providers = {}

    statuses_by_name: dict[str, ProviderStatus] = {}
    for name, settings in sorted(providers.items()):
        if not isinstance(settings, dict):
            continue
        secret_values = [
            value
            for key, value in settings.items()
            if key != "enabled" and isinstance(value, str)
        ]
        statuses_by_name[name] = (
            ProviderStatus(
                name=name,
                enabled=bool(settings.get("enabled", False)),
                configured=any(value.strip() for value in secret_values),
            )
        )

    legacy_keys = api_integrations.get("keys", {})
    if isinstance(legacy_keys, dict):
        for name, value in sorted(legacy_keys.items()):
            if name in statuses_by_name:
                existing = statuses_by_name[name]
                statuses_by_name[name] = ProviderStatus(
                    name=name,
                    enabled=existing.enabled,
                    configured=existing.configured or bool(str(value).strip()),
                )
                continue
            statuses_by_name[name] = ProviderStatus(
                name=name,
                enabled=True,
                configured=bool(str(value).strip()),
            )

    return [statuses_by_name[name] for name in sorted(statuses_by_name)]


def update_last_lookup(mpn: str, manufacturer: str, provider: str) -> None:
    private_data = load_private_data()
    updated = copy.deepcopy(private_data)
    updated.setdefault("lookup", {})
    updated["lookup"]["last_mpn"] = mpn
    updated["lookup"]["last_manufacturer"] = manufacturer
    updated.setdefault("gui", {})
    updated["gui"]["last_provider"] = provider
    save_private_data(updated)
