"""App name to package mapping loader.

Data is stored in app_name_to_package.json so it can be iterated without
touching code.
"""

from __future__ import annotations

import json
from pathlib import Path


DATA_FILE = Path(__file__).with_name("app_name_to_package.json")


def normalize_package_name(name: str) -> str:
    """Normalize an app name for robust matching."""
    return name.lower().strip().replace(" ", "").replace("-", "")


def load_mapping_entries(data_file: Path = DATA_FILE) -> list[dict[str, object]]:
    """Load mapping entries from JSON data file."""
    if not data_file.exists():
        raise FileNotFoundError(f"Mapping data file not found: {data_file}")

    with data_file.open("r", encoding="utf-8") as f:
        payload = json.load(f)

    entries = payload.get("entries")
    if not isinstance(entries, list):
        raise ValueError(f"Invalid mapping data format in {data_file}: missing list 'entries'")
    return entries


def build_package_dicts(entries: list[dict[str, object]]):
    """Build package->aliases and alias->packages lookup dictionaries."""
    packages_name_dict: dict[str, list[str]] = {}
    name_package_dict: dict[str, list[str]] = {}

    for entry in entries:
        if not isinstance(entry, dict):
            continue
        package_id = str(entry.get("package_id", "")).strip()
        aliases_raw = entry.get("aliases", [])
        if not package_id:
            continue
        if not isinstance(aliases_raw, list):
            continue

        # Preserve order while removing duplicates after normalization.
        aliases: list[str] = []
        seen_aliases: set[str] = set()
        for alias in aliases_raw:
            normalized = normalize_package_name(str(alias))
            if not normalized or normalized in seen_aliases:
                continue
            seen_aliases.add(normalized)
            aliases.append(normalized)

        if package_id in packages_name_dict:
            merged = packages_name_dict[package_id] + aliases
            merged_unique: list[str] = []
            seen: set[str] = set()
            for name in merged:
                if name in seen:
                    continue
                seen.add(name)
                merged_unique.append(name)
            packages_name_dict[package_id] = merged_unique
        else:
            packages_name_dict[package_id] = aliases

    for package_id, aliases in packages_name_dict.items():
        for alias in aliases:
            if alias not in name_package_dict:
                name_package_dict[alias] = [package_id]
            elif package_id not in name_package_dict[alias]:
                name_package_dict[alias].append(package_id)

    return packages_name_dict, name_package_dict


def resolve_package_ids(app_name: str) -> list[str]:
    """Resolve installed package ids from a commercial app name or alias."""
    normalized_name = normalize_package_name(app_name)
    if not normalized_name:
        return []
    return NAME_PACKAGE_DICT.get(normalized_name, [])


def resolve_package_id(app_name: str) -> str:
    """Resolve the first package id for a commercial app name or alias."""
    package_ids = resolve_package_ids(app_name)
    return package_ids[0] if package_ids else ""


def resolve_package_ids_from_instruction(instruction: str) -> tuple[str, list[str]]:
    """Resolve package ids by matching known aliases directly in instruction text.

    Returns:
        (matched_alias, package_ids). If no alias is matched, returns ("", []).
    """
    normalized_instruction = normalize_package_name(instruction)
    if not normalized_instruction:
        return "", []

    matched_alias = ""
    # Prefer the longest alias to avoid generic/short alias collisions.
    for alias in sorted(NAME_PACKAGE_DICT.keys(), key=len, reverse=True):
        if alias and alias in normalized_instruction:
            matched_alias = alias
            break

    if not matched_alias:
        return "", []
    return matched_alias, NAME_PACKAGE_DICT.get(matched_alias, [])


MAPPING_ENTRIES = load_mapping_entries()
PACKAGES_NAME_DICT, NAME_PACKAGE_DICT = build_package_dicts(MAPPING_ENTRIES)
