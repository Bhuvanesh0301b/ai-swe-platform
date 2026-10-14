from core.llm_client import ask_llm
from core.json_utils import extract_json

VALID_AGENTS = [
    "repository_agent",
    "debugging_agent",
    "coding_agent",
    "testing_agent",
    "documentation_agent",
    "github_agent",
]

PLANNER_SYSTEM_PROMPT = """You are the Planner Agent in an autonomous software engineering system.

Given a developer's task description, you must:
1. Classify the task into exactly one type: "bug_fix", "add_feature", "modify_feature", "remove_feature", "refactor", or "documentation_only".
2. Decide which agents are needed to complete it, in execution order, chosen ONLY from this list:
   repository_agent, debugging_agent, coding_agent, testing_agent, documentation_agent, github_agent
3. Give a short reasoning (2-3 sentences) explaining your choices.

Rules for agent selection:
- repository_agent almost always runs first (to understand the codebase), unless the task is purely conversational.
- debugging_agent is only needed for "bug_fix" tasks.
- coding_agent is needed for bug_fix, add_feature, modify_feature, remove_feature, refactor (NOT for documentation_only).
- testing_agent runs after coding_agent whenever code was changed.
- documentation_agent runs when docs need updating (always include it if coding_agent ran, plus for documentation_only tasks).
- github_agent runs last, whenever any repository changes were made (skip it only for documentation_only... no wait, docs updates still need github_agent to commit/push/PR).

Respond with ONLY a valid JSON object in this exact format, no other text, no markdown code fences:
{
  "task_type": "bug_fix",
  "agent_sequence": ["repository_agent", "debugging_agent", "coding_agent", "testing_agent", "documentation_agent", "github_agent"],
  "reasoning": "short explanation here"
}
"""



def generate_plan(task_description: str) -> dict:
    """
    Calls the LLM to classify the task and produce an execution plan.
    Returns a dict with task_type, agent_sequence, reasoning.
    Raises ValueError if the LLM response can't be parsed or is invalid.
    """
    raw_response = ask_llm(
        prompt=f"Developer task: {task_description}",
        system_prompt=PLANNER_SYSTEM_PROMPT,
    )

    try:
        plan = extract_json(raw_response)
    except json.JSONDecodeError as e:
        raise ValueError(f"Planner Agent returned invalid JSON: {raw_response}") from e

    required_keys = {"task_type", "agent_sequence", "reasoning"}
    if not required_keys.issubset(plan.keys()):
        raise ValueError(f"Planner Agent response missing required keys: {plan}")

    invalid_agents = [a for a in plan["agent_sequence"] if a not in VALID_AGENTS]
    if invalid_agents:
        raise ValueError(f"Planner Agent returned unknown agents: {invalid_agents}")

    return plan