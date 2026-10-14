import json
from pathlib import Path
from core.llm_client import ask_llm
from core.json_utils import extract_json
from core.retrieval import rank_files_by_relevance

DEBUG_SYSTEM_PROMPT = """You are the Debugging Agent in an autonomous software engineering system.
You are given a bug description, a repository's file list, and the full contents of the files
most likely to be relevant.

Your job:
1. Identify the EXACT file and function/section where the bug lives.
2. Explain the root cause clearly (2-4 sentences).
3. Describe what the fix needs to do conceptually (not the full code yet, just the approach).
4. Rate your confidence: "high", "medium", or "low".

Respond with ONLY valid JSON, no markdown fences:
{
  "buggy_file": "music_player.py",
  "buggy_location": "play_for_emotion() function",
  "root_cause": "explanation here",
  "fix_approach": "explanation here",
  "confidence": "high"
}
"""

# Small repo, so we just read every source file. For larger repos, this
# should be filtered/summarized instead of reading everything.
CODE_EXTENSIONS = {".py", ".js", ".jsx", ".ts", ".tsx"}


def _read_source_files(repo_path: Path, file_list: list, task_description: str = "",
                        max_chars: int = 12000) -> str:
    """
    Reads source code files into one text blob, capped in size. When a
    task_description is given, files are ordered by TF-IDF relevance to the
    task first, so the most useful file for debugging is prioritized rather
    than cut off by arbitrary ordering.
    """
    if task_description:
        ranked = rank_files_by_relevance(task_description, str(repo_path), file_list)
        blob_parts = []
        total_chars = 0
        for entry in ranked:
            section = f"\n--- FILE: {entry['path']} (relevance={entry['score']}) ---\n{entry['content']}"
            if total_chars + len(section) > max_chars:
                continue
            blob_parts.append(section)
            total_chars += len(section)
        return "".join(blob_parts)

    blob_parts = []
    total_chars = 0
    for rel_path in file_list:
        if Path(rel_path).suffix not in CODE_EXTENSIONS:
            continue
        full_path = repo_path / rel_path
        try:
            content = full_path.read_text(encoding="utf-8", errors="ignore")
        except Exception:
            continue
        section = f"\n--- FILE: {rel_path} ---\n{content}"
        if total_chars + len(section) > max_chars:
            break
        blob_parts.append(section)
        total_chars += len(section)
    return "".join(blob_parts)


def debug_issue(task_description: str, repo_local_path: str, file_list: list) -> dict:
    """
    Analyzes the repo's source code against a bug description and returns
    a structured diagnosis: which file, what's wrong, and how to fix it.
    """
    repo_path = Path(repo_local_path)
    source_code_blob = _read_source_files(repo_path, file_list, task_description)
    if not source_code_blob:
        raise ValueError("No readable source files found to debug.")

    prompt = f"""Bug description: {task_description}

Repository source code:
{source_code_blob}
"""
    raw_response = ask_llm(prompt=prompt, system_prompt=DEBUG_SYSTEM_PROMPT, agent_name="debugging_agent")
    try:
        diagnosis = extract_json(raw_response)
    except json.JSONDecodeError as e:
        raise ValueError(f"Debugging Agent returned invalid JSON: {raw_response}") from e

    required_keys = {"buggy_file", "buggy_location", "root_cause", "fix_approach", "confidence"}
    if not required_keys.issubset(diagnosis.keys()):
        raise ValueError(f"Debugging Agent response missing required keys: {diagnosis}")

    return diagnosis