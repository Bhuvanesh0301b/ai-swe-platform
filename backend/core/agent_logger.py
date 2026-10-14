import logging
import time
from pathlib import Path
from contextlib import contextmanager

LOG_DIR = Path(__file__).resolve().parent.parent / "storage" / "logs"
LOG_DIR.mkdir(parents=True, exist_ok=True)
LOG_FILE = LOG_DIR / "agent_calls.log"

logger = logging.getLogger("agent_calls")
logger.setLevel(logging.INFO)

if not logger.handlers:  # avoid duplicate handlers when uvicorn --reload re-imports this module
    file_handler = logging.FileHandler(LOG_FILE, encoding="utf-8")
    file_handler.setFormatter(logging.Formatter("%(asctime)s | %(message)s"))
    logger.addHandler(file_handler)

    console_handler = logging.StreamHandler()
    console_handler.setFormatter(logging.Formatter("[AGENT LOG] %(message)s"))
    logger.addHandler(console_handler)


@contextmanager
def log_llm_call(agent_name: str, task_id: int | None = None):
    """
    Context manager that times an LLM call and logs its outcome (success/failure,
    duration, and token usage if available). Usage:

        with log_llm_call("coding_agent", task_id=8) as ctx:
            response = client.chat.completions.create(...)
            ctx["usage"] = response.usage  # optional, attaches token counts to the log line
    """
    context = {"usage": None}
    start_time = time.monotonic()
    error = None
    try:
        yield context
    except Exception as e:
        error = e
        raise
    finally:
        duration_ms = round((time.monotonic() - start_time) * 1000)
        usage = context.get("usage")
        usage_str = "usage=unavailable"
        if usage is not None:
            usage_str = (
                f"prompt_tokens={getattr(usage, 'prompt_tokens', '?')} "
                f"completion_tokens={getattr(usage, 'completion_tokens', '?')} "
                f"total_tokens={getattr(usage, 'total_tokens', '?')}"
            )
        status = "FAILED" if error else "OK"
        task_str = f"task_id={task_id}" if task_id is not None else "task_id=N/A"
        error_str = f" error={str(error)[:150]}" if error else ""
        logger.info(f"agent={agent_name} {task_str} status={status} duration_ms={duration_ms} {usage_str}{error_str}")


def get_recent_logs(limit: int = 100) -> list[str]:
    """Returns the last `limit` lines from the log file, most recent first."""
    if not LOG_FILE.exists():
        return []
    with open(LOG_FILE, encoding="utf-8") as f:
        lines = f.readlines()
    return [line.strip() for line in lines[-limit:]][::-1]