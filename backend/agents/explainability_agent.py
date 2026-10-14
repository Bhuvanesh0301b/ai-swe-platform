import json
from core.llm_client import ask_llm
from core.json_utils import extract_json

EXPLAINABILITY_SYSTEM_PROMPT = """You are the Explainability Agent in an autonomous software engineering system.
You do NOT analyze code yourself. Your job is to SYNTHESIZE the outputs already produced by other
agents (Planner, Debugging, Coding, Testing) into a single, clear, human-readable report that a
developer could read to fully understand what happened and why, without needing to read the code.

CRITICAL ACCURACY RULE: only reference an agent's involvement if the input explicitly confirms
that agent ran. If the Debugging Agent output says it did not run, do NOT mention debugging,
root cause analysis, or bug diagnosis anywhere in your response, including in the confidence
justification. Referencing a step that didn't happen is a factual error.

Respond with ONLY valid JSON, no markdown fences:
{
  "root_cause": "plain-English root cause, or 'N/A - not a bug fix' if this was a feature/docs task",
  "files_modified": ["list", "of", "file", "paths"],
  "changes_made": "2-4 sentence plain-English description of what was actually changed",
  "reason": "why this change was necessary, in plain English",
  "impact": "what this change affects - both the fix/feature itself and any risk to unrelated functionality",
  "confidence": "high, medium, or low - how confident you are this change is correct and complete",
  "confidence_justification": "1-2 sentences explaining the confidence level, referencing the test verdict if available"
}
"""


def generate_explanation(task_description: str, task_type: str,
                          diagnosis: dict | None, code_result: dict,
                          test_result: dict | None) -> dict:
    """
    Synthesizes a structured, human-readable explanation of a completed change
    by combining the outputs of the Debugging, Coding, and Testing agents.
    Does not re-read source code - operates purely on prior agent outputs,
    keeping this fast and cheap (one LLM call, small context).
    """
    diagnosis_context = "The Debugging Agent did NOT run for this task (not a bug-fix task) - do not reference debugging in your confidence justification."
    if diagnosis:
        diagnosis_context = f"""The Debugging Agent DID run and found:
Root cause identified: {diagnosis['root_cause']}
Location: {diagnosis['buggy_file']} - {diagnosis['buggy_location']}
Fix approach taken: {diagnosis['fix_approach']}
Debugging confidence: {diagnosis['confidence']}"""

    files_summary = "\n".join(
        f"- {f['path']}: {f.get('summary', 'no summary provided')}"
        for f in code_result.get("files_changed", [])
    )

    test_context = "No test results available."
    if test_result:
        syntax_ok = test_result.get("syntax_check", {}).get("all_passed")
        llm_verdict = test_result.get("llm_review", {}).get("verdict") if test_result.get("llm_review") else None
        issues = test_result.get("llm_review", {}).get("issues_found", []) if test_result.get("llm_review") else []
        test_context = f"""Syntax check passed: {syntax_ok}
Test verdict: {llm_verdict}
Issues found during review: {issues if issues else "none"}"""

    root_cause_instruction = (
        "This task_type is 'bug_fix', so provide a real root_cause based on the debugging output below."
        if task_type == "bug_fix"
        else f"This task_type is '{task_type}', NOT a bug fix. You MUST set root_cause to exactly "
             f"'N/A - not a bug fix' - do not invent a technical root cause narrative for non-bug tasks."
    )

    prompt = f"""Task: {task_description}
Task type: {task_type}
{root_cause_instruction}

Debugging Agent output:
{diagnosis_context}

Coding Agent output:
Overall summary: {code_result.get('overall_summary', 'N/A')}
Files changed:
{files_summary}

Testing Agent output:
{test_context}
"""

    raw_response = None
    explanation = None
    last_error = None

    for attempt in range(2):
        temperature = 0.2 if attempt == 0 else 0.6
        raw_response = ask_llm(
            prompt=prompt, system_prompt=EXPLAINABILITY_SYSTEM_PROMPT,
            max_tokens=2048, temperature=temperature,
            agent_name="explainability_agent",
        )
        try:
            explanation = extract_json(raw_response)
            break
        except json.JSONDecodeError:
            last_error = f"Invalid JSON: {raw_response[:500]}..."
            continue
    else:
        raise ValueError(f"Explainability Agent failed after retry. Last error: {last_error}")

    required_keys = {"root_cause", "files_modified", "changes_made", "reason",
                      "impact", "confidence", "confidence_justification"}
    if not required_keys.issubset(explanation.keys()):
        raise ValueError(f"Explainability Agent response missing required keys: {explanation}")

    return explanation