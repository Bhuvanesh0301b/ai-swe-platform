import json
from agents.documentation_agent import answer_project_question
from agents.explainability_agent import generate_explanation
from agents.github_agent import submit_to_github
from agents.documentation_agent import document_changes
from agents.testing_agent import test_changes
from agents.debugging_agent import debug_issue
from agents.coding_agent import write_code
from agents.repository_agent import analyze_repository
from fastapi import FastAPI, HTTPException
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel
from datetime import datetime
from agents.planner_agent import generate_plan
from core.agent_logger import get_recent_logs
from core.diff_utils import build_file_diff

from core.config import settings
from core.database import init_db, get_connection
from core.llm_client import ask_llm

app = FastAPI(title="AI Software Engineer Platform")

# Allow the React dev server to call this API
app.add_middleware(
    CORSMiddleware,
    allow_origins=["http://localhost:5173"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

@app.on_event("startup")
def startup_event():
    settings.validate()
    init_db()

class TaskRequest(BaseModel):
    repo_url: str
    task_description: str

@app.get("/")
def root():
    return {"status": "running", "message": "AI SWE Platform backend is alive"}

@app.get("/health/llm")
def check_llm():
    """Quick test that Groq API key works"""
    try:
        result = ask_llm("Reply with exactly: OK")
        return {"llm_status": "connected", "response": result}
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))

@app.post("/tasks")
def create_task(task: TaskRequest):
    conn = get_connection()
    cursor = conn.cursor()
    cursor.execute(
        "INSERT INTO tasks (repo_url, task_description) VALUES (?, ?)",
        (task.repo_url, task.task_description)
    )
    conn.commit()
    task_id = cursor.lastrowid
    conn.close()
    return {"task_id": task_id, "status": "pending", "message": "Task received"}

@app.get("/tasks")
def list_tasks():
    conn = get_connection()
    cursor = conn.cursor()
    cursor.execute("SELECT * FROM tasks ORDER BY created_at DESC")
    rows = cursor.fetchall()
    conn.close()
    return [dict(row) for row in rows]

@app.post("/tasks/{task_id}/plan")
def create_plan(task_id: int):
    conn = get_connection()
    cursor = conn.cursor()
    cursor.execute("SELECT * FROM tasks WHERE id = ?", (task_id,))
    task = cursor.fetchone()

    if task is None:
        conn.close()
        raise HTTPException(status_code=404, detail="Task not found")

    try:
        plan = generate_plan(task["task_description"])
    except ValueError as e:
        conn.close()
        raise HTTPException(status_code=502, detail=f"Planner Agent failed: {str(e)}")

    cursor.execute(
        """UPDATE tasks
           SET task_type = ?, agent_sequence = ?, reasoning = ?, plan_generated_at = ?
           WHERE id = ?""",
        (plan["task_type"], json.dumps(plan["agent_sequence"]), plan["reasoning"],
         datetime.utcnow().isoformat(), task_id)
    )
    conn.commit()
    conn.close()

    return {
        "task_id": task_id,
        "task_type": plan["task_type"],
        "agent_sequence": plan["agent_sequence"],
        "reasoning": plan["reasoning"],
    }


@app.get("/tasks/{task_id}/plan")
def get_plan(task_id: int):
    conn = get_connection()
    cursor = conn.cursor()
    cursor.execute("SELECT * FROM tasks WHERE id = ?", (task_id,))
    task = cursor.fetchone()
    conn.close()

    if task is None:
        raise HTTPException(status_code=404, detail="Task not found")
    if task["task_type"] is None:
        return {"task_id": task_id, "plan_generated": False}

    return {
        "task_id": task_id,
        "plan_generated": True,
        "task_type": task["task_type"],
        "agent_sequence": json.loads(task["agent_sequence"]),
        "reasoning": task["reasoning"],
    }

