
import os
import subprocess
import tempfile
import time

from app.limited_process import run_limited_process
from app.ga.llvm_runner import LLVMToolchainError, find_clang


def execute_c(source_code: str) -> dict:
    """Compile and execute C code using Clang."""

    try:
        clang_path = find_clang()
    except LLVMToolchainError:
        return {
            "output": "",
            "stderr": "Clang compiler was not found.",
            "exit_code": -1,
            "execution_time_ms": 0,
            "status": "compiler_unavailable",
        }

    with tempfile.TemporaryDirectory(prefix="genetic_compiler_") as temp_dir:
        source_path = os.path.join(temp_dir, "program.c")
        executable_path = os.path.join(temp_dir, "program")

        with open(source_path, "w", encoding="utf-8") as file:
            file.write(source_code)

        # Compile C code
        compile_start = time.perf_counter()

        try:
            compilation = subprocess.run(
                [
                    clang_path,
                    "-std=c11",
                    "-O0",
                    source_path,
                    "-o",
                    executable_path,
                ],
                capture_output=True,
                text=True,
                timeout=15,
                check=False,
            )
        except subprocess.TimeoutExpired:
            return {
                "output": "",
                "stderr": "Compilation timed out after 15 seconds.",
                "exit_code": -1,
                "execution_time_ms": round(
                    (time.perf_counter() - compile_start) * 1000
                ),
                "status": "compile_timeout",
            }
        except OSError as exc:
            return {
                "output": "",
                "stderr": f"Unable to start Clang: {exc}",
                "exit_code": -1,
                "execution_time_ms": round((time.perf_counter() - compile_start) * 1000),
                "status": "compiler_unavailable",
            }

        compilation_time_ms = round(
            (time.perf_counter() - compile_start) * 1000
        )

        # Stop if compilation failed
        if compilation.returncode != 0:
            return {
                "output": "",
                "stderr": compilation.stderr,
                "exit_code": compilation.returncode,
                "execution_time_ms": compilation_time_ms,
                "status": "compile_failed",
            }

        execution = run_limited_process(
            [executable_path],
            temp_dir,
            timeout_seconds=5,
            max_output_bytes=1024 * 1024,
        )
        if execution["timed_out"]:
            return {
                "output": "",
                "stderr": "Execution timed out after 5 seconds.",
                "exit_code": -1,
                "execution_time_ms": round(execution["execution_time_ms"]),
                "status": "timeout",
            }
        if execution["output_limited"]:
            return {
                "output": execution["stdout"],
                "stderr": execution["stderr"],
                "exit_code": -1,
                "execution_time_ms": round(execution["execution_time_ms"]),
                "status": "error",
            }

        return {
            "output": execution["stdout"],
            "stderr": execution["stderr"],
            "exit_code": execution["exit_code"],
            "execution_time_ms": round(execution["execution_time_ms"]),
            "status": "completed" if execution["exit_code"] == 0 else "runtime_failed",
        }
