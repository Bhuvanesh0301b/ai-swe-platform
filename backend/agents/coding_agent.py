import json
import re
import shutil
from pathlib import Path
from core.llm_client import ask_llm
from core.json_utils import extract_json
from core.retrieval import rank_files_by_relevance

CODING_SYSTEM_PROMPT = """You are the Coding Agent in an autonomous software engineering system.
You are given a task description, optionally a bug diagnosis, and the full current contents
of one or more relevant files.

Your job: produce the COMPLETE new contents of each file that needs to change. Do not use diffs,
do not use "...rest unchanged...", do not omit any code - output the full file content for every
file you touch, exactly as it should be saved to disk.

ABSOLUTE RULE - BYTE-IDENTICAL PRESERVATION:
Every line in the input file that is not DIRECTLY required by the task must appear in your
output EXACTLY as it was in the input - same characters, same comments, same decorative
separators, same spacing, same indentation. Do not "clean up," "simplify," or "improve" anything
you were not explicitly asked to change, even if it looks inconsistent or old-fashioned.

Example: if the input contains a comment block like:
    # ──────────────
    # SECTION NAME
    # ──────────────
and your task has nothing to do with that section, that exact three-line block must appear
unchanged in your output. Do not replace it with "# Section name" or remove it.

The ONLY lines that should differ between input and output are lines that directly implement
the requested task. If you are unsure whether a line needs to change, do NOT change it.

For NEW code you write to implement the task: keep new comments minimal (one line, no borders),
and never repeat any single character more than 3 times in a row in anything NEW you write.
This new-content rule does not apply to pre-existing content, which must be preserved exactly
per the rule above.

Respond with ONLY valid JSON, no markdown fences, in this exact format:
{
  "files_changed": [
    {"path": "music_player.py", "new_content": "full file content here", "summary": "one line description of the change"}
  ],
  "overall_summary": "2-3 sentence summary of everything changed and why"
}
"""

CODE_EXTENSIONS = {".py", ".js", ".jsx", ".ts", ".tsx"}


def _has_degenerate_repetition(text: str, max_repeat: int = 40) -> bool:
    """Detects runaway repetition (e.g. a comment separator that never stops),
    which is a known LLM failure mode that produces unparseable truncated JSON.

    Threshold raised to 40 (from 15) because legitimate source code sometimes
    contains long decorative comment dividers (e.g. 40-50 repeated dash/box-drawing
    characters as a section header style) - these are valid, intentional repetition,
    not a model failure, and a lower threshold produced false positives that
    incorrectly rejected correct output.
    """
    return bool(re.search(r"(.)\1{" + str(max_repeat) + r",}", text))


def _read_relevant_files(repo_path: Path, file_list: list, task_description: str = "",
                          max_chars: int = 14000) -> dict:
    """
    Returns {relative_path: content} for source files, capped in total size.
    When a task_description is provided, files are prioritized by TF-IDF
    relevance to the task rather than arbitrary file-list order - this ensures
    the most relevant file to the task is never cut off by the size cap on
    larger repositories.
    """
    if task_description:
        ranked = rank_files_by_relevance(task_description, str(repo_path), file_list)
        files = {}
        total_chars = 0
        for entry in ranked:
            if total_chars + len(entry["content"]) > max_chars:
                continue
            files[entry["path"]] = entry["content"]
            total_chars += len(entry["content"])
        return files

    # Fallback: original arbitrary-order behavior if no task description given
    files = {}
    total_chars = 0
    for rel_path in file_list:
        if Path(rel_path).suffix not in CODE_EXTENSIONS:
            continue
        full_path = repo_path / rel_path
        try:
            content = full_path.read_text(encoding="utf-8", errors="ignore")
        except Exception:
            continue
        if total_chars + len(content) > max_chars:
            continue
        files[rel_path] = content
        total_chars += len(content)
    return files


