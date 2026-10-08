from __future__ import annotations

import json
import re
import subprocess
from dataclasses import dataclass

SYSTEM_RE = re.compile(
    r"(x86_64|aarch64|i686|armv7l|riscv64|powerpc64le)-(linux|darwin|freebsd|netbsd)"
)
VERSION_NAME_RE = re.compile(r"^\d+(\.\d+)+$")
RUNTIME_PREFIX_RE = re.compile(
    r"^(python\d+(\.\d+)?|lua\d+(\.\d+)?|luajit\d*|ocaml\d+(\.\d+){2}|node\d*|perl\d+\.\d+|ruby\d*|php\d+)-"
)
SEARCH_TIMEOUT = 180


@dataclass
class Package:
    attr_path: str
    name: str
    version: str
    description: str


class SearchError(RuntimeError):
    pass


def run_search(nix_bin: str, query: str, limit: int = 200) -> list[Package]:
    query = query.strip()
    if not query:
        return []
    proc = subprocess.run(
        [nix_bin, "search", "nixpkgs", query, "--json"],
        capture_output=True,
        text=True,
        timeout=SEARCH_TIMEOUT,
    )
    if proc.returncode != 0:
        raise SearchError(proc.stderr.strip() or "nix search failed")
    return parse_search_json(proc.stdout, limit)


def parse_search_json(raw: str, limit: int | None = 200) -> list[Package]:
    data = json.loads(raw)
    results = []
    for key, meta in data.items():
        attr_path = _attr_path(key)
        name = meta.get("pname") or meta.get("name") or attr_path
        if VERSION_NAME_RE.match(name):
            name = attr_path.rsplit(".", 1)[-1]
        results.append(
            Package(
                attr_path=attr_path,
                name=name,
                version=meta.get("version", ""),
                description=meta.get("description", ""),
            )
        )
    results.sort(key=lambda package: package.name.lower())
    if limit is not None:
        results = results[:limit]
    return results


def load_catalog(nix_bin: str) -> list[Package]:
    proc = subprocess.run(
        [nix_bin, "search", "nixpkgs", "", "--json"],
        capture_output=True,
        text=True,
        timeout=SEARCH_TIMEOUT,
    )
    if proc.returncode != 0:
        raise SearchError(proc.stderr.strip() or "nix search failed")
    return _dedupe(parse_search_json(proc.stdout, limit=None))


def _dedupe(packages: list[Package]) -> list[Package]:
    seen: set[tuple[str, str]] = set()
    unique: list[Package] = []
    for package in packages:
        key = (RUNTIME_PREFIX_RE.sub("", package.name, count=1), package.version)
        if key in seen:
            continue
        seen.add(key)
        unique.append(package)
    return unique


def filter_catalog(catalog: list[Package], query: str) -> list[Package]:
    query = query.strip().lower()
    if not query:
        return list(catalog)
    return [
        package
        for package in catalog
        if query in package.attr_path.lower()
        or query in package.name.lower()
        or query in (package.description or "").lower()
    ]


def _attr_path(key: str) -> str:
    for separator in "#:>":
        key = key.split(separator)[-1]
    parts = [part for part in key.split(".") if part]
    if parts and parts[0] in ("legacyPackages", "packages"):
        parts = parts[1:]
    if parts and SYSTEM_RE.match(parts[0]):
        parts = parts[1:]
    return ".".join(parts)