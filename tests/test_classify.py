from pathlib import Path

from nix_shell_gui.classify import _desktop_terminal_true, _is_terminal_app


def test_desktop_terminal_true_detects_terminal_flag(tmp_path: Path) -> None:
    desktop = tmp_path / "btop.desktop"
    desktop.write_text(
        "[Desktop Entry]\nType=Application\nName=btop\nExec=btop\nTerminal=true\n"
    )
    assert _desktop_terminal_true(desktop)


def test_desktop_terminal_true_false_and_missing(tmp_path: Path) -> None:
    false_file = tmp_path / "firefox.desktop"
    false_file.write_text("[Desktop Entry]\nType=Application\nTerminal=false\n")
    assert not _desktop_terminal_true(false_file)
    missing = tmp_path / "no-terminal.desktop"
    missing.write_text("[Desktop Entry]\nType=Application\nExec=firefox\n")
    assert not _desktop_terminal_true(missing)


def test_is_terminal_app_checks_any_desktop_file(tmp_path: Path) -> None:
    applications = tmp_path / "share" / "applications"
    applications.mkdir(parents=True)
    (applications / "btop.desktop").write_text(
        "[Desktop Entry]\nType=Application\nTerminal=true\n"
    )
    assert _is_terminal_app(str(tmp_path))


def test_is_terminal_app_false_when_no_terminal_flag(tmp_path: Path) -> None:
    applications = tmp_path / "share" / "applications"
    applications.mkdir(parents=True)
    (applications / "firefox.desktop").write_text(
        "[Desktop Entry]\nType=Application\nTerminal=false\n"
    )
    assert not _is_terminal_app(str(tmp_path))