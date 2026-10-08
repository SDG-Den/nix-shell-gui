import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

from nix_shell_gui.search import (
    _attr_path,
    run_search,
    parse_search_json,
    filter_catalog,
    _dedupe,
    Package,
)


def test_colon_key_parses_attr_path():
    assert _attr_path("nixpkgs:firefox") == "firefox"


def test_hash_key_parses_attr_path():
    assert _attr_path("nixpkgs#python3Packages.requests") == "python3Packages.requests"


def test_gt_key_parses_attr_path():
    assert _attr_path("nixpkgs>gimp") == "gimp"


def test_legacy_key_strips_system():
    assert _attr_path("legacyPackages.x86_64-linux.htop") == "htop"


def test_legacy_key_keeps_nested_attr():
    assert (
        _attr_path("legacyPackages.aarch64-linux.python3Packages.requests")
        == "python3Packages.requests"
    )


def test_parse_uses_pname_and_sorts_and_limits():
    data = {
        "nixpkgs:firefox": {
            "pname": "firefox",
            "version": "133.0.3",
            "description": "browser",
        },
        "nixpkgs:htop": {
            "pname": "htop",
            "version": "3.3.0",
            "description": "process viewer",
        },
        "nixpkgs:curl": {
            "name": "curl",
            "version": "8.9.0",
            "description": "transfer tool",
        },
    }
    results = parse_search_json(json.dumps(data), limit=2)
    assert [package.attr_path for package in results] == ["curl", "firefox"]
    assert results[0].name == "curl"
    assert results[1].version == "133.0.3"


def test_parse_falls_back_to_attr_path_as_name():
    data = {
        "nixpkgs:mystery": {"description": "no name field"},
    }
    results = parse_search_json(json.dumps(data))
    assert results[0].name == "mystery"
    assert results[0].description == "no name field"


def test_empty_query_runs_nothing():
    assert run_search("anything", "   ") == []


def test_parse_with_no_limit_returns_all():
    data = {
        "nixpkgs:a": {"pname": "a"},
        "nixpkgs:b": {"pname": "b"},
    }
    assert len(parse_search_json(json.dumps(data), limit=None)) == 2


def test_filter_matches_name_attr_and_description_case_insensitive():
    catalog = [
        Package("Firefox", "firefox", "1.0", "web browser"),
        Package("htop", "htop", "2.0", "process viewer"),
        Package("python3Packages.requests", "requests", "3.0", "HTTP library"),
    ]
    assert [p.attr_path for p in filter_catalog(catalog, "FIREFOX")] == ["Firefox"]
    assert [p.attr_path for p in filter_catalog(catalog, "process")] == ["htop"]
    assert [p.attr_path for p in filter_catalog(catalog, "requests")] == [
        "python3Packages.requests"
    ]


def test_filter_empty_query_returns_all():
    catalog = [
        Package("firefox", "firefox", "1.0", ""),
        Package("htop", "htop", "2.0", ""),
    ]
    assert len(filter_catalog(catalog, "   ")) == 2


def test_dedupe_keeps_first_of_duplicate_name_and_version():
    catalog = [
        Package("firefox", "firefox", "138.0", ""),
        Package("librewolf", "firefox", "138.0", ""),
        Package("foo", "foo", "1.0", ""),
        Package("python312Packages.foo", "foo", "1.0", ""),
    ]
    result = _dedupe(catalog)
    assert [package.attr_path for package in result] == ["firefox", "foo"]


def test_dedupe_collapses_runtime_scoped_python_duplicates():
    catalog = [
        Package("python313Packages.adb-shell", "python3.13-adb-shell", "0.4.4", ""),
        Package("python314Packages.adb-shell", "python3.14-adb-shell", "0.4.4", ""),
        Package("python313Packages.adb-enhanced", "python3.13-adb-enhanced", "2.8.0", ""),
    ]
    result = _dedupe(catalog)
    assert [package.attr_path for package in result] == [
        "python313Packages.adb-shell",
        "python313Packages.adb-enhanced",
    ]


def test_version_like_pname_falls_back_to_attr_basename():
    data = {
        "nixpkgs:linuxKernel.packages.linux_6_12.ajantv2": {
            "pname": "17.5.0",
            "version": "0.23.4",
        }
    }
    result = parse_search_json(json.dumps(data))
    assert result[0].name == "ajantv2"