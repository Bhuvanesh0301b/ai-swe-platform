import re
from pathlib import Path
from datetime import datetime
from git import Repo
from git.exc import GitCommandError
from github import Github, GithubException
from core.config import settings


def _parse_owner_repo(repo_url: str) -> tuple:
    """Extracts (owner, repo_name) from a GitHub URL like https://github.com/owner/repo(.git)"""
    match = re.search(r"github\.com/([^/]+)/([^/.]+)", repo_url)
    if not match:
        raise ValueError(f"Could not parse owner/repo from URL: {repo_url}")
    return match.group(1), match.group(2)


def _authenticated_remote_url(repo_url: str, token: str) -> str:
    """Injects the token into the HTTPS URL so push works without interactive login."""
    if repo_url.startswith("https://"):
        return repo_url.replace("https://", f"https://{token}@")
    raise ValueError("Only HTTPS GitHub URLs are supported for authenticated push.")


def _get_changed_file_paths(changed_files: list, doc_files: list) -> list:
    """Combines code changes + doc changes into a deduplicated list of relative paths."""
    paths = {f["path"] for f in changed_files}
    for f in doc_files:
        if f.get("written"):
            paths.add(f["path"])
    return list(paths)


def commit_and_push(repo_url: str, repo_local_path: str, task_id: int,
                     task_description: str, changelog_entry: str,
                     changed_files: list, doc_files: list) -> dict:
    """
    Commits all agent-modified files to a new branch and pushes it to GitHub.
    Returns the branch name for use when opening the PR.
    """
    if not settings.GITHUB_TOKEN:
        raise ValueError("GITHUB_TOKEN is not set in .env")

    repo_path = Path(repo_local_path)
    git_repo = Repo(repo_path)

    # A local git identity is required to commit — set one if not already configured
    with git_repo.config_writer() as cfg:
        cfg.set_value("user", "name", "AI SWE Platform Bot")
        cfg.set_value("user", "email", "ai-swe-bot@example.com")

    branch_name = f"ai-fix/task-{task_id}-{datetime.utcnow().strftime('%Y%m%d%H%M%S')}"
    git_repo.git.checkout("-b", branch_name)

    file_paths = _get_changed_file_paths(changed_files, doc_files)
    if not file_paths:
        raise ValueError("No changed files to commit.")

    git_repo.index.add(file_paths)

    commit_message = f"AI fix: {task_description}\n\n{changelog_entry}"
    git_repo.index.commit(commit_message)

    remote_url = _authenticated_remote_url(repo_url, settings.GITHUB_TOKEN)
    try:
        git_repo.git.push(remote_url, branch_name)
    except GitCommandError as e:
        raise ValueError(f"Failed to push branch: {e}")

    return {"branch_name": branch_name, "commit_message": commit_message, "files_committed": file_paths}


def open_pull_request(repo_url: str, branch_name: str, task_description: str,
                       changelog_entry: str, task_type: str, reasoning: str) -> dict:
    """
    Opens a PR from branch_name into the repo's default branch using the GitHub API.
    """
    owner, repo_name = _parse_owner_repo(repo_url)
    gh = Github(settings.GITHUB_TOKEN)

    try:
        gh_repo = gh.get_repo(f"{owner}/{repo_name}")
    except GithubException as e:
        raise ValueError(f"Could not access repo {owner}/{repo_name} on GitHub: {e}")

    default_branch = gh_repo.default_branch

    pr_body = f"""## Summary
{changelog_entry}

## Task
{task_description}

**Task type:** `{task_type}`

## Agent reasoning
{reasoning}

---
*This PR was created automatically by the AI Software Engineer Platform.*
"""

    try:
        pr = gh_repo.create_pull(
            title=f"AI fix: {task_description}",
            body=pr_body,
            head=branch_name,
            base=default_branch,
        )
    except GithubException as e:
        raise ValueError(f"Failed to open pull request: {e.data if hasattr(e, 'data') else str(e)}")

    return {"pr_number": pr.number, "pr_url": pr.html_url, "base_branch": default_branch}


def submit_to_github(repo_url: str, repo_local_path: str, task_id: int,
                      task_description: str, changelog_entry: str,
                      changed_files: list, doc_files: list,
                      task_type: str, reasoning: str) -> dict:
    """
    Full pipeline: commit + push + open PR. Returns everything needed to display
    a link back to the user.
    """
    push_result = commit_and_push(
        repo_url, repo_local_path, task_id, task_description,
        changelog_entry, changed_files, doc_files
    )
    pr_result = open_pull_request(
        repo_url, push_result["branch_name"], task_description,
        changelog_entry, task_type, reasoning
    )

    return {**push_result, **pr_result}