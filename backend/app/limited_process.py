import math
import os
import signal
import subprocess
import sys
import tempfile
import time
from typing import Any, Dict, List, Optional


DEFAULT_MEMORY_LIMIT_BYTES = 512 * 1024 * 1024


def run_limited_process(
    command: List[str],
    cwd: Optional[str],
    timeout_seconds: float,
    max_output_bytes: int,
    memory_limit_bytes: int = DEFAULT_MEMORY_LIMIT_BYTES,
) -> Dict[str, Any]:
    process_command = command
    if os.name == "posix":
        cpu_seconds = max(1, math.ceil(timeout_seconds))
        wrapper = (
            "import os,resource,sys\n"
            "cpu=int(sys.argv[1])\n"
            "resource.setrlimit(resource.RLIMIT_CPU,(cpu,cpu+1))\n"
            "resource.setrlimit(resource.RLIMIT_FSIZE,(int(sys.argv[2]),int(sys.argv[2])))\n"
            "resource.setrlimit(resource.RLIMIT_NOFILE,(64,64))\n"
            "resource.setrlimit(resource.RLIMIT_CORE,(0,0))\n"
            "try:\n"
            "    resource.setrlimit(resource.RLIMIT_AS,(int(sys.argv[3]),int(sys.argv[3])))\n"
            "except (ValueError,OSError):\n"
            "    pass\n"
            "os.execv(sys.argv[4],sys.argv[4:])\n"
        )
        process_command = [
            sys.executable,
            "-I",
            "-c",
            wrapper,
            str(cpu_seconds),
            str(max_output_bytes),
            str(memory_limit_bytes),
        ] + command

    with tempfile.TemporaryFile() as stdout_file, tempfile.TemporaryFile() as stderr_file:
        start = time.perf_counter()
        try:
            process = subprocess.Popen(
                process_command,
                cwd=cwd,
                stdin=subprocess.DEVNULL,
                stdout=stdout_file,
                stderr=stderr_file,
                start_new_session=os.name == "posix",
            )
        except OSError as exc:
            return {
                "exit_code": -1,
                "stdout": "",
                "stderr": f"Unable to start process: {exc}",
                "execution_time_ms": 0.0,
                "timed_out": False,
                "output_limited": False,
            }
        timed_out = False
        try:
            exit_code = process.wait(timeout=timeout_seconds)
        except subprocess.TimeoutExpired:
            timed_out = True
            if os.name == "posix":
                try:
                    os.killpg(process.pid, signal.SIGKILL)
                except ProcessLookupError:
                    pass
            else:
                process.kill()
            exit_code = process.wait()
        execution_time_ms = (time.perf_counter() - start) * 1000

        stdout_size = os.fstat(stdout_file.fileno()).st_size
        stderr_size = os.fstat(stderr_file.fileno()).st_size
        stdout_file.seek(0)
        stderr_file.seek(0)
        stdout = stdout_file.read(max_output_bytes).decode("utf-8", errors="replace")
        stderr = stderr_file.read(max_output_bytes).decode("utf-8", errors="replace")

    output_limited = (
        stdout_size >= max_output_bytes or stderr_size >= max_output_bytes
    )
    if output_limited:
        stderr = (stderr + "\nOutput limit exceeded.").strip()
    return {
        "exit_code": exit_code,
        "stdout": stdout,
        "stderr": stderr,
        "execution_time_ms": execution_time_ms,
        "timed_out": timed_out,
        "output_limited": output_limited,
    }
