import pytest
from pathlib import Path
from agents.coding_agent import _has_degenerate_repetition, _backup_file, CODE_EXTENSIONS


def test_detects_runaway_repetition():
    text = "# " + "-" * 50 + "\ncode here"
    assert _has_degenerate_repetition(text) is True


def test_allows_normal_bounded_separator():
    # A short, normal-looking comment divider should NOT trigger a false positive
    text = "# ---- Section ----\ncode here"
    assert _has_degenerate_repetition(text) is False


def test_no_repetition_in_normal_code():
    text = "def foo():\n    return 42\n"
    assert _has_degenerate_repetition(text) is False


def test_repetition_of_non_dash_characters_detected():
    # Threshold is 40 (raised from 15 earlier to avoid false positives on
    # legitimate decorative comment dividers) - this needs 41+ repeats to trigger.
    text = "x" * 45
    assert _has_degenerate_repetition(text) is True


def test_short_repetition_under_new_threshold_is_allowed():
    # Explicitly documents the current threshold: 30 repeats should NOT trigger,
    # since real decorative dividers can legitimately be this long.
    text = "x" * 30
    assert _has_degenerate_repetition(text) is False


def test_backup_file_creates_bak_copy(tmp_path):
    original = tmp_path / "sample.py"
    original.write_text("original content", encoding="utf-8")

    _backup_file(original)

    backup = tmp_path / "sample.py.bak"
    assert backup.exists()
    assert backup.read_text(encoding="utf-8") == "original content"


def test_backup_file_does_not_overwrite_existing_backup(tmp_path):
    original = tmp_path / "sample.py"
    original.write_text("version 2", encoding="utf-8")

    backup = tmp_path / "sample.py.bak"
    backup.write_text("version 1 (the real original)", encoding="utf-8")

    _backup_file(original)

    # Should NOT overwrite - the first backup is the one worth preserving
    assert backup.read_text(encoding="utf-8") == "version 1 (the real original)"


def test_path_boundary_check_allows_files_inside_repo(tmp_path):
    repo_path = tmp_path / "repo"
    repo_path.mkdir()
    target = repo_path / "src" / "file.py"

    # This mirrors the boundary check logic used in write_code()
    assert target.resolve().is_relative_to(repo_path.resolve())


def test_path_boundary_check_rejects_traversal_outside_repo(tmp_path):
    repo_path = tmp_path / "repo"
    repo_path.mkdir()
    malicious_path = repo_path / ".." / ".." / "etc" / "passwd"

    assert not malicious_path.resolve().is_relative_to(repo_path.resolve())


def test_code_extensions_includes_expected_languages():
    assert ".py" in CODE_EXTENSIONS
    assert ".js" in CODE_EXTENSIONS
    assert ".tsx" in CODE_EXTENSIONS