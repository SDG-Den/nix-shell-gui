from __future__ import annotations

import json
import os
import subprocess
from pathlib import Path

from .search import Package, RUNTIME_PREFIX_RE

CONFIG_DIR = Path.home() / ".config" / "nix-shell-gui"
FAVOURITES_FILE = CONFIG_DIR / "favourites.json"
CONFIG_FILE = CONFIG_DIR / "config.json"
CATALOG_FILE = CONFIG_DIR / "catalog.json"
OFFLINE_FILE = CONFIG_DIR / "offline.json"
PATH_INFO_TIMEOUT = 60
BATCH_EVAL_TIMEOUT = 300

_store_paths: dict[str, str | None] = {}


def load_config() -> dict[str, object]:
    try:
        data = json.loads(CONFIG_FILE.read_text())
    except (FileNotFoundError, json.JSONDecodeError):
        return {}
    if not isinstance(data, dict):
        return {}
    return data


def load_favourites() -> set[str]:
    try:
        data = json.loads(FAVOURITES_FILE.read_text())
        return set(data)
    except (FileNotFoundError, json.JSONDecodeError):
        return set()


def save_favourites(favourites: set[str]) -> None:
    CONFIG_DIR.mkdir(parents=True, exist_ok=True)
    FAVOURITES_FILE.write_text(json.dumps(sorted(favourites), indent=2))


def _write_if_changed(path: Path, text: str) -> None:
    try:
        if path.read_text() == text:
            return
    except OSError:
        pass
    CONFIG_DIR.mkdir(parents=True, exist_ok=True)
    path.write_text(text)


def load_catalog_cache() -> list[Package] | None:
    try:
        data = json.loads(CATALOG_FILE.read_text())
    except (FileNotFoundError, json.JSONDecodeError):
        return None
    if not isinstance(data, list):
        return None
    packages: list[Package] = []
    for item in data:
        if not isinstance(item, dict) or "attr_path" not in item:
            return None
        packages.append(
            Package(
                item["attr_path"],
                item.get("name", item["attr_path"]),
                item.get("version", ""),
                item.get("description", ""),
            )
        )
    return packages


def save_catalog_cache(packages: list[Package]) -> None:
    CONFIG_DIR.mkdir(parents=True, exist_ok=True)
    data = [
        {
            "attr_path": package.attr_path,
            "name": package.name,
            "version": package.version,
            "description": package.description,
        }
        for package in packages
    ]
    _write_if_changed(CATALOG_FILE, json.dumps(data, indent=1))


def load_availability_cache() -> dict[str, bool]:
    try:
        data = json.loads(OFFLINE_FILE.read_text())
    except (FileNotFoundError, json.JSONDecodeError):
        return {}
    available = data.get("available") if isinstance(data, dict) else None
    if not isinstance(available, dict):
        return {}
    return {str(key): bool(value) for key, value in available.items()}


_availability: dict[str, bool] = load_availability_cache()


def save_availability(available: dict[str, bool]) -> None:
    data = {"available": {key: available[key] for key in sorted(available)}}
    _write_if_changed(OFFLINE_FILE, json.dumps(data, indent=1))


def is_available(attr_path: str) -> bool:
    return _availability.get(attr_path, False)


def store_entry_count() -> int:
    try:
        return len(os.listdir("/nix/store"))
    except OSError:
        return 0


def store_names() -> set[str]:
    try:
        entries = os.listdir("/nix/store")
    except OSError:
        return set()
    names: set[str] = set()
    for entry in entries:
        if not os.path.isdir(os.path.join("/nix/store", entry)):
            continue
        stripped = entry.split("-", 1)[1] if "-" in entry else entry
        if stripped:
            names.add(stripped)
    return names


def _name_candidates(base: str) -> set[str]:
    candidates: set[str] = set()
    for text in (base, RUNTIME_PREFIX_RE.sub("", base)):
        parts = text.split("-")
        while parts and parts[-1][:1].isdigit():
            parts.pop()
        if parts:
            candidates.add("-".join(parts))
    return candidates


def compute_availability(catalog: list[Package]) -> dict[str, bool]:
    name_set = {package.name for package in catalog}
    available_names: set[str] = set()
    for base in store_names():
        available_names.update(_name_candidates(base) & name_set)
    return {package.attr_path: package.name in available_names for package in catalog}


def store_path(nix_bin: str, attr_path: str) -> str | None:
    if attr_path in _store_paths:
        return _store_paths[attr_path]
    path = _query_store_path(nix_bin, attr_path)
    _store_paths[attr_path] = path
    return path


def store_paths(nix_bin: str, attr_paths: list[str]) -> dict[str, str | None]:
    unresolved = [attr for attr in attr_paths if attr not in _store_paths]
    if unresolved:
        for attr, path in _query_store_paths(nix_bin, unresolved).items():
            _store_paths[attr] = path
    return {attr: _store_paths.get(attr) for attr in attr_paths}


def _query_store_paths(nix_bin: str, attr_paths: list[str]) -> dict[str, str | None]:
    from .classify import nix_system

    attrs = " ".join(json.dumps(attr) for attr in attr_paths)
    apply_expr = (
        "d: let walk = n: "
        "  let segs = builtins.filter builtins.isString (builtins.split \"\\\\.\" n); "
        "      go = l: a: "
        "        if l == [] then a "
        "        else if builtins.isAttrs a && builtins.hasAttr (builtins.head l) a "
        "          then go (builtins.tail l) (builtins.getAttr (builtins.head l) a) "
        "          else { }; "
        "      got = go segs d; "
        "  in if got ? outPath "
        "       then let r = builtins.tryEval got.outPath; "
        "         in { success = r.success; value = if r.success then r.value else null; } "
        "       else { success = false; value = null; }; "
        "in builtins.map (n: { name = n; inherit (walk n) success value; }) "
        f"[ {attrs} ]"
    )
    proc = subprocess.run(
        [
            nix_bin,
            "eval",
            "--json",
            f"nixpkgs#legacyPackages.{nix_system()}",
            "--apply",
            apply_expr,
        ],
        capture_output=True,
        text=True,
        timeout=BATCH_EVAL_TIMEOUT,
    )
    if proc.returncode != 0:
        return {}
    try:
        data = json.loads(proc.stdout)
    except json.JSONDecodeError:
        return {}
    out_paths = {item["name"]: item["value"] for item in data if item.get("success")}
    existing = _existing_store_paths(nix_bin, list(out_paths.values()))
    return {
        attr: (path if path in existing else None)
        for attr, path in out_paths.items()
    }


def _existing_store_paths(nix_bin: str, paths: list[str]) -> set[str]:
    if not paths:
        return set()
    proc = subprocess.run(
        [nix_bin, "path-info", "--option", "substitute", "false", "--json", *paths],
        capture_output=True,
        text=True,
        timeout=PATH_INFO_TIMEOUT,
    )
    if proc.returncode != 0:
        return set()
    try:
        data = json.loads(proc.stdout)
    except json.JSONDecodeError:
        return set()
    return {path for path in paths if data.get(path) is not None}


def _query_store_path(nix_bin: str, attr_path: str) -> str | None:
    try:
        proc = subprocess.run(
            [nix_bin, "path-info", "--json", f"nixpkgs#{attr_path}"],
            capture_output=True,
            text=True,
            timeout=PATH_INFO_TIMEOUT,
        )
    except subprocess.TimeoutExpired:
        return None
    if proc.returncode != 0:
        return None
    try:
        data = json.loads(proc.stdout)
    except json.JSONDecodeError:
        return None
    if not data:
        return None
    return next(iter(data))