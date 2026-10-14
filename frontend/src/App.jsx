import { useState, useEffect } from 'react'
import './index.css'

const API_BASE = "http://127.0.0.1:8000"

const PIPELINE_STEPS = [
  { key: "plan", label: "Plan", endpoint: (id) => `/tasks/${id}/plan`, dataField: "task_type", agentName: null },
  { key: "analyze-repo", label: "Analyze", endpoint: (id) => `/tasks/${id}/analyze-repo`, dataField: "repo_language", agentName: null },
  { key: "debug", label: "Debug", endpoint: (id) => `/tasks/${id}/debug`, dataField: "debug_diagnosis", agentName: "debugging_agent" },
  { key: "code", label: "Code", endpoint: (id) => `/tasks/${id}/code`, dataField: "code_changes", agentName: "coding_agent" },
  { key: "test", label: "Test", endpoint: (id) => `/tasks/${id}/test`, dataField: "test_verdict", agentName: "testing_agent" },
  { key: "explain", label: "Explain", endpoint: (id) => `/tasks/${id}/explain`, dataField: "explanation", agentName: null },
  { key: "document", label: "Document", endpoint: (id) => `/tasks/${id}/document`, dataField: "doc_results", agentName: "documentation_agent" },
  { key: "submit-github", label: "Submit", endpoint: (id) => `/tasks/${id}/submit-github`, dataField: "github_pr_url", agentName: "github_agent" },
]

const taskTypeColors = {
  bug_fix: "bg-rose-500/10 text-rose-300 border-rose-500/20",
  add_feature: "bg-emerald-500/10 text-emerald-300 border-emerald-500/20",
  modify_feature: "bg-sky-500/10 text-sky-300 border-sky-500/20",
  remove_feature: "bg-orange-500/10 text-orange-300 border-orange-500/20",
  refactor: "bg-violet-500/10 text-violet-300 border-violet-500/20",
  documentation_only: "bg-slate-500/10 text-slate-300 border-slate-500/20",
}

const verdictColors = {
  pass: "bg-emerald-500/10 text-emerald-300 border-emerald-500/20",
  pass_with_concerns: "bg-amber-500/10 text-amber-300 border-amber-500/20",
  fail: "bg-rose-500/10 text-rose-300 border-rose-500/20",
}

function Pipeline({ task, isRunning, currentStepKey, failedStepKey }) {
  const agentSequence = task.agent_sequence ? JSON.parse(task.agent_sequence) : null

  return (
    <div className="flex items-center flex-wrap gap-0 mt-4">
      {PIPELINE_STEPS.map((step, idx) => {
        const isDone = !!task[step.dataField]
        const isSkipped = !isDone && step.agentName && agentSequence && !agentSequence.includes(step.agentName)
        const isCurrent = isRunning && currentStepKey === step.key
        const isFailed = failedStepKey === step.key
        const isLast = idx === PIPELINE_STEPS.length - 1

        let nodeStyles = "border-ink-600 bg-ink-800 text-ink-500"
        let dot = "bg-ink-600"
        if (isDone) {
          nodeStyles = "border-teal-500/40 bg-teal-500/10 text-teal-300"
          dot = "bg-teal-400"
        } else if (isFailed) {
          nodeStyles = "border-rose-500/50 bg-rose-500/10 text-rose-300"
          dot = "bg-rose-400"
        } else if (isCurrent) {
          nodeStyles = "border-amber-400/60 bg-amber-400/10 text-amber-300 animate-pulse"
          dot = "bg-amber-400"
        } else if (isSkipped) {
          nodeStyles = "border-ink-700 bg-transparent text-ink-600"
          dot = "bg-ink-700"
        }

        return (
          <div key={step.key} className="flex items-center">
            <div
              title={isSkipped ? `${step.label}: not needed for this task` : step.label}
              className={`flex items-center gap-1.5 px-2.5 py-1 rounded-full border font-mono text-[11px] tracking-wide ${nodeStyles} ${isSkipped ? "line-through decoration-ink-700" : ""}`}
            >
              <span className={`w-1.5 h-1.5 rounded-full ${dot}`} />
              {step.label}
            </div>
            {!isLast && (
              <div className={`h-px w-4 ${isDone ? "bg-teal-500/40" : "bg-ink-700"}`} />
            )}
          </div>
        )
      })}
    </div>
  )
}

