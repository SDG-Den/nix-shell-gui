from __future__ import annotations

import shlex
import shutil
import subprocess

from . import store

DEFAULT_TERMINALS = [
    ["ghostty", "-e", "zsh", "-c", "{command_s}"],
    ["kitty", "--", "{command}"],
    ["alacritty", "-e", "{command}"],
    ["foot", "{command}"],
    ["xterm", "-e", "{command}"],
]
COMMAND_PLACEHOLDER = "{command}"
COMMAND_STRING_PLACEHOLDER = "{command_s}"


def launch_direct(nix_bin: str, attr_path: str) -> None:
    subprocess.Popen(
        [nix_bin, "run", f"nixpkgs#{attr_path}"],
        stdin=subprocess.DEVNULL,
        stdout=subprocess.DEVNULL,
        stderr=subprocess.DEVNULL,
        start_new_session=True,
    )


def launch_in_terminal(nix_bin: str, attr_path: str, mode: str) -> None:
    action = "run" if mode == "tui" else "shell"
    nix_args = [nix_bin, action, f"nixpkgs#{attr_path}"]
    subprocess.Popen(
        expand_command(_terminal_template(), nix_args),
        stdin=subprocess.DEVNULL,
        stdout=subprocess.DEVNULL,
        stderr=subprocess.DEVNULL,
        start_new_session=True,
    )


def expand_command(template: list[str], nix_args: list[str]) -> list[str]:
    result: list[str] = []
    for token in template:
        if token == COMMAND_PLACEHOLDER:
            result.extend(nix_args)
        elif token == COMMAND_STRING_PLACEHOLDER:
            result.append(shlex.join(nix_args))
        else:
            result.append(token)
    return result


def _terminal_template() -> list[str]:
    configured = store.load_config().get("terminal")
    if isinstance(configured, list) and configured and all(
        isinstance(token, str) for token in configured
    ):
        return configured
    for candidate in DEFAULT_TERMINALS:
        if shutil.which(candidate[0]):
            return candidate
    return DEFAULT_TERMINALS[0]