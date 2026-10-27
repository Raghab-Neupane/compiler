import uuid

from fastapi import APIRouter, HTTPException
from mysql.connector import Error

from app.clang_runner import execute_c
from app.schemas import CodeRequest, CodeResponse, OptimizationRequest
from app.database import (
    get_compilation_job,
    get_optimization_result,
    get_original_tac,
    save_job,
    save_optimization_run,
    save_original_tac,
    update_job,
)
from app.python_runner import execute_python
from app.tac_generator import TacGenerationError, generate_tac
from app.llvm_optimizer import OptimizationError, optimize_c

router = APIRouter()


@router.post("/execute", response_model=CodeResponse)
def receive_code(request: CodeRequest):
    language = request.language.strip().lower()

    try:
        intermediate_representation = generate_tac(request.source_code, language)
    except TacGenerationError as exc:
        # TAC is an optional diagnostic view. It must not prevent valid C from
        # reaching the real Clang/LLVM execution and optimization pipeline.
        if language == "c":
            intermediate_representation = []
        else:
            raise HTTPException(status_code=422, detail=str(exc))

    # 1. Execute using the correct language runner.
    if language == "c":
        result = execute_c(request.source_code)
    elif language == "python":
        result = execute_python(request.source_code)
    else:
        raise HTTPException(
            status_code=400,
            detail=(
                f"Unsupported language: {request.language}. "
                "Only C and Python are supported."
            ),
        )

    p_id = str(uuid.uuid4())

    # 2. Save the source code.
    try:
        save_job(
            p_id,
            language,
            request.source_code,
        )
    except Error:
        raise HTTPException(
            status_code=500,
            detail="Failed to save source code to MySQL.",
        )

    try:
        save_original_tac(
            p_id,
            intermediate_representation,
        )
    except Error:
        raise HTTPException(
            status_code=500,
            detail=f"Code executed, but saving TAC failed. Job ID: {p_id}",
        )

    # 3. Normalize output keys across both runners.
    output = result.get("output", result.get("stdout", ""))

    # 4. Save the execution result.
    try:
        update_job(
            p_id=p_id,
            stdout=output,
            stderr=result["stderr"],
            exit_code=result["exit_code"],
            execution_time_ms=result["execution_time_ms"],
            status=result["status"],
        )
    except Error:
        raise HTTPException(
            status_code=500,
            detail=(
                "Execution finished, but saving the result failed. "
                f"Job ID: {p_id}"
            ),
        )

    # 5. Return the response.
    return CodeResponse(
        p_id=p_id,
        message=(
            "Code executed successfully."
            if result["status"] == "completed"
            else "Code execution did not complete successfully."
        ),
        language=language,
        output=output,
        stderr=result["stderr"],
        exit_code=result["exit_code"],
        execution_time_ms=result["execution_time_ms"],
        status=result["status"],
    )


@router.get("/tac/{p_id}")
def retrieve_tac(p_id: str):
    try:
        result = get_optimization_result(p_id)
    except Error:
        raise HTTPException(
            status_code=500,
            detail="Failed to retrieve compiler results from MySQL.",
        )

    if result is None:
        raise HTTPException(status_code=404, detail="Compilation job not found.")

    metadata = result.pop("optimization_metadata", {})
    if result["language"] == "c":
        if isinstance(result.get("original_tac"), str):
            result["original_tac"] = generate_tac(result["source_code"], "c")
            try:
                save_original_tac(p_id, result["original_tac"])
            except Error:
                raise HTTPException(
                    status_code=500,
                    detail="Failed to save regenerated TAC for this compilation job.",
                )
        if isinstance(result.get("optimized_tac"), str):
            result["optimized_tac"] = None
            result["equivalent"] = None
            result["optimization_status"] = "legacy"
            metadata = {}
    result["optimization_status"] = result.get("optimization_status") or "pending"
    result.update(metadata)
    result["status"] = result["optimization_status"]
    return result


@router.post("/optimize")
def optimize_job(request: OptimizationRequest):
    p_id = request.p_id

    try:
        job = get_compilation_job(p_id)
    except Error:
        raise HTTPException(status_code=500, detail="Failed to load compilation job.")
    if job is None:
        raise HTTPException(status_code=404, detail="Compilation job not found.")
    if job["language"] != "c":
        raise HTTPException(
            status_code=400,
            detail="LLVM IR genetic optimization is currently supported for C jobs only.",
        )
    if job.get("status") in {
        "compile_failed",
        "compiler_unavailable",
        "compile_timeout",
        "timeout",
        "error",
    }:
        raise HTTPException(
            status_code=422,
            detail="The original C program must compile and complete before optimization.",
        )

    try:
        result = optimize_c(
            job["source_code"],
            {
                "exit_code": job["exit_code"],
                "stdout": job["original_stdout"] or "",
                "stderr": job["original_stderr"] or "",
            },
            request.model_dump(exclude={"p_id"}, exclude_none=True),
        )
        result["p_id"] = p_id
        result["optimization_status"] = result["status"]
    except OptimizationError as exc:
        result = {
            "status": "error",
            "optimization_status": "error",
            "language": "c",
            "optimization_path": "LLVM",
            "p_id": p_id,
            "original_code": job["source_code"],
            "original_tac": get_original_tac(p_id) or "",
            "optimized_tac": "",
            "optimized_code": "",
            "original_stdout": job["original_stdout"] or "",
            "optimized_stdout": "",
            "original_execution_time_ms": job["execution_time_ms"] or 0,
            "optimized_execution_time_ms": None,
            "time_improvement_percent": None,
            "original_instruction_count": None,
            "optimized_instruction_count": None,
            "code_size_reduction_percent": None,
            "tests_passed": 0,
            "tests_total": 0,
            "pass_sequence": [],
            "pass_events": [],
            "transformation_events": [],
            "generation_history": [],
            "generations": 0,
            "population_size": 0,
            "best_fitness": None,
            "simulation": False,
            "equivalent": None,
            "error_message": str(exc),
            "metadata": {"optimization_path": "LLVM", "error": str(exc)},
        }

    try:
        save_optimization_run(p_id, result)
    except (Error, ValueError) as exc:
        raise HTTPException(
            status_code=500,
            detail=(
                "Optimization completed, but its results could not be saved. "
                f"Job ID: {p_id}. Reason: {exc}"
            ),
        ) from exc
    return result