function App() {
  const [repoUrl, setRepoUrl] = useState("")
  const [taskDescription, setTaskDescription] = useState("")
  const [tasks, setTasks] = useState([])
  const [loading, setLoading] = useState(false)
  const [message, setMessage] = useState("")
  const [runningTaskId, setRunningTaskId] = useState(null)
  const [currentStepKey, setCurrentStepKey] = useState(null)
  const [failedStep, setFailedStep] = useState({ taskId: null, stepKey: null, error: null })
  const [copiedTaskId, setCopiedTaskId] = useState(null)
  const [openDiffTaskId, setOpenDiffTaskId] = useState(null)
  const [diffData, setDiffData] = useState(null)
  const [diffLoading, setDiffLoading] = useState(false)
  const [confirmDeleteId, setConfirmDeleteId] = useState(null)
  const [deletingId, setDeletingId] = useState(null)

  const fetchTasks = async () => {
    try {
      const res = await fetch(`${API_BASE}/tasks`)
      const data = await res.json()
      setTasks(data)
      return data
    } catch (err) {
      console.error("Failed to fetch tasks:", err)
      return null
    }
  }

  useEffect(() => {
    fetchTasks()
  }, [])

  const handleSubmit = async (e) => {
    e.preventDefault()
    if (!repoUrl || !taskDescription) {
      setMessage("Repository URL and task description are both required.")
      return
    }
    setLoading(true)
    setMessage("")
    try {
      const res = await fetch(`${API_BASE}/tasks`, {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ repo_url: repoUrl, task_description: taskDescription }),
      })
      const data = await res.json()
      setMessage(`Task #${data.task_id} queued.`)
      setRepoUrl("")
      setTaskDescription("")
      fetchTasks()
    } catch (err) {
      setMessage("Could not reach the backend. Is it running?")
      console.error(err)
    } finally {
      setLoading(false)
    }
  }

  const runFullPipeline = async (taskId) => {
    setRunningTaskId(taskId)
    setFailedStep({ taskId: null, stepKey: null, error: null })

    let latestTasks = await fetchTasks()
    let task = latestTasks?.find((t) => t.id === taskId)

    for (const step of PIPELINE_STEPS) {
      if (!task) break
      if (task[step.dataField]) continue

      const agentSequence = task.agent_sequence ? JSON.parse(task.agent_sequence) : null
      if (step.agentName && agentSequence && !agentSequence.includes(step.agentName)) continue

      setCurrentStepKey(step.key)
      try {
        const res = await fetch(`${API_BASE}${step.endpoint(taskId)}`, { method: "POST" })
        if (!res.ok) {
          const errData = await res.json()
          throw new Error(errData.detail || "Unknown error")
        }
        latestTasks = await fetchTasks()
        task = latestTasks?.find((t) => t.id === taskId)
      } catch (err) {
        setFailedStep({ taskId, stepKey: step.key, error: `${step.label} failed: ${err.message}` })
        setRunningTaskId(null)
        setCurrentStepKey(null)
        return
      }
    }

    setRunningTaskId(null)
    setCurrentStepKey(null)
  }

  const handleToggleDiff = async (taskId) => {
    if (openDiffTaskId === taskId) {
      setOpenDiffTaskId(null)
      setDiffData(null)
      return
    }
    setOpenDiffTaskId(taskId)
    setDiffLoading(true)
    setDiffData(null)
    try {
      const res = await fetch(`${API_BASE}/tasks/${taskId}/diff`)
      if (!res.ok) {
        const errData = await res.json()
        throw new Error(errData.detail || "Failed to load diff")
      }
      const data = await res.json()
      setDiffData(data.diffs)
    } catch (err) {
      setDiffData([{ path: "error", lines: [{ type: "context", content: err.message }] }])
    } finally {
      setDiffLoading(false)
    }
  }

  const handleCopyPrLink = (url, taskId) => {
    navigator.clipboard.writeText(url).then(() => {
      setCopiedTaskId(taskId)
      setTimeout(() => setCopiedTaskId(null), 1500)
    })
  }

  const handleDelete = async (taskId) => {
    setDeletingId(taskId)
    try {
      const res = await fetch(`${API_BASE}/tasks/${taskId}`, { method: "DELETE" })
      if (!res.ok) throw new Error("Delete failed")
      setTasks((prev) => prev.filter((t) => t.id !== taskId))
    } catch (err) {
      console.error(err)
    } finally {
      setDeletingId(null)
      setConfirmDeleteId(null)
    }
  }

  return (
    <div className="min-h-screen bg-ink-950 text-ink-100" style={{ fontFamily: "'Inter', sans-serif" }}>
      <div className="max-w-3xl mx-auto px-6 py-12">

        <header className="mb-10">
          <div className="flex items-center gap-2 mb-2">
            <span className="w-2 h-2 rounded-full bg-teal-400 shadow-[0_0_8px_2px_rgba(45,212,191,0.5)]" />
            <span className="font-mono text-[11px] tracking-widest text-teal-400 uppercase">Autonomous pipeline</span>
          </div>
          <h1
            className="text-3xl font-semibold text-ink-50 tracking-tight"
            style={{ fontFamily: "'Space Grotesk', sans-serif" }}
          >
            AI Software Engineer Platform
          </h1>
          <p className="text-ink-400 mt-1.5 text-sm leading-relaxed">
            Point it at a repository, describe the task, and the agents take it from there.
          </p>
        </header>

        <form onSubmit={handleSubmit} className="bg-ink-900 border border-ink-800 rounded-2xl p-6 mb-10 space-y-4">
          <div>
            <label className="block text-xs font-mono uppercase tracking-wide text-ink-500 mb-2">
              Repository URL
            </label>
            <input
              type="text"
              value={repoUrl}
              onChange={(e) => setRepoUrl(e.target.value)}
              placeholder="https://github.com/you/project"
              className="w-full bg-ink-950 border border-ink-700 rounded-lg px-3.5 py-2.5 text-sm text-ink-100 placeholder-ink-600 focus:outline-none focus:ring-1 focus:ring-teal-500/50 focus:border-teal-500/50 transition"
            />
          </div>

          <div>
            <label className="block text-xs font-mono uppercase tracking-wide text-ink-500 mb-2">
              Task
            </label>
            <textarea
              value={taskDescription}
              onChange={(e) => setTaskDescription(e.target.value)}
              placeholder="Fix the crash when the login button is clicked twice"
              rows={3}
              className="w-full bg-ink-950 border border-ink-700 rounded-lg px-3.5 py-2.5 text-sm text-ink-100 placeholder-ink-600 focus:outline-none focus:ring-1 focus:ring-teal-500/50 focus:border-teal-500/50 transition resize-none"
            />
          </div>

          <div className="flex items-center gap-4 pt-1">
            <button
              type="submit"
              disabled={loading}
              className="bg-teal-500 text-ink-950 font-medium text-sm px-5 py-2.5 rounded-lg hover:bg-teal-400 disabled:opacity-40 disabled:cursor-not-allowed transition"
            >
              {loading ? "Submitting…" : "Submit task"}
            </button>
            {message && <p className="text-xs text-ink-500 font-mono">{message}</p>}
          </div>
        </form>

        <div className="flex items-center justify-between mb-4">
          <h2 className="text-xs font-mono uppercase tracking-widest text-ink-500">
            Task history
          </h2>
          <span className="text-xs font-mono text-ink-600">{tasks.length} total</span>
        </div>

        {tasks.length === 0 && (
          <div className="border border-dashed border-ink-800 rounded-2xl p-10 text-center">
            <p className="text-ink-500 text-sm">No tasks yet.</p>
            <p className="text-ink-600 text-xs mt-1">Submit one above to start the pipeline.</p>
          </div>
        )}

        <div className="space-y-3">
          {tasks.map((task) => {
            const isRunning = runningTaskId === task.id
            const agentSequence = task.agent_sequence ? JSON.parse(task.agent_sequence) : null
            const hasFailure = failedStep.taskId === task.id
            const canRun = task.status !== 'completed'
            const isConfirmingDelete = confirmDeleteId === task.id
            const isDeleting = deletingId === task.id

            return (
              <div
                key={task.id}
                className={`bg-ink-900 border border-ink-800 rounded-2xl p-5 transition ${isDeleting ? "opacity-30" : ""}`}
              >
                <div className="flex items-start justify-between gap-4">
                  <div className="min-w-0">
                    <p className="text-xs font-mono text-ink-600 truncate">{task.repo_url}</p>
                    <p className="text-ink-50 font-medium mt-0.5">{task.task_description}</p>
                  </div>

                  {!isConfirmingDelete ? (
                    <button
                      onClick={() => setConfirmDeleteId(task.id)}
                      title="Delete task"
                      className="shrink-0 w-7 h-7 flex items-center justify-center rounded-lg text-ink-600 hover:text-rose-400 hover:bg-rose-500/10 transition"
                    >
                      <svg width="14" height="14" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2">
                        <path d="M3 6h18M8 6V4a2 2 0 0 1 2-2h4a2 2 0 0 1 2 2v2m3 0v14a2 2 0 0 1-2 2H7a2 2 0 0 1-2-2V6h14ZM10 11v6M14 11v6" />
                      </svg>
                    </button>
                  ) : (
                    <div className="shrink-0 flex items-center gap-1.5">
                      <button
                        onClick={() => handleDelete(task.id)}
                        className="text-xs px-2.5 py-1 rounded-lg bg-rose-500 text-ink-950 font-medium hover:bg-rose-400 transition"
                      >
                        Delete
                      </button>
                      <button
                        onClick={() => setConfirmDeleteId(null)}
                        className="text-xs px-2.5 py-1 rounded-lg text-ink-500 hover:text-ink-300 transition"
                      >
                        Cancel
                      </button>
                    </div>
                  )}
                </div>

                <div className="flex flex-wrap items-center gap-1.5 mt-3">
                  <span className={`text-[11px] font-mono px-2 py-0.5 rounded-full border ${task.status === 'completed' ? 'bg-teal-500/10 text-teal-300 border-teal-500/20' : 'bg-ink-800 text-ink-400 border-ink-700'}`}>
                    {task.status}
                  </span>
                  {task.task_type && (
                    <span className={`text-[11px] font-mono px-2 py-0.5 rounded-full border ${taskTypeColors[task.task_type] || "bg-ink-800 text-ink-400 border-ink-700"}`}>
                      {task.task_type}
                    </span>
                  )}
                  {task.test_verdict && (
                    <span className={`text-[11px] font-mono px-2 py-0.5 rounded-full border ${verdictColors[task.test_verdict] || "bg-ink-800 text-ink-400 border-ink-700"}`}>
                      test: {task.test_verdict}
                    </span>
                  )}
                </div>

                {(task.task_type || isRunning || hasFailure) && (
                  <Pipeline
                    task={task}
                    isRunning={isRunning}
                    currentStepKey={currentStepKey}
                    failedStepKey={hasFailure ? failedStep.stepKey : null}
                  />
                )}

                {agentSequence && (
                  <div className="mt-4 bg-ink-950/60 border border-ink-800 rounded-xl p-3.5">
                    <p className="text-[10px] font-mono uppercase tracking-wider text-ink-600 mb-1.5">Reasoning</p>
                    <p className="text-sm text-ink-400 leading-relaxed">{task.reasoning}</p>
                  </div>
                )}

                {task.repo_language && (
                  <p className="text-xs text-ink-600 mt-3 font-mono">
                    {task.repo_language} · {task.repo_framework}
                  </p>
                )}

                {task.code_summary && (
                  <div className="mt-3 bg-ink-950/60 border border-ink-800 rounded-xl p-3.5">
                    <div className="flex items-center justify-between mb-1.5">
                      <p className="text-[10px] font-mono uppercase tracking-wider text-teal-400">Code changes</p>
                      <button
                        onClick={() => handleToggleDiff(task.id)}
                        className="text-[11px] font-mono text-ink-500 hover:text-teal-300 transition"
                      >
                        {openDiffTaskId === task.id ? "hide diff" : "view diff →"}
                      </button>
                    </div>
                    <p className="text-sm text-ink-300 leading-relaxed">{task.code_summary}</p>

                    {openDiffTaskId === task.id && (
                      <div className="mt-3 bg-black/40 rounded-lg overflow-hidden border border-ink-800">
                        {diffLoading && <p className="text-ink-600 text-xs p-3 font-mono">loading diff…</p>}
                        {!diffLoading && diffData && diffData.map((fileDiff, fIdx) => (
                          <div key={fIdx} className="border-b border-ink-800 last:border-b-0">
                            <div className="px-3 py-1.5 bg-ink-900 text-ink-400 text-xs font-mono flex justify-between">
                              <span>{fileDiff.path}</span>
                              {fileDiff.lines_added !== undefined && (
                                <span>
                                  <span className="text-teal-400">+{fileDiff.lines_added}</span>{" "}
                                  <span className="text-rose-400">-{fileDiff.lines_removed}</span>
                                </span>
                              )}
                            </div>
                            <pre className="text-[11px] font-mono p-2 overflow-x-auto">
                              {fileDiff.lines.map((line, lIdx) => {
                                let s = "text-ink-600"
                                if (line.type === "added") s = "text-teal-300 bg-teal-500/5"
                                if (line.type === "removed") s = "text-rose-300 bg-rose-500/5"
                                if (line.type === "hunk_header") s = "text-sky-400"
                                if (line.type === "file_header") s = "text-ink-600"
                                return <div key={lIdx} className={s}>{line.content || " "}</div>
                              })}
                            </pre>
                          </div>
                        ))}
                      </div>
                    )}
                  </div>
                )}

                {task.explanation && (() => {
                  const exp = JSON.parse(task.explanation)
                  return (
                    <div className="mt-3 bg-ink-950/60 border border-ink-800 rounded-xl p-3.5 space-y-1.5">
                      <p className="text-[10px] font-mono uppercase tracking-wider text-amber-400 mb-1">Explanation</p>
                      <p className="text-sm text-ink-300"><span className="text-ink-500">changed:</span> {exp.changes_made}</p>
                      <p className="text-sm text-ink-300"><span className="text-ink-500">impact:</span> {exp.impact}</p>
                      <p className="text-sm text-ink-300">
                        <span className="text-ink-500">confidence:</span> {exp.confidence} — {exp.confidence_justification}
                      </p>
                    </div>
                  )
                })()}

                {task.changelog_entry && (
                  <div className="mt-3 bg-ink-950/60 border border-ink-800 rounded-xl p-3.5">
                    <p className="text-[10px] font-mono uppercase tracking-wider text-sky-400 mb-1.5">Changelog</p>
                    <p className="text-sm text-ink-300">{task.changelog_entry}</p>
                  </div>
                )}

                {task.github_pr_url && (
                  <div className="mt-3 flex items-center gap-2 flex-wrap">
                    <a
                      href={task.github_pr_url}
                      target="_blank"
                      rel="noreferrer"
                      className="text-xs font-mono text-teal-300 hover:text-teal-200 underline decoration-teal-800 underline-offset-2 break-all"
                    >
                      {task.github_pr_url}
                    </a>
                    <button
                      onClick={() => handleCopyPrLink(task.github_pr_url, task.id)}
                      className="text-[11px] font-mono px-2 py-0.5 rounded-full border border-ink-700 text-ink-500 hover:text-teal-300 hover:border-teal-800 transition"
                    >
                      {copiedTaskId === task.id ? "copied" : "copy"}
                    </button>
                  </div>
                )}

                {hasFailure && (
                  <div className="mt-3 bg-rose-500/5 border border-rose-500/20 rounded-xl p-3.5">
                    <p className="text-sm text-rose-300">{failedStep.error}</p>
                  </div>
                )}

                {canRun && (
                  <button
                    onClick={() => runFullPipeline(task.id)}
                    disabled={runningTaskId !== null}
                    className="mt-4 bg-ink-800 border border-ink-700 text-ink-200 text-sm font-medium px-4 py-2 rounded-lg hover:bg-ink-750 hover:border-teal-800 disabled:opacity-40 disabled:cursor-not-allowed transition"
                  >
                    {isRunning
                      ? `Running · ${PIPELINE_STEPS.find((s) => s.key === currentStepKey)?.label || "…"}`
                      : hasFailure
                        ? "Retry from failed step"
                        : task.task_type
                          ? "Resume pipeline"
                          : "Run pipeline"}
                  </button>
                )}
              </div>
            )
          })}
        </div>
      </div>
    </div>
  )
}

export default App