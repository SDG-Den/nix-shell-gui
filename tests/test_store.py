from nix_shell_gui import store
from nix_shell_gui.search import Package


def setup_function() -> None:
    store._store_paths.clear()
    store._availability = {}


def test_store_paths_queries_only_unresolved_attrs(monkeypatch) -> None:
    queried: list[list[str]] = []
    monkeypatch.setattr(
        store, "_query_store_paths", lambda nix_bin, attrs: queried.append(attrs) or {a: None for a in attrs}
    )
    store._store_paths["firefox"] = "/nix/store/placeholder-firefox"
    result = store.store_paths("nix", ["firefox", "htop", "curl"])
    assert queried == [["htop", "curl"]]
    assert result == {
        "firefox": "/nix/store/placeholder-firefox",
        "htop": None,
        "curl": None,
    }


def test_store_paths_caches_between_calls(monkeypatch) -> None:
    queried: list[list[str]] = []
    monkeypatch.setattr(
        store, "_query_store_paths", lambda nix_bin, attrs: queried.append(attrs) or {a: None for a in attrs}
    )
    first = store.store_paths("nix", ["one", "two"])
    second = store.store_paths("nix", ["one", "two"])
    assert queried == [["one", "two"]]
    assert first == second == {"one": None, "two": None}


def test_store_paths_tolerates_partial_results(monkeypatch) -> None:
    monkeypatch.setattr(store, "_query_store_paths", lambda nix_bin, attrs: {"one": "/nix/store/one"})
    result = store.store_paths("nix", ["one", "two", "three"])
    assert result == {
        "one": "/nix/store/one",
        "two": None,
        "three": None,
    }


def test_catalog_cache_roundtrip(tmp_path, monkeypatch) -> None:
    monkeypatch.setattr(store, "CATALOG_FILE", tmp_path / "catalog.json")
    catalog = [
        Package("firefox", "firefox", "157.0", "browser"),
        Package("python313Packages.adb-shell", "python3.13-adb-shell", "1.0.2", "adb tools"),
    ]
    store.save_catalog_cache(catalog)
    assert store.load_catalog_cache() == catalog


def test_availability_roundtrip(tmp_path, monkeypatch) -> None:
    monkeypatch.setattr(store, "OFFLINE_FILE", tmp_path / "offline.json")
    store.save_availability({"firefox": True, "htop": False})
    assert store.load_availability_cache() == {"firefox": True, "htop": False}


def test_compute_availability(monkeypatch) -> None:
    monkeypatch.setattr(
        store, "store_names", lambda: {"firefox-157.0", "nix-2.34.8", "python3.13-adb-shell-1.0.2"}
    )
    catalog = [
        Package("firefox", "firefox", "157.0", ""),
        Package("htop", "htop", "3.3.0", ""),
        Package("python313Packages.adb-shell", "python3.13-adb-shell", "1.0.2", ""),
        Package("nix-prefetch-git", "nix-prefetch-git", "3.1.3", ""),
    ]
    assert store.compute_availability(catalog) == {
        "firefox": True,
        "htop": False,
        "python313Packages.adb-shell": True,
        "nix-prefetch-git": False,
    }