@app.post("/tasks/{task_id}/analyze-repo")
def analyze_repo(task_id: int):
    conn = get_connection()
    cursor = conn.cursor()
    cursor.execute("SELECT * FROM tasks WHERE id = ?", (task_id,))
    task = cursor.fetchone()

    if task is None:
        conn.close()
        raise HTTPException(status_code=404, detail="Task not found")

    try:
        analysis = analyze_repository(task["repo_url"], task_id)
    except ValueError as e:
        conn.close()
        raise HTTPException(status_code=502, detail=str(e))

    cursor.execute(
        """UPDATE tasks
           SET repo_local_path = ?, repo_language = ?, repo_framework = ?, repo_project_type = ?,
               repo_file_count = ?, repo_file_list = ?, repo_analyzed_at = ?
           WHERE id = ?""",
        (analysis["local_path"], analysis["language"], analysis["framework"], analysis["project_type"],
         analysis["file_count"], json.dumps(analysis["file_list"]),
         datetime.utcnow().isoformat(), task_id)
    )
    conn.commit()
    conn.close()

    return {
        "task_id": task_id,
        "language": analysis["language"],
        "framework": analysis["framework"],
        "project_type": analysis["project_type"],
        "file_count": analysis["file_count"],
        "file_list": analysis["file_list"],
        "dependencies_preview": analysis["dependencies_preview"],
    }

@app.post("/tasks/{task_id}/debug")
def debug_task(task_id: int):
    conn = get_connection()
    cursor = conn.cursor()
    cursor.execute("SELECT * FROM tasks WHERE id = ?", (task_id,))
    task = cursor.fetchone()

    if task is None:
        conn.close()
        raise HTTPException(status_code=404, detail="Task not found")
    if not task["repo_local_path"]:
        conn.close()
        raise HTTPException(status_code=400, detail="Repository not analyzed yet. Run analyze-repo first.")

    try:
        diagnosis = debug_issue(
            task["task_description"], task["repo_local_path"], json.loads(task["repo_file_list"])
        )
    except ValueError as e:
        conn.close()
        raise HTTPException(status_code=502, detail=str(e))

    cursor.execute(
        "UPDATE tasks SET debug_diagnosis = ?, debug_analyzed_at = ? WHERE id = ?",
        (json.dumps(diagnosis), datetime.utcnow().isoformat(), task_id)
    )
    conn.commit()
    conn.close()
    return {"task_id": task_id, **diagnosis}


@app.post("/tasks/{task_id}/code")
def code_task(task_id: int):
    conn = get_connection()
    cursor = conn.cursor()
    cursor.execute("SELECT * FROM tasks WHERE id = ?", (task_id,))
    task = cursor.fetchone()

    if task is None:
        conn.close()
        raise HTTPException(status_code=404, detail="Task not found")
    if not task["repo_local_path"]:
        conn.close()
        raise HTTPException(status_code=400, detail="Repository not analyzed yet. Run analyze-repo first.")

    diagnosis = json.loads(task["debug_diagnosis"]) if task["debug_diagnosis"] else None

    try:
        result = write_code(
            task["task_description"], task["repo_local_path"],
            json.loads(task["repo_file_list"]), diagnosis
        )
    except ValueError as e:
        conn.close()
        raise HTTPException(status_code=502, detail=str(e))

    cursor.execute(
        "UPDATE tasks SET code_changes = ?, code_summary = ?, code_written_at = ? WHERE id = ?",
        (json.dumps(result["files_changed"]), result["overall_summary"],
         datetime.utcnow().isoformat(), task_id)
    )
    conn.commit()
    conn.close()
    return {"task_id": task_id, **result}

@app.post("/tasks/{task_id}/test")
def test_task(task_id: int):
    conn = get_connection()
    cursor = conn.cursor()
    cursor.execute("SELECT * FROM tasks WHERE id = ?", (task_id,))
    task = cursor.fetchone()

    if task is None:
        conn.close()
        raise HTTPException(status_code=404, detail="Task not found")
    if not task["code_changes"]:
        conn.close()
        raise HTTPException(status_code=400, detail="No code changes to test yet. Run /code first.")

    diagnosis = json.loads(task["debug_diagnosis"]) if task["debug_diagnosis"] else None
    changed_files = json.loads(task["code_changes"])

    try:
        results = test_changes(
            task["task_description"], diagnosis, task["repo_local_path"], changed_files
        )
    except ValueError as e:
        conn.close()
        raise HTTPException(status_code=502, detail=str(e))

    cursor.execute(
        "UPDATE tasks SET test_results = ?, test_verdict = ?, tested_at = ? WHERE id = ?",
        (json.dumps(results), results["final_verdict"], datetime.utcnow().isoformat(), task_id)
    )
    conn.commit()
    conn.close()
    return {"task_id": task_id, **results}

