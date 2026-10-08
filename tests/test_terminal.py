from nix_shell_gui.terminal import (
    COMMAND_PLACEHOLDER,
    COMMAND_STRING_PLACEHOLDER,
    _terminal_template,
    expand_command,
)


def test_expand_command_replaces_placeholder_with_nix_args():
    template = ["kitty", "--", COMMAND_PLACEHOLDER]
    nix_args = ["/nix/var/nix/profiles/default/bin/nix", "run", "nixpkgs#adb"]
    assert expand_command(template, nix_args) == [
        "kitty",
        "--",
        "/nix/var/nix/profiles/default/bin/nix",
        "run",
        "nixpkgs#adb",
    ]


def test_expand_command_shell_quotes_command_string_placeholder():
    template = ["ghostty", "-e", "zsh", "-c", COMMAND_STRING_PLACEHOLDER]
    nix_args = ["/nix/var/nix/profiles/default/bin/nix", "shell", "nixpkgs#cowsay"]
    assert expand_command(template, nix_args) == [
        "ghostty",
        "-e",
        "zsh",
        "-c",
        "/nix/var/nix/profiles/default/bin/nix shell 'nixpkgs#cowsay'",
    ]


def test_terminal_template_defaults_are_known_terminals(monkeypatch):
    monkeypatch.setattr("nix_shell_gui.store.load_config", lambda: {})
    monkeypatch.setattr("nix_shell_gui.terminal.shutil.which", lambda name: None)
    template = _terminal_template()
    assert COMMAND_PLACEHOLDER in template or COMMAND_STRING_PLACEHOLDER in template
    assert template[0] in {"ghostty", "kitty", "alacritty", "foot", "xterm"}


def test_terminal_template_prefers_configured_list(monkeypatch):
    monkeypatch.setattr(
        "nix_shell_gui.store.load_config",
        lambda: {"terminal": ["wezterm", "start", "--", COMMAND_PLACEHOLDER]},
    )
    assert _terminal_template() == ["wezterm", "start", "--", COMMAND_PLACEHOLDER]