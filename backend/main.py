import os
import shutil
import sys
import tempfile

from fastapi import FastAPI, HTTPException, status
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel, Field, field_validator

from app.limited_process import run_limited_process
from app.routes import router as compiler_router

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
app.include_router(compiler_router)


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
        with open(script_path, "w", encoding="utf-8") as f:
            f.write(source_code)
        result = run_limited_process(
            [sys.executable, "-I", "-u", script_path],
            cwd=temp_dir,
            timeout_seconds=timeout_sec,
            max_output_bytes=MAX_OUTPUT_BYTES,
        )
        execution_time_ms = round(result["execution_time_ms"], 2)

        if result["timed_out"]:
            timeout_msg = f"Execution timed out after {timeout_sec:.1f} seconds."
            full_stderr = (
                f"{result['stderr']}\n{timeout_msg}".strip()
                if result["stderr"]
                else timeout_msg
            )
            return RunResponse(
                status="timeout",
                language="python",
                stdout=result["stdout"],
                stderr=full_stderr,
                exit_code=-1,
                execution_time_ms=execution_time_ms,
            )

        if result["output_limited"]:
            limit_msg = f"Output limit of {MAX_OUTPUT_BYTES // 1024} KB exceeded. Process terminated."
            full_stderr = (
                f"{result['stderr']}\n{limit_msg}".strip()
                if result["stderr"]
                else limit_msg
            )
            return RunResponse(
                status="error",
                language="python",
                stdout=result["stdout"],
                stderr=full_stderr,
                exit_code=-1,
                execution_time_ms=execution_time_ms,
            )

        exit_code = result["exit_code"]
        run_status = "success" if exit_code == 0 else "error"

        return RunResponse(
            status=run_status,
            language="python",
            stdout=result["stdout"],
            stderr=result["stderr"],
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