@app.post("/tasks/{task_id}/explain")
def explain_task(task_id: int):
    conn = get_connection()
    cursor = conn.cursor()
    cursor.execute("SELECT * FROM tasks WHERE id = ?", (task_id,))
    task = cursor.fetchone()

    if task is None:
        conn.close()
        raise HTTPException(status_code=404, detail="Task not found")
    if not task["code_changes"]:
        if task["task_type"] != "documentation_only":
            conn.close()
            raise HTTPException(status_code=400, detail="No code changes to explain yet. Run /code first.")

        # documentation_only task with no code changes: nothing for the
        # Explainability Agent to synthesize yet (the Documentation Agent
        # runs next and produces the actual answer). Store a clear no-op
        # explanation instead of erroring, so the pipeline can continue.
        stub_explanation = {
            "root_cause": "N/A - not a bug fix",
            "files_modified": [],
            "changes_made": "N/A - this is an informational task with no code changes.",
            "reason": task["task_description"],
            "impact": "No code impact; this task provides information about the project.",
            "confidence": "high",
            "confidence_justification": "No code was changed, so there is nothing to assess for correctness.",
        }
        cursor.execute(
            "UPDATE tasks SET explanation = ?, explained_at = ? WHERE id = ?",
            (json.dumps(stub_explanation), datetime.utcnow().isoformat(), task_id)
        )
        conn.commit()
        conn.close()
        return {"task_id": task_id, **stub_explanation}

    diagnosis = json.loads(task["debug_diagnosis"]) if task["debug_diagnosis"] else None
    code_result = {
        "files_changed": json.loads(task["code_changes"]),
        "overall_summary": task["code_summary"],
    }
    test_result = json.loads(task["test_results"]) if task["test_results"] else None

    try:
        explanation = generate_explanation(
            task["task_description"], task["task_type"], diagnosis, code_result, test_result
        )
    except ValueError as e:
        conn.close()
        raise HTTPException(status_code=502, detail=str(e))

    cursor.execute(
        "UPDATE tasks SET explanation = ?, explained_at = ? WHERE id = ?",
        (json.dumps(explanation), datetime.utcnow().isoformat(), task_id)
    )
    conn.commit()
    conn.close()
    return {"task_id": task_id, **explanation}

@app.post("/tasks/{task_id}/document")
def document_task(task_id: int):
    conn = get_connection()
    cursor = conn.cursor()
    cursor.execute("SELECT * FROM tasks WHERE id = ?", (task_id,))
    task = cursor.fetchone()

    if task is None:
        conn.close()
        raise HTTPException(status_code=404, detail="Task not found")
    if not task["code_changes"]:
        if task["task_type"] != "documentation_only":
            conn.close()
            raise HTTPException(status_code=400, detail="No code changes to document yet. Run /code first.")

        # documentation_only task with no code changes: this is a question
        # about the existing project, not a summary of a diff.
        try:
            result = answer_project_question(
                task["task_description"], task["repo_local_path"], json.loads(task["repo_file_list"])
            )
        except ValueError as e:
            conn.close()
            raise HTTPException(status_code=502, detail=str(e))

        cursor.execute(
            "UPDATE tasks SET doc_results = ?, changelog_entry = ?, documented_at = ? WHERE id = ?",
            (json.dumps(result["files_documented"]), result["changelog_entry"],
             datetime.utcnow().isoformat(), task_id)
        )
        conn.commit()
        conn.close()
        return {"task_id": task_id, "answer": result["answer"], "files_documented": result["files_documented"]}

    changed_files = json.loads(task["code_changes"])

    try:
        result = document_changes(task["task_description"], task["repo_local_path"], changed_files)
    except ValueError as e:
        conn.close()
        raise HTTPException(status_code=502, detail=str(e))

    cursor.execute(
        "UPDATE tasks SET doc_results = ?, changelog_entry = ?, documented_at = ? WHERE id = ?",
        (json.dumps(result["files_documented"]), result["changelog_entry"],
         datetime.utcnow().isoformat(), task_id)
    )
    conn.commit()
    conn.close()
    return {"task_id": task_id, **result}

