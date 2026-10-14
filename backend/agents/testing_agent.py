import ast
import json
import py_compile
import tempfile
import os
from pathlib import Path
from core.llm_client import ask_llm
from core.json_utils import extract_json

REVIEW_SYSTEM_PROMPT = """You are the Testing Agent in an autonomous software engineering system.
You are given a task description, the original bug diagnosis (if any), and the code changes that
were made (as full file contents before and after).

Your job is a LOGICAL CODE REVIEW — the code has already passed syntax validation, so focus on:
1. Does the change actually address the stated task/bug?
2. Are there edge cases the fix misses?
3. Did the change accidentally break or remove any unrelated existing functionality?
4. Is the fix consistent with the rest of the codebase's style and patterns?

Respond with ONLY valid JSON, no markdown fences:
{
  "verdict": "pass",
  "issues_found": ["list of specific concerns, empty list if none"],
  "reasoning": "2-4 sentence explanation of your verdict"
}
"verdict" must be exactly one of: "pass", "pass_with_concerns", "fail"
"""


def check_python_syntax(file_path: Path) -> dict:
    """
    Fast mechanical check: does this Python file parse and compile cleanly?
    Does NOT execute the code — just validates syntax, which is safe and instant.
    """
    source = file_path.read_text(encoding="utf-8", errors="ignore")

    try:
        ast.parse(source, filename=str(file_path))
    except SyntaxError as e:
        return {"passed": False, "error": f"SyntaxError: {e.msg} at line {e.lineno}"}

    try:
        with tempfile.NamedTemporaryFile(suffix=".py", delete=False) as tmp:
            tmp.write(source.encode("utf-8"))
            tmp_path = tmp.name
        py_compile.compile(tmp_path, doraise=True)
    except py_compile.PyCompileError as e:
        return {"passed": False, "error": f"CompileError: {str(e)}"}
    finally:
        if os.path.exists(tmp_path):
            os.remove(tmp_path)

    return {"passed": True, "error": None}


def run_syntax_checks(repo_local_path: str, changed_files: list) -> dict:
    """
    Runs syntax validation on every changed file. Only Python files are checked
    mechanically for now; other extensions are skipped with a note (future work).
    """
    repo_path = Path(repo_local_path)
    results = []
    all_passed = True

    for file_info in changed_files:
        rel_path = file_info["path"]
        full_path = repo_path / rel_path

        if full_path.suffix != ".py":
            results.append({"path": rel_path, "passed": None, "error": "Skipped: syntax check only supports Python currently"})
            continue

        check = check_python_syntax(full_path)
        results.append({"path": rel_path, "passed": check["passed"], "error": check["error"]})
        if not check["passed"]:
            all_passed = False

    return {"all_passed": all_passed, "file_results": results}


def run_llm_review(task_description: str, diagnosis: dict | None,
                    repo_local_path: str, changed_files: list) -> dict:
    """
    Second-layer review: asks the LLM to reason about correctness, not just syntax.
    """
    repo_path = Path(repo_local_path)
    files_context_parts = []
    for file_info in changed_files:
        rel_path = file_info["path"]
        full_path = repo_path / rel_path
        backup_path = full_path.with_suffix(full_path.suffix + ".bak")

        new_content = full_path.read_text(encoding="utf-8", errors="ignore")
        old_content = backup_path.read_text(encoding="utf-8", errors="ignore") if backup_path.exists() else "(new file, no prior version)"

        files_context_parts.append(
            f"\n--- FILE: {rel_path} ---\nBEFORE:\n{old_content}\n\nAFTER:\n{new_content}"
        )

    diagnosis_context = ""
    if diagnosis:
        diagnosis_context = f"\nOriginal bug diagnosis: {diagnosis['root_cause']}\nIntended fix approach: {diagnosis['fix_approach']}\n"

    prompt = f"""Task: {task_description}
{diagnosis_context}
Code changes to review:
{"".join(files_context_parts)}
"""

    raw_response = ask_llm(prompt=prompt, system_prompt=REVIEW_SYSTEM_PROMPT, agent_name="testing_agent")
    try:
        review = extract_json(raw_response)
    except json.JSONDecodeError as e:
        raise ValueError(f"Testing Agent review returned invalid JSON: {raw_response}") from e

    required_keys = {"verdict", "issues_found", "reasoning"}
    if not required_keys.issubset(review.keys()):
        raise ValueError(f"Testing Agent review missing required keys: {review}")

    return review


def test_changes(task_description: str, diagnosis: dict | None,
                  repo_local_path: str, changed_files: list) -> dict:
    """
    Main entry point: runs syntax checks first. Only proceeds to the more
    expensive LLM review if syntax checks pass (no point reviewing broken code).
    """
    syntax_results = run_syntax_checks(repo_local_path, changed_files)

    if not syntax_results["all_passed"]:
        return {
            "syntax_check": syntax_results,
            "llm_review": None,
            "final_verdict": "fail",
        }

    llm_review = run_llm_review(task_description, diagnosis, repo_local_path, changed_files)

    return {
        "syntax_check": syntax_results,
        "llm_review": llm_review,
        "final_verdict": llm_review["verdict"],
    }