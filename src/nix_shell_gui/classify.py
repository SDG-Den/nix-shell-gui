from __future__ import annotations

import json
import platform
import re
import subprocess
from pathlib import Path

from . import store

SYSTEMS = {
    ("Linux", "x86_64"): "x86_64-linux",
    ("Linux", "aarch64"): "aarch64-linux",
    ("Linux", "i686"): "i686-linux",
    ("Linux", "armv7l"): "armv7l-linux",
    ("Linux", "riscv64"): "riscv64-linux",
    ("Linux", "powerpc64le"): "powerpc64le-linux",
    ("Darwin", "x86_64"): "x86_64-darwin",
    ("Darwin", "arm64"): "aarch64-darwin",
}

GUI_LIBS = re.compile(
    r"^(gtk|gtk3|gtk4|gtkmm|libadwaita|qtbase|qt5|qt6|libx11|libxcb|sdl2|webkitgtk|wxgtk|electron|gtksourceview)",
    re.IGNORECASE,
)
TUI_LIBS = re.compile(r"^(ncurses|pdcurses|termbox|tvision)", re.IGNORECASE)

EVAL_TIMEOUT = 60

_mode_cache: dict[str, str] = {}
_build_input_cache: dict[str, list[str]] = {}


def nix_system() -> str:
    return SYSTEMS.get((platform.system(), platform.machine()), "x86_64-linux")


def classify(nix_bin: str, attr_path: str) -> str:
    if attr_path not in _mode_cache:
        _mode_cache[attr_path] = _classify(nix_bin, attr_path)
    return _mode_cache[attr_path]


def _classify(nix_bin: str, attr_path: str) -> str:
    path = store.store_paths(nix_bin, [attr_path]).get(attr_path)
    if path and _has_desktop_file(path) and not _is_terminal_app(path):
        return "gui"
    names = _build_input_names(nix_bin, attr_path)
    if any(GUI_LIBS.match(name) for name in names):
        return "gui"
    if any(TUI_LIBS.match(name) for name in names):
        return "tui"
    return "cli"


def _desktop_files(path: str) -> list[Path]:
    applications = Path(path) / "share" / "applications"
    if not applications.is_dir():
        return []
    return list(applications.glob("*.desktop"))


def _has_desktop_file(path: str) -> bool:
    return bool(_desktop_files(path))


def _is_terminal_app(path: str) -> bool:
    return any(_desktop_terminal_true(desktop) for desktop in _desktop_files(path))


def _desktop_terminal_true(desktop: Path) -> bool:
    for line in desktop.read_text(errors="ignore").splitlines():
        if line.strip().lower().startswith("terminal="):
            return line.split("=", 1)[1].strip().lower() in {"true", "1"}
    return False


def _build_input_names(nix_bin: str, attr_path: str) -> list[str]:
    if attr_path not in _build_input_cache:
        _build_input_cache[attr_path] = _query_build_inputs(nix_bin, attr_path)
    return _build_input_cache[attr_path]


def _query_build_inputs(nix_bin: str, attr_path: str) -> list[str]:
    apply_expr = (
        "d: builtins.map (p: p.name) "
        "(builtins.filter (x: x != null) "
        "(d.buildInputs ++ d.nativeBuildInputs ++ d.propagatedBuildInputs))"
    )
    try:
        proc = subprocess.run(
            [
                nix_bin,
                "eval",
                "--json",
                f"nixpkgs#legacyPackages.{nix_system()}.{attr_path}",
                "--apply",
                apply_expr,
            ],
            capture_output=True,
            text=True,
            timeout=EVAL_TIMEOUT,
        )
    except subprocess.TimeoutExpired:
        return []
    if proc.returncode != 0:
        return []
    try:
        return json.loads(proc.stdout)
    except json.JSONDecodeError:
        return []