@app.post("/tasks/{task_id}/submit-github")
def submit_github(task_id: int):
    conn = get_connection()
    cursor = conn.cursor()
    cursor.execute("SELECT * FROM tasks WHERE id = ?", (task_id,))
    task = cursor.fetchone()

    if task is None:
        conn.close()
        raise HTTPException(status_code=404, detail="Task not found")
    if not task["code_changes"] and task["task_type"] != "documentation_only":
        conn.close()
        raise HTTPException(status_code=400, detail="No code changes to submit. Run /code first.")

    changed_files = json.loads(task["code_changes"]) if task["code_changes"] else []
    doc_files = json.loads(task["doc_results"]) if task["doc_results"] else []

    has_committable_files = bool(changed_files) or any(f.get("written") for f in doc_files)
    if not has_committable_files:
        cursor.execute("UPDATE tasks SET status = 'completed' WHERE id = ?", (task_id,))
        conn.commit()
        conn.close()
        return {
            "task_id": task_id,
            "message": "No file changes were made for this task, so nothing was committed. Task marked complete.",
            "pr_url": None,
        }

    has_committable_files = bool(changed_files) or any(f.get("written") for f in doc_files)
    if not has_committable_files:
        cursor.execute("UPDATE tasks SET status = 'completed' WHERE id = ?", (task_id,))
        conn.commit()
        conn.close()
        return {
            "task_id": task_id,
            "message": "No file changes were made for this task, so nothing was committed. Task marked complete.",
            "pr_url": None,
        }

    try:
        result = submit_to_github(
            task["repo_url"], task["repo_local_path"], task_id,
            task["task_description"], task["changelog_entry"] or "AI-generated fix",
            changed_files, doc_files, task["task_type"], task["reasoning"]
        )
    except ValueError as e:
        conn.close()
        raise HTTPException(status_code=502, detail=str(e))

    cursor.execute(
        """UPDATE tasks
           SET github_branch = ?, github_pr_url = ?, github_pr_number = ?,
               github_submitted_at = ?, status = 'completed'
           WHERE id = ?""",
        (result["branch_name"], result["pr_url"], result["pr_number"],
         datetime.utcnow().isoformat(), task_id)
    )
    conn.commit()
    conn.close()
    return {"task_id": task_id, **result}

@app.get("/logs")
def view_logs(limit: int = 50):
    return {"logs": get_recent_logs(limit)}

@app.get("/tasks/{task_id}/diff")
def get_task_diff(task_id: int):
    conn = get_connection()
    cursor = conn.cursor()
    cursor.execute("SELECT * FROM tasks WHERE id = ?", (task_id,))
    task = cursor.fetchone()
    conn.close()

    if task is None:
        raise HTTPException(status_code=404, detail="Task not found")
    if not task["code_changes"]:
        raise HTTPException(status_code=400, detail="No code changes yet for this task.")

    changed_files = json.loads(task["code_changes"])
    diffs = build_file_diff(task["repo_local_path"], changed_files)
    return {"task_id": task_id, "diffs": diffs}

@app.delete("/tasks/{task_id}")
def delete_task(task_id: int):
    conn = get_connection()
    cursor = conn.cursor()
    cursor.execute("SELECT id FROM tasks WHERE id = ?", (task_id,))
    if cursor.fetchone() is None:
        conn.close()
        raise HTTPException(status_code=404, detail="Task not found")

    cursor.execute("DELETE FROM tasks WHERE id = ?", (task_id,))
    conn.commit()
    conn.close()
    return {"task_id": task_id, "deleted": True}