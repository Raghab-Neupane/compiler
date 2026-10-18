# Python Compiler Execution Backend

A lightweight, dedicated FastAPI execution service for the **Compiler Optimization Using Genetic Algorithm** project.

This service executes user-submitted Python code via a managed subprocess, capturing real execution output, standard errors, return codes, and execution duration.

---

## 1. Quick Start

### Prerequisites
- Python 3.9+
- `pip`

### Setup and Running the Backend

From the `backend/` directory:

```bash
# 1. Create a virtual environment
python3 -m venv .venv

# 2. Activate the virtual environment
source .venv/bin/activate

# 3. Install dependencies
pip install -r requirements.txt

# 4. Start the FastAPI server with Uvicorn
uvicorn main:app --reload --host 127.0.0.1 --port 8000
```

The server will be available at `http://127.0.0.1:8000`.

### Running the Frontend

In a separate terminal, navigate to the frontend directory and start the Vite dev server:

```bash
npm run dev
```

The frontend will run at `http://localhost:5173`.

---

## 2. API Specification

### `POST /run`
Executes Python source code and returns the captured output.

#### Request Body:
```json
{
  "language": "python",
  "source_code": "print(10 + 20)"
}
```

#### Successful Response (`200 OK`):
```json
{
  "status": "success",
  "language": "python",
  "stdout": "30\n",
  "stderr": "",
  "exit_code": 0,
  "execution_time_ms": 14.25
}
```

#### Runtime Error Response (`200 OK`):
```json
{
  "status": "error",
  "language": "python",
  "stdout": "",
  "stderr": "Traceback (most recent call last):\n  File \"...\", line 1, in <module>\n    print(10 / 0)\nZeroDivisionError: division by zero\n",
  "exit_code": 1,
  "execution_time_ms": 12.80
}
```

#### Timeout Response (`200 OK`):
```json
{
  "status": "timeout",
  "language": "python",
  "stdout": "",
  "stderr": "Execution timed out after 5.0 seconds.",
  "exit_code": -1,
  "execution_time_ms": 5005.12
}
```

---

## 3. Safeguards & Security Notice

### Current Prototyping Safeguards
- **Max Source Code Size**: 50 KB (`MAX_SOURCE_SIZE_BYTES = 50 * 1024`).
- **Execution Timeout**: 5.0 seconds (`TIMEOUT_SECONDS = 5.0`).
- **Bounded Output Stream**: Output capture is capped at 100 KB (`MAX_OUTPUT_BYTES = 100 * 1024`) during streaming to prevent buffer and memory exhaustion.
- **Dedicated Subprocess**: Each execution spawns a clean `sys.executable` subprocess in a temporary directory.
- **Temporary Cleanup**: The temporary `.py` script and its enclosing directory are automatically purged upon completion.
- **CORS Restricted**: Allowed origins are restricted to `http://localhost:5173` and `http://127.0.0.1:5173`.

### ⚠️ Security & Sandboxing Limitations
> **IMPORTANT SECURITY ADVISORY**: This backend prototype runs Python scripts directly under the host operating system permissions of the running backend process. 
> 
> **It is NOT a fully sandboxed multi-tenant environment.** Submitted code can potentially read accessible files, read environment variables, or attempt network requests permitted by the host OS.
>
> **Production Deployment Recommendation:**
> Before exposing this execution endpoint publicly or to untrusted users, code execution **must** be isolated inside an ephemeral container or secure sandbox technology with strict limits:
> - Containerization (Docker / OCI container per execution)
> - MicroVMs or sandboxes (e.g., [gVisor](https://gvisor.dev/), [Firecracker](https://firecracker-microvm.github.io/))
> - Seccomp syscall filtering and cgroups resource limits (CPU, memory, PIDs)
> - Complete network isolation (`--network none`)
> - Read-only root filesystem with ephemeral tmpfs
