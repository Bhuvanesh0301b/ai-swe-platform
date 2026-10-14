from agents.repository_agent import detect_language_and_framework, build_file_tree


def test_detects_python_from_requirements_txt():
    files = ["requirements.txt", "app.py", "utils.py"]
    result = detect_language_and_framework(files)
    assert result["language"] == "Python"


def test_detects_javascript_from_package_json():
    files = ["package.json", "index.js", "src/App.jsx"]
    result = detect_language_and_framework(files)
    assert result["language"] == "JavaScript/TypeScript"


def test_detects_django_framework():
    files = ["manage.py", "requirements.txt", "app/models.py"]
    result = detect_language_and_framework(files)
    assert result["framework"] == "Django"


def test_unknown_language_when_no_markers_present():
    files = ["README.md", "notes.txt"]
    result = detect_language_and_framework(files)
    assert result["language"] == "Unknown"


def test_no_framework_detected_when_no_markers_present():
    files = ["requirements.txt", "script.py"]
    result = detect_language_and_framework(files)
    assert result["framework"] is None


def test_build_file_tree_respects_max_files_cap(tmp_path):
    for i in range(10):
        (tmp_path / f"file_{i}.py").write_text("x = 1", encoding="utf-8")

    result = build_file_tree(tmp_path, max_files=5)
    assert len(result) == 5


def test_build_file_tree_ignores_venv_and_node_modules(tmp_path):
    (tmp_path / "real_file.py").write_text("x = 1", encoding="utf-8")
    venv_dir = tmp_path / "venv"
    venv_dir.mkdir()
    (venv_dir / "ignored.py").write_text("y = 2", encoding="utf-8")

    result = build_file_tree(tmp_path)
    assert "real_file.py" in result
    assert not any("venv" in f for f in result)