def _backup_file(full_path: Path):
    """Keeps a .bak copy before overwriting, so changes can be manually reverted if needed."""
    backup_path = full_path.with_suffix(full_path.suffix + ".bak")
    if full_path.exists() and not backup_path.exists():
        shutil.copy2(full_path, backup_path)


def write_code(task_description: str, repo_local_path: str, file_list: list,
                diagnosis: dict | None = None) -> dict:
    """
    Generates and WRITES code changes directly into the cloned repo on disk.
    Returns a summary of what was changed.

    Makes up to 2 attempts: the first at normal settings, and if the response
    contains degenerate repetition or invalid JSON, a second attempt with a
    stronger frequency_penalty to suppress repetition loops.
    """
    repo_path = Path(repo_local_path)
    existing_files = _read_relevant_files(repo_path, file_list, task_description)
    if not existing_files:
        raise ValueError("No readable source files found to modify.")

    files_context = "\n".join(
        f"\n--- FILE: {path} ---\n{content}" for path, content in existing_files.items()
    )

    diagnosis_context = ""
    if diagnosis:
        diagnosis_context = f"""
Bug diagnosis from Debugging Agent:
- Buggy file: {diagnosis['buggy_file']}
- Location: {diagnosis['buggy_location']}
- Root cause: {diagnosis['root_cause']}
- Suggested fix approach: {diagnosis['fix_approach']}
"""

    prompt = f"""Task: {task_description}
{diagnosis_context}
Current repository files:
{files_context}
"""

    raw_response = None
    result = None
    last_error = None

    for attempt in range(3):
        frequency_penalty = 0.0 if attempt == 0 else (0.4 if attempt == 1 else 0.8)
        temperature = 0.0 if attempt == 0 else (0.5 if attempt == 1 else 0.8)
        raw_response = ask_llm(
            prompt=prompt, system_prompt=CODING_SYSTEM_PROMPT,
            max_tokens=16384, frequency_penalty=frequency_penalty, temperature=temperature,
            agent_name="coding_agent",
        )

        # Always try parsing first - a bounded comment divider can look like
        # "repetition" but still be perfectly valid, parseable JSON.
        try:
            result = extract_json(raw_response)
            break
        except json.JSONDecodeError:
            if _has_degenerate_repetition(raw_response):
                last_error = "Response contained runaway character repetition (likely truncated mid-generation)."
            else:
                last_error = f"Invalid JSON: {raw_response[:500]}..."
            continue
    else:
        truncation_hint = ""
        if raw_response and not raw_response.rstrip().endswith(("}", "]")):
            truncation_hint = " (response appears truncated)"

        # Dump the full raw response for debugging - this reveals exactly what
        # the model produced, rather than us guessing from summary statistics.
        debug_dir = Path(__file__).resolve().parent.parent / "storage" / "logs"
        debug_dir.mkdir(parents=True, exist_ok=True)
        debug_path = debug_dir / "last_coding_agent_failure.txt"
        if raw_response:
            debug_path.write_text(raw_response, encoding="utf-8")

        raise ValueError(
            f"Coding Agent failed after retry{truncation_hint}. Last error: {last_error}. "
            f"Full raw response saved to backend/storage/logs/last_coding_agent_failure.txt for inspection."
        )

    if "files_changed" not in result or not isinstance(result["files_changed"], list):
        raise ValueError(f"Coding Agent response missing files_changed list: {result}")

    written_files = []
    for file_change in result["files_changed"]:
        rel_path = file_change["path"]
        new_content = file_change["new_content"]
        full_path = repo_path / rel_path

        if not full_path.resolve().is_relative_to(repo_path.resolve()):
            raise ValueError(f"Refused to write outside repo boundary: {rel_path}")

        _backup_file(full_path)
        full_path.parent.mkdir(parents=True, exist_ok=True)
        full_path.write_text(new_content, encoding="utf-8")
        written_files.append({"path": rel_path, "summary": file_change.get("summary", "")})

    return {
        "files_changed": written_files,
        "overall_summary": result.get("overall_summary", ""),
    }