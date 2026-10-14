import pytest
from pathlib import Path
from agents.testing_agent import check_python_syntax, run_syntax_checks


@pytest.fixture
def tmp_python_file(tmp_path):
    def _make(content: str, filename: str = "sample.py") -> Path:
        file_path = tmp_path / filename
        file_path.write_text(content, encoding="utf-8")
        return file_path
    return _make


def test_valid_python_passes(tmp_python_file):
    file_path = tmp_python_file("def hello():\n    return 'world'\n")
    result = check_python_syntax(file_path)
    assert result["passed"] is True
    assert result["error"] is None


def test_syntax_error_is_caught(tmp_python_file):
    file_path = tmp_python_file("def hello(\n    return 'world'\n")  # missing closing paren
    result = check_python_syntax(file_path)
    assert result["passed"] is False
    assert "SyntaxError" in result["error"]


def test_indentation_error_is_caught(tmp_python_file):
    file_path = tmp_python_file("def hello():\nreturn 'world'\n")  # bad indentation
    result = check_python_syntax(file_path)
    assert result["passed"] is False


def test_empty_file_is_valid_python(tmp_python_file):
    file_path = tmp_python_file("")
    result = check_python_syntax(file_path)
    assert result["passed"] is True


def test_run_syntax_checks_all_pass(tmp_path):
    good_file = tmp_path / "good.py"
    good_file.write_text("x = 1\n", encoding="utf-8")

    result = run_syntax_checks(str(tmp_path), [{"path": "good.py"}])
    assert result["all_passed"] is True
    assert result["file_results"][0]["passed"] is True


def test_run_syntax_checks_detects_failure(tmp_path):
    bad_file = tmp_path / "bad.py"
    bad_file.write_text("def broken(\n", encoding="utf-8")

    result = run_syntax_checks(str(tmp_path), [{"path": "bad.py"}])
    assert result["all_passed"] is False
    assert result["file_results"][0]["passed"] is False


def test_run_syntax_checks_skips_non_python_files(tmp_path):
    js_file = tmp_path / "script.js"
    js_file.write_text("const x = 1;", encoding="utf-8")

    result = run_syntax_checks(str(tmp_path), [{"path": "script.js"}])
    # Non-Python files are skipped (passed=None), so they shouldn't fail the overall check
    assert result["all_passed"] is True
    assert result["file_results"][0]["passed"] is None