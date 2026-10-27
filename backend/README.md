# Python Compiler Execution Backend

A lightweight, dedicated FastAPI execution service for the **Compiler Optimization Using Genetic Algorithm** project.

This service executes user-submitted Python code via a managed subprocess, capturing real execution output, standard errors, return codes, and execution duration.

---

## 1. Quick Start

### Prerequisites
- Python 3.9+
- `pip`
- LLVM `clang` and `opt` (Homebrew macOS: `brew install llvm`)

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

## 3. LLVM Genetic Optimization

The FastAPI app started with `uvicorn main:app` also exposes the compilation
routes. Run C code first to create a `p_id`, then send `POST /optimize` with
`{"p_id":"<job-id>"}`. The route uses the modular engine in `app/ga/`:
chromosomes contain ordered native LLVM new-pass-manager identifiers, and every
candidate starts from the same pristine `-O0` LLVM IR. Candidates are applied
through the installed `opt` executable, compiled with Clang, executed under the
bounded process runner, and accepted only after output, stderr, exit status,
timeout, and compilation checks agree with the original program.
`GET /tac/{p_id}` retrieves the source and saved optimization results.

The response contains the initial population, candidate evaluations, per-pass
requested/executed/IR-changed diagnostics, generation history, the global best
chromosome, actual LLVM IR and assembly, and independent `-O0`, `-O1`, `-O2`,
and `-O3` measurements. The GA uses tournament selection, one-point crossover,
replace/insert/remove mutation, elitism, a reproducible seed, and a per-run
cache keyed by source, toolchain, sequence, objective, and benchmark settings.

The pass registry currently exposes `simplifycfg`, `instcombine`, `sroa`,
`early-cse`, `reassociate`, `gvn`, `dce`, `adce`, `loop-simplify`, `licm`, and
`indvars`. It is checked against `opt --print-passes` at runtime, so an
unsupported toolchain fails explicitly instead of being represented as a
successful transformation. TAC generation remains a separate diagnostic/viewer
feature; TAC pass names are not LLVM chromosomes.

Incorrect candidates receive no fitness, and the original executable remains
the baseline when no equivalent candidate measurably improves the objective.
The displayed objective values are measured runtime or bytes, not reciprocal
fitness scores.

Configuration is supplied through environment variables:

| Variable | Default | Meaning |
| --- | --- | --- |
| `GA_POPULATION_SIZE` | `6` | Candidate count per generation (minimum 2) |
| `GA_GENERATIONS` | `3` | Number of GA generations |
| `GA_MAX_CHROMOSOME_LENGTH` | `5` | Maximum native LLVM passes in a candidate |
| `GA_BENCHMARK_RUNS` | `3` | Repeated executions for each benchmark |
| `GA_OBJECTIVE` | `execution_time` | `binary_size` or `execution_time` |
| `GA_MUTATION_PROBABILITY` | `0.35` | Mutation probability |
| `GA_RANDOM_SEED` | `0` | Reproducible seed; empty disables seeding |
| `GA_TOURNAMENT_SIZE` | `3` | Tournament parent count |

Native optimization requires a compatible LLVM `clang`/`opt` pair. On macOS,
install it with `brew install llvm`; the backend automatically detects the
standard Homebrew paths. Set `LLVM_CLANG` and `LLVM_OPT` explicitly when using
another installation. The API returns an error explaining a missing tool
rather than falling back to TAC or pretending that a pass ran.

The existing `optimization_runs.original_tac` and `optimized_tac` columns contain
JSON-serialized TAC instruction arrays. Since the schema has no separate GA
metadata column, `optimized_code` stores a JSON envelope containing assembly
and LLVM GA metadata; the API unwraps that field for the frontend. LLVM IR is
returned separately as `original_llvm_ir` and `optimized_llvm_ir`.

Program runs in the C, Python, and optimization paths are subject to CPU,
output-file, open-file, process-group, and wall-clock limits. This is not a
complete OS sandbox: the inspected macOS runtime does not support the attempted
address-space limit, and these processes are not isolated from filesystem or
network access. Do not expose the service to untrusted production submissions
without external sandboxing.

## 4. Safeguards & Security Notice

### Current Prototyping Safeguards
- **Max Source Code Size**: 50 KB (`MAX_SOURCE_SIZE_BYTES = 50 * 1024`).
- **Execution Timeout**: 5.0 seconds (`TIMEOUT_SECONDS = 5.0`).
- **Bounded Output**: Captured stdout and stderr are each capped at 100 KB (`MAX_OUTPUT_BYTES = 100 * 1024`) by the shared subprocess runner.
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
