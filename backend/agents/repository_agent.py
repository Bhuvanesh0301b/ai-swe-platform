import os
import shutil
import stat
import json
from pathlib import Path
from git import Repo
from git.exc import GitCommandError
from core.llm_client import ask_llm
from core.json_utils import extract_json

BACKEND_ROOT = Path(__file__).resolve().parent.parent
REPOS_DIR = BACKEND_ROOT / "storage" / "repos"

LANGUAGE_MARKERS = {
    "requirements.txt": "Python",
    "Pipfile": "Python",
    "pyproject.toml": "Python",
    "package.json": "JavaScript/TypeScript",
    "go.mod": "Go",
    "pom.xml": "Java",
    "Cargo.toml": "Rust",
}

FRAMEWORK_MARKERS = {
    "manage.py": "Django",
    "app.py": "Flask/FastAPI (likely)",
    "next.config.js": "Next.js",
    "nest-cli.json": "NestJS",
    "vite.config.js": "Vite (React/Vue)",
}

IGNORE_DIRS = {".git", "node_modules", "venv", "__pycache__", ".vite", "dist", "build"}

FRAMEWORK_SYSTEM_PROMPT = """You are the Repository Agent in an autonomous software engineering system.
You are given a repository's file list and a preview of its dependency file (requirements.txt or package.json).

Determine:
1. "language": the primary programming language (e.g. "Python", "JavaScript", "TypeScript").
2. "framework": the specific framework/library stack in plain English. If it's not a web framework
   (e.g. it's a desktop GUI app, CLI tool, ML script, etc.), say so explicitly instead of guessing
   a web framework. Be precise - e.g. "Tkinter desktop GUI with Pygame for audio" is better than "Flask".
3. "project_type": one of "web_backend", "web_frontend", "full_stack_web", "desktop_application",
   "cli_tool", "machine_learning_script", "library", "other".

Respond with ONLY a valid JSON object, no markdown fences, no other text:
{"language": "Python", "framework": "description here", "project_type": "desktop_application"}
"""


def _remove_readonly(func, path, _):
    """Windows sometimes marks .git files read-only, which blocks shutil.rmtree."""
    os.chmod(path, stat.S_IWRITE)
    func(path)


def _safe_repo_folder_name(repo_url: str, task_id: int) -> str:
    name = repo_url.rstrip("/").split("/")[-1].replace(".git", "")
    return f"task_{task_id}_{name}"


def clone_repository(repo_url: str, task_id: int) -> Path:
    """
    Clones the repo fresh into storage/repos/task_<id>_<reponame>.
    If that folder already exists (e.g. re-running), it's deleted first.
    """
    REPOS_DIR.mkdir(parents=True, exist_ok=True)
    target_path = REPOS_DIR / _safe_repo_folder_name(repo_url, task_id)

    if target_path.exists():
        shutil.rmtree(target_path, onerror=_remove_readonly)

    try:
        Repo.clone_from(repo_url, target_path, depth=1)
    except GitCommandError as e:
        raise ValueError(f"Failed to clone repository: {e}")

    return target_path


def build_file_tree(root_path: Path, max_files: int = 300) -> list:
    """
    Walks the repo and returns a flat list of relative file paths,
    skipping ignored directories. Capped at max_files for large repos.
    """
    file_list = []
    for dirpath, dirnames, filenames in os.walk(root_path):
        dirnames[:] = [d for d in dirnames if d not in IGNORE_DIRS]
        for filename in filenames:
            rel_path = os.path.relpath(os.path.join(dirpath, filename), root_path)
            file_list.append(rel_path.replace("\\", "/"))
            if len(file_list) >= max_files:
                return file_list
    return file_list


def detect_language_and_framework(file_list: list) -> dict:
    top_level_files = {f for f in file_list if "/" not in f}

    detected_language = "Unknown"
    for marker, language in LANGUAGE_MARKERS.items():
        if marker in top_level_files:
            detected_language = language
            break

    detected_framework = None
    for marker, framework in FRAMEWORK_MARKERS.items():
        if marker in top_level_files:
            detected_framework = framework
            break

    return {"language": detected_language, "framework": detected_framework}


def read_dependency_file(root_path: Path, file_list: list) -> str:
    """Reads requirements.txt or package.json contents if present, for context."""
    for candidate in ["requirements.txt", "package.json"]:
        if candidate in file_list:
            try:
                return (root_path / candidate).read_text(encoding="utf-8", errors="ignore")[:2000]
            except Exception:
                return ""
    return ""


def classify_project_with_llm(file_list: list, dependencies_preview: str,
                               heuristic_language: str, heuristic_framework: str) -> dict:
    """
    Uses the LLM to refine the fast heuristic guess into an accurate
    language/framework/project_type classification.
    Falls back to the heuristic values if the LLM call fails.
    """
    prompt = f"""Repository files (sample):
{json.dumps(file_list[:100])}

Dependency file preview:
{dependencies_preview if dependencies_preview else "(none found)"}

Quick heuristic guess (may be wrong, verify against the evidence above):
language={heuristic_language}, framework={heuristic_framework}
"""
    try:
        raw_response = ask_llm(prompt=prompt, system_prompt=FRAMEWORK_SYSTEM_PROMPT, agent_name="repository_agent")
        result = extract_json(raw_response)
        required_keys = {"language", "framework", "project_type"}
        if not required_keys.issubset(result.keys()):
            raise ValueError("LLM classification missing required keys")
        return result
    except Exception:
        return {
            "language": heuristic_language,
            "framework": heuristic_framework,
            "project_type": "unknown",
        }


def analyze_repository(repo_url: str, task_id: int) -> dict:
    """
    Main entry point: clones the repo and returns a structured analysis.
    Uses a fast heuristic first, then refines it with an LLM classification pass.
    """
    repo_path = clone_repository(repo_url, task_id)
    file_list = build_file_tree(repo_path)
    heuristic = detect_language_and_framework(file_list)
    dependencies_raw = read_dependency_file(repo_path, file_list)

    classification = classify_project_with_llm(
        file_list, dependencies_raw, heuristic["language"], heuristic["framework"]
    )

    return {
        "local_path": str(repo_path),
        "file_count": len(file_list),
        "file_list": file_list,
        "language": classification["language"],
        "framework": classification["framework"],
        "project_type": classification["project_type"],
        "dependencies_preview": dependencies_raw,
    }