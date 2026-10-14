import sqlite3
import os

DB_PATH = os.path.join(os.path.dirname(os.path.dirname(__file__)), "storage", "app.db")

def get_connection():
    conn = sqlite3.connect(DB_PATH)
    conn.row_factory = sqlite3.Row
    return conn

def _column_exists(cursor, table, column):
    cursor.execute(f"PRAGMA table_info({table})")
    return any(row["name"] == column for row in cursor.fetchall())

def init_db():
    conn = get_connection()
    cursor = conn.cursor()
    cursor.execute("""
        CREATE TABLE IF NOT EXISTS tasks (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            repo_url TEXT NOT NULL,
            task_description TEXT NOT NULL,
            status TEXT DEFAULT 'pending',
            created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
        )
    """)

    # Migration: add plan-related columns if they don't exist yet
    new_columns = {
        "explanation": "TEXT",
        "explained_at": "TIMESTAMP",
        "github_branch": "TEXT",
        "github_pr_url": "TEXT",
        "github_pr_number": "INTEGER",
        "github_submitted_at": "TIMESTAMP",
        "doc_results": "TEXT",
        "changelog_entry": "TEXT",
        "documented_at": "TIMESTAMP",
        "test_results": "TEXT",
        "test_verdict": "TEXT",
        "tested_at": "TIMESTAMP",
        "debug_diagnosis": "TEXT",
        "debug_analyzed_at": "TIMESTAMP",
        "code_changes": "TEXT",
        "code_summary": "TEXT",
        "code_written_at": "TIMESTAMP",
        "repo_project_type": "TEXT",
        "task_type": "TEXT",
        "agent_sequence": "TEXT",
        "reasoning": "TEXT",
        "plan_generated_at": "TIMESTAMP",
        "repo_local_path": "TEXT",
        "repo_language": "TEXT",
        "repo_framework": "TEXT",
        "repo_file_count": "INTEGER",
        "repo_file_list": "TEXT",
        "repo_analyzed_at": "TIMESTAMP",
    }
    for col_name, col_type in new_columns.items():
        if not _column_exists(cursor, "tasks", col_name):
            cursor.execute(f"ALTER TABLE tasks ADD COLUMN {col_name} {col_type}")

    conn.commit()
    conn.close()