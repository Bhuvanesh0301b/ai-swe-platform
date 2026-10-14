import pytest
from pathlib import Path
from core.retrieval import rank_files_by_relevance


@pytest.fixture
def sample_repo(tmp_path):
    (tmp_path / "auth.py").write_text(
        "def login(username, password):\n    validate_credentials(username, password)\n    return create_session()\n",
        encoding="utf-8",
    )
    (tmp_path / "math_utils.py").write_text(
        "def add(a, b):\n    return a + b\n\ndef multiply(a, b):\n    return a * b\n",
        encoding="utf-8",
    )
    return tmp_path


def test_ranks_relevant_file_higher(sample_repo):
    result = rank_files_by_relevance(
        "fix bug in user login authentication",
        str(sample_repo),
        ["auth.py", "math_utils.py"],
    )
    assert result[0]["path"] == "auth.py"
    assert result[0]["score"] > result[1]["score"]


def test_returns_all_files(sample_repo):
    result = rank_files_by_relevance(
        "any task description",
        str(sample_repo),
        ["auth.py", "math_utils.py"],
    )
    assert len(result) == 2
    assert {r["path"] for r in result} == {"auth.py", "math_utils.py"}


def test_single_file_returns_full_score(tmp_path):
    (tmp_path / "only.py").write_text("x = 1\n", encoding="utf-8")
    result = rank_files_by_relevance("any task", str(tmp_path), ["only.py"])
    assert len(result) == 1
    assert result[0]["score"] == 1.0


def test_empty_file_list_returns_empty(tmp_path):
    result = rank_files_by_relevance("any task", str(tmp_path), [])
    assert result == []


def test_nonexistent_files_are_skipped(tmp_path):
    result = rank_files_by_relevance("any task", str(tmp_path), ["does_not_exist.py"])
    assert result == []


def test_each_result_has_required_keys(sample_repo):
    result = rank_files_by_relevance("login task", str(sample_repo), ["auth.py", "math_utils.py"])
    for entry in result:
        assert "path" in entry
        assert "score" in entry
        assert "content" in entry