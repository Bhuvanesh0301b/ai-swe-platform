# AI Software Engineer Platform

An autonomous multi-agent system that takes a plain-English task description and a GitHub
repository URL, then independently diagnoses bugs, writes code, tests it, documents it, and
opens a real pull request — coordinated by 8 specialized AI agents running entirely on
Groq's free-tier cloud API, so it costs nothing and needs no local GPU or heavy RAM.

Built and tested on an 8GB RAM Windows laptop.

---

## What It Does

Give it a task like:

> Repo: `https://github.com/yourname/yourproject`
> Task: `Fix the crash when a folder is missing`

...and it will:

1. **Plan** — classify the task type and decide which agents are actually needed
2. **Analyze** the repository — clone it, detect language/framework/architecture
3. **Debug** — find the root cause (for bug-fix tasks)
4. **Code** — write the actual fix, directly to disk
5. **Test** — validate syntax and run an LLM-based code review
6. **Explain** — produce a plain-English report of what changed and why
7. **Document** — add missing docstrings and a changelog entry
8. **Submit** — commit, push to a new branch, and open a real GitHub pull request

---

## Architecture

```
User submits task ──▶ Planner Agent (decides which agents run, in what order)
                              │
                              ▼
                    Repository Agent (clone + classify)
                              │
                    ┌─────────┴─────────┐
                    ▼                   ▼
            Debugging Agent      (skipped for non-bug tasks)
                    │
                    ▼
              Coding Agent (writes real files, with safety guardrails)
                    │
                    ▼
              Testing Agent (syntax check → LLM review)
                    │
                    ▼
           Explainability Agent (synthesizes a human-readable report)
                    │
                    ▼
           Documentation Agent (docstrings + changelog)
                    │
                    ▼
              GitHub Agent (branch, commit, push, open PR)
```

The Planner Agent genuinely changes which agents run based on the task — e.g. a pure
feature-add task skips the Debugging Agent entirely, since there's nothing to debug.

---

## Tech Stack

| Layer | Technology |
|---|---|
| AI reasoning | Groq API (`llama-3.3-70b-versatile`) — cloud-hosted, no local inference |
| Backend | FastAPI (Python) |
| Database | SQLite |
| Repo operations | GitPython (clone, branch, commit, push) |
| GitHub integration | PyGithub (pull request creation) |
| Frontend | React + Vite |
| Styling | Tailwind CSS v4 |
| Testing | pytest (30+ unit tests on deterministic logic) |

---

## Project Structure

```
ai-swe-platform/
├── backend/
│   ├── agents/              # One file per agent (planner, repository, debugging,
│   │                        # coding, testing, explainability, documentation, github)
│   ├── core/                # config, database, LLM client, JSON utils, diff utils, logging
│   ├── tests/                # pytest suite
│   ├── storage/
│   │   ├── repos/            # cloned repositories (gitignored, working data only)
│   │   ├── logs/              # agent call logs (gitignored)
│   │   └── app.db             # SQLite database (gitignored)
│   ├── main.py               # FastAPI app and all API routes
│   └── requirements.txt
└── frontend/
    ├── src/
    │   └── App.jsx            # Dashboard: task submission, pipeline progress, diff viewer
    └── package.json
```

---

## Setup

### Prerequisites
- Python 3.10+
- Node.js 18+
- Git
- A free [Groq API key](https://console.groq.com)
- A GitHub personal access token with `repo` scope (for the GitHub Agent to push/open PRs)

### Backend

```bash
cd backend
python -m venv venv
venv\Scripts\activate        # Windows
# source venv/bin/activate   # macOS/Linux

pip install -r requirements.txt
```

Create `backend/.env`:
```env
GROQ_API_KEY=your_groq_api_key_here
GITHUB_TOKEN=your_github_personal_access_token_here
LLM_MODEL=llama-3.3-70b-versatile
DATABASE_URL=sqlite:///./storage/app.db
CHROMA_DB_PATH=./storage/chroma_db
```

Run the backend:
```bash
uvicorn main:app --reload
```
Backend runs at `http://127.0.0.1:8000`.

### Frontend

```bash
cd frontend
npm install
npm run dev
```
Dashboard runs at `http://localhost:5173`.

### Running Tests

```bash
cd backend
pytest tests/ -v
```

---

## Usage

1. Open `http://localhost:5173`
2. Enter a public GitHub repository URL you own (needs push access for the GitHub Agent step)
3. Describe the task in plain English
4. Click **Submit Task**
5. Click **Run Full AI Pipeline** on the task card
6. Watch the step tracker as each agent runs — steps the Planner decided aren't needed
   are shown as skipped, not run
7. Once complete, view the code diff, explainability report, and the real PR link

If a step fails partway (e.g. a rate limit), clicking the button again resumes from
where it left off rather than restarting the whole pipeline.

---

## Key Design Decisions

- **Shallow git clones** (`depth=1`) — faster and lighter on disk/RAM than a full clone
- **Automatic `.bak` backups** before any file overwrite, enabling manual rollback
- **Path-boundary enforcement** — the Coding Agent refuses to write outside the cloned
  repository folder, even if the model hallucinates a path traversal
- **Two-tier testing** — a fast, deterministic Python syntax check runs before the more
  expensive LLM code review, so broken code never wastes a review call
- **Resumable pipeline** — every step's completion is tracked in the database, so a
  partial failure (e.g. hitting Groq's rate limit) doesn't require starting over

---

## Known Limitations

- Testing validates syntax and does an LLM code review, but does not execute the code
  (not feasible for repos requiring webcams, GUIs, or trained ML models)
- Framework/project-type detection, while LLM-refined beyond simple heuristics, can still
  be wrong for unusual project layouts
- Groq's free tier caps usage at 100,000 tokens/day — a full pipeline run costs roughly
  7-10 Groq calls, so heavy testing/iteration can exhaust the daily budget
- Single-operator design — no authentication or multi-user support

---

## Verified Results

This system has been used to open real, working pull requests on real repositories,
including a genuine crash fix (missing folder handling) in a Python desktop application —
found, diagnosed, fixed, tested, documented, and submitted entirely autonomously.
