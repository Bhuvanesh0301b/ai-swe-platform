import json
from pathlib import Path
from core.llm_client import ask_llm
from core.json_utils import extract_json
from agents.coding_agent import _has_degenerate_repetition

DOC_SYSTEM_PROMPT = """You are the Documentation Agent in an autonomous software engineering system.
You are given a task description and the code changes that were made (full file contents,
after the change). Your job has two parts:

1. For each changed file, determine if any function/class involved in the change is missing a
   docstring or has an outdated one that no longer matches its behavior. If so, provide the
   COMPLETE new file content with proper docstrings added/updated (keep all other code identical —
   only touch documentation, never change logic). If the file's documentation is already adequate,
   set "updated_content" to null for that file.

2. Write a short "changelog_entry": 1-3 sentences in plain English, suitable for a README changelog
   or commit body, describing what changed and why — written for a future developer, not for you.

Respond with ONLY valid JSON, no markdown fences:
{
  "files_documented": [
    {"path": "music_player.py", "updated_content": "full file content or null", "notes": "what was added/changed, or 'no changes needed'"}
  ],
  "changelog_entry": "text here"
}
"""


def _read_changed_files(repo_path: Path, changed_files: list) -> dict:
    files = {}
    for file_info in changed_files:
        rel_path = file_info["path"]
        full_path = repo_path / rel_path
        try:
            files[rel_path] = full_path.read_text(encoding="utf-8", errors="ignore")
        except Exception:
            continue
    return files


def document_changes(task_description: str, repo_local_path: str, changed_files: list) -> dict:
    """
    Reviews the current (already-modified) code and adds/updates docstrings where missing,
    plus produces a plain-English changelog entry. Only writes files where documentation
    was actually added or changed — never touches files whose docs are already adequate.
    """
    repo_path = Path(repo_local_path)
    current_files = _read_changed_files(repo_path, changed_files)

    if not current_files:
        raise ValueError("No readable changed files found to document.")

    files_context = "\n".join(
        f"\n--- FILE: {path} ---\n{content}" for path, content in current_files.items()
    )

    prompt = f"""Task that was completed: {task_description}

Current file contents (after the code fix):
{files_context}
"""

    raw_response = None
    result = None
    last_error = None

    for attempt in range(2):
        frequency_penalty = 0.0 if attempt == 0 else 0.6
        temperature = 0.2 if attempt == 0 else 0.6
        raw_response = ask_llm(
            prompt=prompt, system_prompt=DOC_SYSTEM_PROMPT,
            max_tokens=16384, frequency_penalty=frequency_penalty, temperature=temperature,
            agent_name="documentation_agent",
        )

        try:
            result = extract_json(raw_response)
            break
        except json.JSONDecodeError:
            if _has_degenerate_repetition(raw_response):
                last_error = "Response contained runaway character repetition."
            else:
                last_error = f"Invalid JSON: {raw_response[:500]}..."
            continue
    else:
        raise ValueError(f"Documentation Agent failed after retry. Last error: {last_error}")

    if "files_documented" not in result or "changelog_entry" not in result:
        raise ValueError(f"Documentation Agent response missing required keys: {result}")

    written_files = []
    for file_info in result["files_documented"]:
        rel_path = file_info["path"]
        updated_content = file_info.get("updated_content")
        notes = file_info.get("notes", "")

        if updated_content:  # only write if there's an actual change (not null/empty)
            full_path = repo_path / rel_path
            if not full_path.resolve().is_relative_to(repo_path.resolve()):
                raise ValueError(f"Refused to write outside repo boundary: {rel_path}")
            full_path.write_text(updated_content, encoding="utf-8")
            written_files.append({"path": rel_path, "notes": notes, "written": True})
        else:
            written_files.append({"path": rel_path, "notes": notes, "written": False})

    return {
        "files_documented": written_files,
        "changelog_entry": result["changelog_entry"],
    }

OVERVIEW_SYSTEM_PROMPT = """You are the Documentation Agent, answering a question about an existing
codebase (not documenting a code change - there is none for this task).

You are given the question, the repository's file list, and the current README content if any.

Your job:
1. Answer the question clearly and accurately based on the evidence provided (file names,
   README content, dependencies). Do not invent details not supported by the evidence.
2. If the current README.md is missing, empty, or doesn't already answer this question well,
   propose improved README.md content that would answer it for future readers. Otherwise,
   set "readme_update" to null.

Respond with ONLY valid JSON, no markdown fences:
{
  "answer": "direct answer to the question, 2-5 sentences",
  "readme_update": "full new README.md content, or null if the existing README already covers this"
}
"""


def answer_project_question(task_description: str, repo_local_path: str, file_list: list) -> dict:
    """
    Handles documentation_only tasks that are questions about the existing
    project (e.g. "what is this project about") rather than documentation of
    a code change. Returns a direct answer, and optionally proposes a README
    update if the current one is missing or inadequate.
    """
    repo_path = Path(repo_local_path)
    readme_content = "(no README.md found)"
    if "README.md" in file_list:
        readme_path = repo_path / "README.md"
        try:
            content = readme_path.read_text(encoding="utf-8", errors="ignore").strip()
            readme_content = content if content else "(README.md exists but is empty)"
        except Exception:
            pass

    prompt = f"""Question: {task_description}

Repository files: {json.dumps(file_list[:50])}

Current README.md content:
{readme_content}
"""

    raw_response = ask_llm(
        prompt=prompt, system_prompt=OVERVIEW_SYSTEM_PROMPT,
        max_tokens=4096, agent_name="documentation_agent_overview",
    )

    try:
        result = extract_json(raw_response)
    except json.JSONDecodeError as e:
        raise ValueError(f"Documentation Agent (overview mode) returned invalid JSON: {raw_response}") from e

    if "answer" not in result:
        raise ValueError(f"Documentation Agent (overview mode) response missing 'answer': {result}")

    written_files = []
    if result.get("readme_update"):
        readme_path = repo_path / "README.md"
        readme_path.write_text(result["readme_update"], encoding="utf-8")
        written_files.append({"path": "README.md", "notes": "Updated to better answer the question", "written": True})

    return {
        "answer": result["answer"],
        "files_documented": written_files,
        "changelog_entry": result["answer"],
    }