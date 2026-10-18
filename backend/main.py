import os
import sys
import time
import shutil
import tempfile
import threading
import subprocess
from typing import Optional

from fastapi import FastAPI, HTTPException, status
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel, Field, field_validator

# ---------------------------------------------------------
# Configuration Constants
# ---------------------------------------------------------
TIMEOUT_SECONDS = 5.0
MAX_SOURCE_SIZE_BYTES = 50 * 1024   # 50 KB limit
MAX_OUTPUT_BYTES = 100 * 1024       # 100 KB limit

# ---------------------------------------------------------
# FastAPI App Initialization & CORS
# ---------------------------------------------------------
app = FastAPI(
    title="Genetic Compiler Python Execution Backend",
    description="Backend service executing real Python code in isolated subprocesses.",
    version="1.0.0",
)

app.add_middleware(
    CORSMiddleware,
    allow_origins=[
        "http://localhost:5173",
        "http://127.0.0.1:5173",
    ],
    allow_credentials=True,
    allow_methods=["GET", "POST", "OPTIONS"],
    allow_headers=["*"],
)


# ---------------------------------------------------------
# Request & Response Models
# ---------------------------------------------------------
class RunRequest(BaseModel):
    language: str = Field(..., description="Target execution language, must be 'python'")
    source_code: str = Field(..., description="Python source code to execute")

    @field_validator("language")
    @classmethod
    def validate_language(cls, v: str) -> str:
        normalized = v.strip().lower()
        if normalized != "python":
            raise ValueError(f"Unsupported language: '{v}'. Only 'python' is supported.")
        return normalized

    @field_validator("source_code")
    @classmethod
    def validate_source_code(cls, v: str) -> str:
        if not v or v.strip() == "":
            raise ValueError("source_code must not be empty.")
        encoded_size = len(v.encode("utf-8"))
        if encoded_size > MAX_SOURCE_SIZE_BYTES:
            raise ValueError(
                f"Source code exceeds maximum allowed size of 50 KB (received {encoded_size} bytes)."
            )
        return v


class RunResponse(BaseModel):
    status: str
    language: str
    stdout: str
    stderr: str
    exit_code: int
    execution_time_ms: float


# ---------------------------------------------------------
# Subprocess Execution Engine with Bounded I/O & Timeout
# ---------------------------------------------------------
def execute_python_code(source_code: str, timeout_sec: float = TIMEOUT_SECONDS) -> RunResponse:
    """
    Executes Python source code in a dedicated temporary file using a separate subprocess.
    Enforces maximum execution timeout and bounded output capture to prevent memory exhaustion.
    """
    temp_dir = tempfile.mkdtemp(prefix="compiler_run_")
    script_path = os.path.join(temp_dir, "submission.py")

    try:
        # Write exact source code without modification
        with open(script_path, "w", encoding="utf-8") as f:
            f.write(source_code)

        stdout_buf = bytearray()
        stderr_buf = bytearray()
        output_limit_exceeded = threading.Event()

        def stream_reader(pipe, buf: bytearray):
            try:
                while True:
                    chunk = pipe.read(4096)
                    if not chunk:
                        break
                    if len(buf) < MAX_OUTPUT_BYTES:
                        remaining = MAX_OUTPUT_BYTES - len(buf)
                        buf.extend(chunk[:remaining])
                    if len(buf) >= MAX_OUTPUT_BYTES:
                        output_limit_exceeded.set()
                        break
            except Exception:
                pass
            finally:
                try:
                    pipe.close()
                except Exception:
                    pass

        start_time = time.perf_counter()

        # Launch unbuffered Python process using sys.executable
        proc = subprocess.Popen(
            [sys.executable, "-u", script_path],
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            cwd=temp_dir,
        )

        t_out = threading.Thread(target=stream_reader, args=(proc.stdout, stdout_buf), daemon=True)
        t_err = threading.Thread(target=stream_reader, args=(proc.stderr, stderr_buf), daemon=True)
        t_out.start()
        t_err.start()

        timed_out = False
        poll_interval = 0.05

        while True:
            retcode = proc.poll()
            elapsed = time.perf_counter() - start_time

            if retcode is not None:
                # Process finished
                break

            if elapsed >= timeout_sec:
                timed_out = True
                try:
                    proc.kill()
                    proc.wait(timeout=1.0)
                except Exception:
                    pass
                break

            if output_limit_exceeded.is_set():
                try:
                    proc.kill()
                    proc.wait(timeout=1.0)
                except Exception:
                    pass
                break

            time.sleep(poll_interval)

        end_time = time.perf_counter()
        execution_time_ms = round((end_time - start_time) * 1000, 2)

        # Allow threads to finalize remaining reads
        t_out.join(timeout=0.3)
        t_err.join(timeout=0.3)

        decoded_stdout = stdout_buf.decode("utf-8", errors="replace")
        decoded_stderr = stderr_buf.decode("utf-8", errors="replace")

        if timed_out:
            timeout_msg = f"Execution timed out after {timeout_sec:.1f} seconds."
            full_stderr = f"{decoded_stderr}\n{timeout_msg}".strip() if decoded_stderr else timeout_msg
            return RunResponse(
                status="timeout",
                language="python",
                stdout=decoded_stdout,
                stderr=full_stderr,
                exit_code=-1,
                execution_time_ms=execution_time_ms,
            )

        if output_limit_exceeded.is_set():
            limit_msg = f"Output limit of {MAX_OUTPUT_BYTES // 1024} KB exceeded. Process terminated."
            full_stderr = f"{decoded_stderr}\n{limit_msg}".strip() if decoded_stderr else limit_msg
            return RunResponse(
                status="error",
                language="python",
                stdout=decoded_stdout,
                stderr=full_stderr,
                exit_code=-1,
                execution_time_ms=execution_time_ms,
            )

        exit_code = proc.returncode if proc.returncode is not None else 0
        run_status = "success" if exit_code == 0 else "error"

        return RunResponse(
            status=run_status,
            language="python",
            stdout=decoded_stdout,
            stderr=decoded_stderr,
            exit_code=exit_code,
            execution_time_ms=execution_time_ms,
        )

    finally:
        # Guarantee cleanup of temporary directory and files
        shutil.rmtree(temp_dir, ignore_errors=True)


# ---------------------------------------------------------
# API Endpoints
# ---------------------------------------------------------
@app.get("/")
def health_check():
    return {
        "service": "Genetic Compiler Backend",
        "status": "online",
        "language": "python",
        "interpreter": sys.version,
    }


@app.post("/run", response_model=RunResponse)
def run_code_endpoint(req: RunRequest):
    """
    Executes Python source code on the backend and returns real execution output.
    """
    try:
        return execute_python_code(req.source_code)
    except Exception as exc:
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"Internal server execution error: {str(exc)}",
        )
