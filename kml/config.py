from __future__ import annotations

import copy
import json
from dataclasses import dataclass
from pathlib import Path
from typing import Any


PROJECT_ROOT = Path(__file__).resolve().parent.parent
PRIVATE_DATA_PATH = PROJECT_ROOT / "kml_private_data.json"
PRIVATE_DATA_EXAMPLE_PATH = PROJECT_ROOT / "kml_private_data.example.json"
DEFAULT_PRIVATE_DATA: dict[str, Any] = {
    "config_schema_version": 1,
    "api_integrations": {
        "providers": {
            "mouser": {
                "enabled": False,
                "api_key": "",
            },
            "digikey": {
                "enabled": False,
                "client_id": "",
                "client_secret": "",
            },
        },
    },
    "gui": {
        "window_geometry": "",
        "last_provider": "mouser",
    },
    "lookup": {
        "last_mpn": "",
        "last_manufacturer": "",
    },
}
SUPPORTED_PROVIDER_NAMES = {"digikey", "mouser"}


@dataclass(frozen=True)
class ProviderStatus:
    name: str
    enabled: bool
    configured: bool


def ensure_private_data_file() -> None:
    if PRIVATE_DATA_PATH.exists():
        return
    save_private_data(copy.deepcopy(DEFAULT_PRIVATE_DATA))


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
        if name not in SUPPORTED_PROVIDER_NAMES:
            continue
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
            if name not in SUPPORTED_PROVIDER_NAMES:
                continue
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


def provider_secret(private_data: dict[str, Any], provider_name: str, key_name: str) -> str:
    api_integrations = private_data.get("api_integrations", {})
    if not isinstance(api_integrations, dict):
        return ""

    providers = api_integrations.get("providers", {})
    if isinstance(providers, dict):
        provider_settings = providers.get(provider_name, {})
        if isinstance(provider_settings, dict):
            value = provider_settings.get(key_name, "")
            if isinstance(value, str) and value.strip():
                return value.strip()

    legacy_keys = api_integrations.get("keys", {})
    if key_name == "api_key" and isinstance(legacy_keys, dict):
        value = legacy_keys.get(provider_name, "")
        if isinstance(value, str):
            return value.strip()

    return ""


def update_last_lookup(mpn: str, manufacturer: str, provider: str) -> None:
    private_data = load_private_data()
    updated = copy.deepcopy(private_data)
    updated.setdefault("lookup", {})
    updated["lookup"]["last_mpn"] = mpn
    updated["lookup"]["last_manufacturer"] = manufacturer
    updated.setdefault("gui", {})
    updated["gui"]["last_provider"] = provider
    save_private_data(updated)
