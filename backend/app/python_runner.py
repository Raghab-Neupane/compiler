
import sys

from app.limited_process import run_limited_process

def execute_python(source_code: str) -> dict:
    result = run_limited_process(
        [sys.executable, "-I", "-c", source_code],
        cwd=None,
        timeout_seconds=5,
        max_output_bytes=100 * 1024,
    )
    if result["timed_out"]:
        return {
            "stdout": "",
            "stderr": "Execution timed out after 5 seconds.",
            "exit_code": -1,
            "execution_time_ms": round(result["execution_time_ms"]),
            "status": "timeout",
        }
    if result["output_limited"]:
        return {
            "stdout": result["stdout"],
            "stderr": result["stderr"],
            "exit_code": -1,
            "execution_time_ms": round(result["execution_time_ms"]),
            "status": "error",
        }

    return {
        "stdout": result["stdout"],
        "stderr": result["stderr"],
        "exit_code": result["exit_code"],
        "execution_time_ms": round(result["execution_time_ms"]),
        "status": "completed" if result["exit_code"] == 0 else "failed",
    }
