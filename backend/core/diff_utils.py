import difflib
from pathlib import Path


def _read_lines(file_path: Path) -> list:
    if not file_path.exists():
        return []
    return file_path.read_text(encoding="utf-8", errors="ignore").splitlines(keepends=True)


def build_file_diff(repo_local_path: str, changed_files: list) -> list:
    """
    For each changed file, compares its .bak (original, pre-AI-edit) version
    against the current on-disk version, and returns a structured line-by-line
    diff suitable for rendering in a UI (similar to GitHub's diff view).

    Uses Python's built-in difflib - no external tools, no LLM calls, instant.
    """
    repo_path = Path(repo_local_path)
    results = []

    for file_info in changed_files:
        rel_path = file_info["path"]
        current_path = repo_path / rel_path
        backup_path = current_path.with_suffix(current_path.suffix + ".bak")

        before_lines = _read_lines(backup_path)
        after_lines = _read_lines(current_path)

        diff = list(difflib.unified_diff(
            before_lines, after_lines,
            fromfile=f"{rel_path} (before)",
            tofile=f"{rel_path} (after)",
            lineterm="",
        ))

        parsed_lines = []
        for line in diff:
            if line.startswith("+++") or line.startswith("---"):
                line_type = "file_header"
            elif line.startswith("@@"):
                line_type = "hunk_header"
            elif line.startswith("+"):
                line_type = "added"
            elif line.startswith("-"):
                line_type = "removed"
            else:
                line_type = "context"
            parsed_lines.append({"type": line_type, "content": line})

        has_backup = backup_path.exists()
        results.append({
            "path": rel_path,
            "has_original": has_backup,
            "lines": parsed_lines,
            "lines_added": sum(1 for l in parsed_lines if l["type"] == "added"),
            "lines_removed": sum(1 for l in parsed_lines if l["type"] == "removed"),
        })

    return results