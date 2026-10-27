import os
import platform
import random
import re
import shutil
import statistics
import subprocess
import tempfile
import copy
import hashlib
from difflib import SequenceMatcher
from pathlib import Path
from typing import Any, Dict, List, Optional, Sequence, Tuple

from app.limited_process import DEFAULT_MEMORY_LIMIT_BYTES, run_limited_process
from app.tac_generator import (
    C_SIMPLE_EXPRESSION,
    TacGenerationError,
    generate_tac,
    parse_c_assignments,
)
from app.ga.chromosome import Chromosome, LLVM_PASS_REGISTRY, PassSpec, registry_map
from app.ga.crossover import one_point_crossover
from app.ga.fitness import calculate_fitness, median_absolute_deviation, median_metric
from app.ga.llvm_runner import (
    LLVMToolchainError,
    apply_sequence,
    artifact_fingerprint,
    find_clang,
    find_opt,
    ir_fingerprint,
    resolve_registry,
    tool_version,
    verify_ir,
)
from app.ga.mutation import mutate
from app.ga.population import generate_population
from app.ga.selection import tournament_select


class OptimizationError(RuntimeError):
    pass


SUPPORTED_PIPELINES = ("O1", "O2", "O3", "Os", "Oz")
MAX_SOURCE_SIZE_BYTES = 50 * 1024
COMPILER_TIMEOUT_SECONDS = 15
EXECUTION_TIMEOUT_SECONDS = 5
MAX_OUTPUT_BYTES = 1024 * 1024
LLVM_IR_INSTRUCTION = re.compile(r"^\s*(?:%[-\w.$]+ = |(?:ret|br|switch|store|call|invoke|unreachable|resume|fence|atomicrmw|cmpxchg)\b)")
APPLIED_PASS = re.compile(r"^Running pass: (.+?)(?: on |$)")


def generate_llvm_ir(source_code: str) -> str:
    if len(source_code.encode("utf-8")) > MAX_SOURCE_SIZE_BYTES:
        raise OptimizationError("Source code exceeds the 50 KB LLVM IR generation limit.")
    try:
        clang_path = find_clang()
    except LLVMToolchainError as exc:
        raise OptimizationError(str(exc)) from exc

    with tempfile.TemporaryDirectory(prefix="llvm_ir_") as work_dir:
        source_path = os.path.join(work_dir, "source.c")
        ir_path = os.path.join(work_dir, "original.ll")
        with open(source_path, "w", encoding="utf-8") as source_file:
            source_file.write(source_code)
        _run_compiler(
            [
                clang_path, "-std=c11", "-O0", "-S", "-emit-llvm", "-Xclang",
                "-disable-llvm-passes", "-Xclang", "-disable-O0-optnone",
                "source.c", "-o", ir_path,
            ],
            work_dir,
        )
        with open(ir_path, encoding="utf-8") as ir_file:
            return ir_file.read()


def _configuration() -> Tuple[List[str], int, int, int, int, str]:
    pipelines = [
        value.strip()
        for value in os.getenv("LLVM_OPTIMIZATION_PIPELINES", "O1,O2,O3,Os,Oz").split(",")
        if value.strip()
    ]
    if not pipelines or any(value not in SUPPORTED_PIPELINES for value in pipelines):
        raise OptimizationError(
            "LLVM_OPTIMIZATION_PIPELINES must contain only O1, O2, O3, Os, or Oz."
        )

    try:
        population_size = int(os.getenv("GA_POPULATION_SIZE", "6"))
        generations = int(os.getenv("GA_GENERATIONS", "3"))
        max_sequence_length = int(os.getenv("GA_MAX_SEQUENCE_LENGTH", "3"))
        benchmark_runs = int(os.getenv("GA_BENCHMARK_RUNS", "3"))
    except ValueError as exc:
        raise OptimizationError("GA configuration values must be integers.") from exc

    if min(population_size, generations, max_sequence_length, benchmark_runs) < 1:
        raise OptimizationError("GA configuration values must all be positive.")
    if population_size < 2:
        raise OptimizationError("GA_POPULATION_SIZE must be at least 2.")
    objective = os.getenv("GA_OBJECTIVE", "binary_size").strip().lower()
    if objective not in ("binary_size", "execution_time"):
        raise OptimizationError("GA_OBJECTIVE must be binary_size or execution_time.")
    return (
        pipelines,
        population_size,
        generations,
        max_sequence_length,
        benchmark_runs,
        objective,
    )


def _run_compiler(command: List[str], cwd: str) -> subprocess.CompletedProcess:
    try:
        result = subprocess.run(
            command,
            cwd=cwd,
            capture_output=True,
            text=True,
            timeout=COMPILER_TIMEOUT_SECONDS,
            check=False,
        )
    except subprocess.TimeoutExpired as exc:
        raise OptimizationError("Clang timed out while compiling or optimizing LLVM IR.") from exc
    except OSError as exc:
        raise OptimizationError(f"Unable to start Clang: {exc}") from exc
    if result.returncode != 0:
        detail = (result.stderr or result.stdout or "Clang returned an error.").strip()
        raise OptimizationError(detail[-4000:])
    return result


def _run_compiler_recorded(
    command: List[str],
    cwd: str,
    command_records: List[Dict[str, Any]],
    stage: str,
    input_ir_path: Optional[str] = None,
    output_path: Optional[str] = None,
) -> subprocess.CompletedProcess:
    """Run clang and retain enough evidence to audit the emitted artifact."""
    record: Dict[str, Any] = {
        "stage": stage,
        "command": list(command),
        "cwd": cwd,
        "compiler": command[0] if command else None,
        "flags": list(command[1:]),
        "input_ir_path": input_ir_path,
        "output_path": output_path,
        "returncode": None,
    }
    try:
        result = _run_compiler(command, cwd)
    except OptimizationError as exc:
        record["error"] = str(exc)
        command_records.append(record)
        raise
    record["returncode"] = result.returncode
    record["stdout"] = result.stdout[-4000:]
    record["stderr"] = result.stderr[-4000:]
    if output_path and os.path.isfile(output_path):
        record["output_sha256"] = artifact_fingerprint(output_path)
        record["output_size"] = os.path.getsize(output_path)
    command_records.append(record)
    return result


def _read_text(path: str) -> str:
    with open(path, encoding="utf-8") as file:
        return file.read()


def _run_executable(executable: str, cwd: str) -> Dict[str, Any]:
    return run_limited_process(
        [executable],
        cwd,
        EXECUTION_TIMEOUT_SECONDS,
        MAX_OUTPUT_BYTES,
    )


def _matches_expected(result: Dict[str, Any], expected: Optional[Dict[str, Any]]) -> bool:
    if result["timed_out"] or result["output_limited"]:
        return False
    return expected is None or (
        result["exit_code"] == expected["exit_code"]
        and result["stdout"] == expected["stdout"]
        and result["stderr"] == expected["stderr"]
    )


def _runtime_summary(runs: Sequence[Dict[str, Any]]) -> Dict[str, Optional[float]]:
    samples = [float(run["execution_time_ms"]) for run in runs]
    if not samples:
        return {
            "runtime_ms": None,
            "runtime_spread_ms": None,
            "runtime_min_ms": None,
            "runtime_max_ms": None,
        }
    median = statistics.median(samples)
    return {
        "runtime_ms": median,
        "runtime_spread_ms": median_absolute_deviation(samples),
        "runtime_min_ms": min(samples),
        "runtime_max_ms": max(samples),
    }


def _benchmark(
    executable: str, cwd: str, expected: Optional[Dict[str, Any]], count: int
) -> Tuple[List[Dict[str, Any]], bool]:
    """Run one executable with one unreported warm-up and measured samples."""
    results: List[Dict[str, Any]] = []
    warmup = _run_executable(executable, cwd)
    if not _matches_expected(warmup, expected):
        return results, False
    for _ in range(count):
        result = _run_executable(executable, cwd)
        results.append(result)
        if not _matches_expected(result, expected):
            return results, False
    return results, True


def _benchmark_interleaved(
    reference_executable: str,
    candidate_executable: str,
    reference_cwd: str,
    candidate_cwd: str,
    expected: Dict[str, Any],
    count: int,
) -> Tuple[List[Dict[str, Any]], List[Dict[str, Any]], bool]:
    """Measure reference and candidate with identical warm-up/interleaving."""
    reference_warmup = _run_executable(reference_executable, reference_cwd)
    candidate_warmup = _run_executable(candidate_executable, candidate_cwd)
    if not _matches_expected(reference_warmup, expected) or not _matches_expected(
        candidate_warmup, expected
    ):
        return [], [], False

    reference_runs: List[Dict[str, Any]] = []
    candidate_runs: List[Dict[str, Any]] = []
    for index in range(count):
        ordered = (
            ((reference_executable, reference_cwd, reference_runs),
             (candidate_executable, candidate_cwd, candidate_runs))
            if index % 2 == 0
            else ((candidate_executable, candidate_cwd, candidate_runs),
                  (reference_executable, reference_cwd, reference_runs))
        )
        for executable, cwd, destination in ordered:
            result = _run_executable(executable, cwd)
            destination.append(result)
            if not _matches_expected(result, expected):
                return reference_runs, candidate_runs, False
    return reference_runs, candidate_runs, True


def _ordered_passes(ir_path: str, sequence: Tuple[str, ...], work_dir: str) -> Tuple[str, List[str]]:
    current_ir = ir_path
    applied_passes: List[str] = []
    for index, pipeline in enumerate(sequence):
        next_ir = os.path.join(work_dir, "optimized_{}.ll".format(index))
        result = _run_compiler(
            [
                "clang",
                "-Xclang",
                "-fdebug-pass-manager",
                "-x",
                "ir",
                "-S",
                "-emit-llvm",
                "-{}".format(pipeline),
                current_ir,
                "-o",
                next_ir,
            ],
            work_dir,
        )
        for line in result.stderr.splitlines():
            match = APPLIED_PASS.match(line.strip())
            if match:
                applied_passes.append(match.group(1))
        if not os.path.isfile(next_ir):
            raise OptimizationError("Clang did not emit optimized LLVM IR.")
        current_ir = next_ir

    if not applied_passes:
        raise OptimizationError("Clang did not report applying any LLVM optimization passes.")
    return current_ir, applied_passes


def optimize_c_with_llvm_pipelines(
    source_code: str,
    expected_original: Optional[Dict[str, Any]] = None,
) -> Dict[str, Any]:
    if len(source_code.encode("utf-8")) > MAX_SOURCE_SIZE_BYTES:
        raise OptimizationError("Source code exceeds the 50 KB optimization limit.")
    if not shutil.which("clang"):
        raise OptimizationError("Clang is required for LLVM IR optimization.")

    (
        pipelines,
        population_size,
        generations,
        max_sequence_length,
        benchmark_runs,
        objective,
    ) = _configuration()

    with tempfile.TemporaryDirectory(prefix="llvm_ga_") as work_dir:
        source_path = os.path.join(work_dir, "source.c")
        original_ir = os.path.join(work_dir, "original.ll")
        original_executable = os.path.join(work_dir, "original.out")
        with open(source_path, "w", encoding="utf-8") as source_file:
            source_file.write(source_code)

        _run_compiler(
            [
                "clang", "-std=c11", "-O0", "-S", "-emit-llvm", "-Xclang",
                "-disable-llvm-passes", "-Xclang", "-disable-O0-optnone",
                "source.c", "-o", original_ir,
            ],
            work_dir,
        )
        _run_compiler(
            ["clang", "-std=c11", "-O0", source_path, "-o", original_executable],
            work_dir,
        )
        original_runs, original_valid = _benchmark(
            original_executable, work_dir, None, benchmark_runs
        )
        if not original_valid or not original_runs:
            raise OptimizationError("Original C program did not complete successfully.")
        original_signature = original_runs[0]
        if any(
            run["exit_code"] != original_signature["exit_code"]
            or run["stdout"] != original_signature["stdout"]
            or run["stderr"] != original_signature["stderr"]
            for run in original_runs
        ):
            raise OptimizationError("Original program produced inconsistent benchmark results.")
        if expected_original is not None and (
            original_signature["exit_code"] != expected_original.get("exit_code")
            or original_signature["stdout"] != expected_original.get("stdout")
            or original_signature["stderr"] != expected_original.get("stderr")
        ):
            raise OptimizationError(
                "Recompiled original output did not match the saved compilation result."
            )

        original_size = os.path.getsize(original_executable)
        original_runtime = statistics.median(
            run["execution_time_ms"] for run in original_runs
        )
        evaluation_cache: Dict[Tuple[str, ...], Dict[str, Any]] = {}

        def evaluate(sequence: Tuple[str, ...]) -> Dict[str, Any]:
            if sequence in evaluation_cache:
                return evaluation_cache[sequence]

            try:
                optimized_ir_path, applied = _ordered_passes(
                    original_ir, sequence, work_dir
                )
                candidate = os.path.join(
                    work_dir, "candidate_{}.out".format(len(evaluation_cache))
                )
                _run_compiler(
                    ["clang", "-x", "ir", "-O0", optimized_ir_path, "-o", candidate],
                    work_dir,
                )
                runs, equivalent = _benchmark(
                    candidate, work_dir, original_signature, benchmark_runs
                )
                if not equivalent:
                    result = {
                        "sequence": sequence,
                        "fitness": 0.0,
                        "equivalent": False,
                        "error": "Candidate timed out, exited unsuccessfully, or changed observable output.",
                    }
                else:
                    size = os.path.getsize(candidate)
                    runtime = statistics.median(
                        run["execution_time_ms"] for run in runs
                    )
                    metric = size if objective == "binary_size" else runtime
                    result = {
                        "sequence": sequence,
                        "fitness": 1.0 / max(float(metric), 1.0),
                        "equivalent": True,
                        "ir": _read_text(optimized_ir_path),
                        "binary": candidate,
                        "binary_size": size,
                        "runtime_ms": runtime,
                        "runs": runs,
                        "applied_passes": applied,
                    }
            except OptimizationError as exc:
                result = {
                    "sequence": sequence,
                    "fitness": 0.0,
                    "equivalent": False,
                    "error": str(exc),
                }
            evaluation_cache[sequence] = result
            return result

        generator = random.Random()

        def random_sequence() -> Tuple[str, ...]:
            length = generator.randint(1, max_sequence_length)
            return tuple(generator.choice(pipelines) for _ in range(length))

        population: List[Tuple[str, ...]] = []
        for pipeline in pipelines:
            if len(population) < population_size:
                population.append((pipeline,))
        while len(population) < population_size:
            population.append(random_sequence())

        best: Optional[Dict[str, Any]] = None

        def select_parent(evaluated: List[Dict[str, Any]]) -> Tuple[str, ...]:
            tournament = generator.sample(evaluated, min(2, len(evaluated)))
            return max(tournament, key=lambda item: item["fitness"])["sequence"]

        for _ in range(generations):
            evaluated = [evaluate(candidate) for candidate in population]
            generation_best = max(evaluated, key=lambda item: item["fitness"])
            if generation_best["equivalent"] and (
                best is None or generation_best["fitness"] > best["fitness"]
            ):
                best = generation_best

            next_population = [
                max(evaluated, key=lambda item: item["fitness"])["sequence"]
            ]
            while len(next_population) < population_size:
                first = select_parent(evaluated)
                second = select_parent(evaluated)
                first_cut = generator.randint(0, len(first))
                second_cut = generator.randint(0, len(second))
                child = first[:first_cut] + second[second_cut:]
                child = child[:max_sequence_length]
                if not child:
                    child = (generator.choice(pipelines),)

                if generator.random() < 0.35:
                    mutation = generator.choice(("replace", "insert", "remove"))
                    mutable = list(child)
                    if mutation == "replace":
                        mutable[generator.randrange(len(mutable))] = generator.choice(pipelines)
                    elif mutation == "insert" and len(mutable) < max_sequence_length:
                        mutable.insert(generator.randrange(len(mutable) + 1), generator.choice(pipelines))
                    elif mutation == "remove" and len(mutable) > 1:
                        mutable.pop(generator.randrange(len(mutable)))
                    child = tuple(mutable)
                next_population.append(child)
            population = next_population

        for candidate in population:
            candidate_result = evaluate(candidate)
            if candidate_result["equivalent"] and (
                best is None or candidate_result["fitness"] > best["fitness"]
            ):
                best = candidate_result

        if best is None:
            raise OptimizationError("No equivalent LLVM optimization candidate was found.")

        assembly_path = os.path.join(work_dir, "optimized.s")
        best_ir_path = os.path.join(work_dir, "best_optimized.ll")
        with open(best_ir_path, "w", encoding="utf-8") as ir_file:
            ir_file.write(best["ir"])
        _run_compiler(
            [
                "clang", "-x", "ir", "-S", "-O0", best_ir_path, "-o", assembly_path,
            ],
            work_dir,
        )

        with open(original_ir, encoding="utf-8") as ir_file:
            original_ir_text = ir_file.read()
        with open(assembly_path, encoding="utf-8") as assembly_file:
            assembly = assembly_file.read()
        optimized_runs = best["runs"]
        optimized_runtime = best["runtime_ms"]
        time_improvement = (
            (original_runtime - optimized_runtime) / original_runtime * 100
            if original_runtime > 0
            else 0.0
        )
        size_reduction = (
            (original_size - best["binary_size"]) / original_size * 100
            if original_size > 0
            else 0.0
        )
        optimized_ir_text = best["ir"]
        metadata = {
            "pass_sequence": list(best["sequence"]),
            "applied_passes": best["applied_passes"],
            "generations": generations,
            "population_size": population_size,
            "best_fitness": best["fitness"],
            "objective": objective,
            "original_execution_time_ms": original_runtime,
            "optimized_execution_time_ms": optimized_runtime,
            "time_improvement_percent": time_improvement,
            "original_binary_size": original_size,
            "optimized_binary_size": best["binary_size"],
            "code_size_reduction_percent": size_reduction,
            "tests_passed": len(optimized_runs),
            "tests_total": len(optimized_runs),
            "original_exit_code": original_signature["exit_code"],
            "equivalent": True,
            "clang_version": subprocess.run(
                ["clang", "--version"],
                capture_output=True,
                text=True,
                timeout=5,
                check=True,
            ).stdout.splitlines()[0],
        }
        return {
            "status": "success",
            "language": "c",
            "original_code": source_code,
            "original_tac": original_ir_text,
            "optimized_tac": optimized_ir_text,
            "optimized_code": assembly,
            "original_stdout": original_signature["stdout"],
            "optimized_stdout": optimized_runs[0]["stdout"],
            "original_execution_time_ms": original_runtime,
            "optimized_execution_time_ms": optimized_runtime,
            "time_improvement_percent": time_improvement,
            "original_instruction_count": sum(
                bool(LLVM_IR_INSTRUCTION.match(line))
                for line in original_ir_text.splitlines()
            ),
            "optimized_instruction_count": sum(
                bool(LLVM_IR_INSTRUCTION.match(line))
                for line in optimized_ir_text.splitlines()
            ),
            "code_size_reduction_percent": size_reduction,
            "tests_passed": len(optimized_runs),
            "tests_total": len(optimized_runs),
            "pass_sequence": list(best["sequence"]),
            "applied_passes": best["applied_passes"],
            "generations": generations,
            "population_size": population_size,
            "best_fitness": best["fitness"],
            "simulation": False,
            "equivalent": True,
            "objective": objective,
            "original_exit_code": original_signature["exit_code"],
            "optimized_exit_code": optimized_runs[0]["exit_code"],
            "original_binary_size": original_size,
            "optimized_binary_size": best["binary_size"],
            "clang_version": metadata["clang_version"],
            "metadata": metadata,
        }


TAC_PASSES = {
    "CF": "Constant Folding",
    "CP": "Copy Propagation",
    "DCE": "Dead Code Elimination",
    "CSE": "Common Subexpression Elimination",
    "SR": "Strength Reduction",
}
TAC_BINARY_EXPRESSION = re.compile(r"^(-?\d+|[A-Za-z_]\w*)\s*([+\-*/%])\s*(-?\d+|[A-Za-z_]\w*)$")
TAC_ATOM = re.compile(r"^(?:-?\d+|[A-Za-z_]\w*)$")


def _tac_ga_configuration() -> Tuple[int, int, int, int, str]:
    try:
        population_size = int(os.getenv("GA_POPULATION_SIZE", "6"))
        generations = int(os.getenv("GA_GENERATIONS", "3"))
        max_sequence_length = int(os.getenv("GA_MAX_SEQUENCE_LENGTH", "3"))
        benchmark_runs = int(os.getenv("GA_BENCHMARK_RUNS", "3"))
    except ValueError as exc:
        raise OptimizationError("GA configuration values must be integers.") from exc
    if min(population_size, generations, max_sequence_length, benchmark_runs) < 1:
        raise OptimizationError("GA configuration values must all be positive.")
    if population_size < 2:
        raise OptimizationError("GA_POPULATION_SIZE must be at least 2.")
    objective = os.getenv("GA_OBJECTIVE", "binary_size").strip().lower()
    if objective not in ("binary_size", "execution_time"):
        raise OptimizationError("GA_OBJECTIVE must be binary_size or execution_time.")
    return population_size, generations, max_sequence_length, benchmark_runs, objective


def _apply_tac_pass(
    source: str, pass_id: str
) -> Tuple[str, List[Dict[str, Any]]]:
    assignments = parse_c_assignments(source)
    tac = generate_tac(source, "c")
    tac_instructions = [
        (item["source_line"], item["instruction"]) for item in tac
    ]
    variable_types = {
        assignment["target"]: re.sub(r"\s+", " ", assignment["declaration"])
        for assignment in assignments
        if assignment["declaration"]
    }
    for _, instruction in tac_instructions:
        declaration = re.fullmatch(
            r"decl (.+?) ([A-Za-z_]\w*)(?:\[[^]]+\])*", instruction
        )
        if declaration:
            variable_types.setdefault(declaration.group(2), declaration.group(1))
    events: List[Dict[str, Any]] = []
    replacements: List[Tuple[int, int, str]] = []
    function_body_start = source.find("{")
    local_assignments = [
        record for record in assignments if record["start"] > function_body_start
    ]
    local_declared_targets = {
        record["target"]
        for record in local_assignments
        if record["declaration"]
        and source[:record["start"]].count("{")
        - source[:record["start"]].count("}") == 1
    }

    def split_tac_assignment(instruction: str) -> Optional[Tuple[str, str]]:
        match = re.fullmatch(r"([A-Za-z_]\w*)\s*=\s*(.+)", instruction)
        return match.groups() if match else None

    def mentions(expression: str, variable: str) -> bool:
        return re.search(r"\b{}\b".format(re.escape(variable)), expression) is not None

    def reads_volatile(expression: str) -> bool:
        return any(
            "volatile" in type_name.split() and mentions(expression, variable)
            for variable, type_name in variable_types.items()
        )

    def normalized_expression(expression: str) -> str:
        binary = TAC_BINARY_EXPRESSION.fullmatch(expression)
        if binary is None:
            return re.sub(r"\s+", "", expression)
        left, operator, right = binary.groups()
        if operator in {"+", "*"}:
            left, right = sorted((left, right))
        return f"{left}{operator}{right}"

    def tac_reads_after(line: int, target: str, instructions: List[Tuple[int, str]]) -> bool:
        definition_index = next(
            (
                index
                for index, (tac_line, instruction) in enumerate(instructions)
                if tac_line == line
                and (assignment := split_tac_assignment(instruction)) is not None
                and assignment[0] == target
            ),
            -1,
        )
        if definition_index < 0:
            return True
        for _, instruction in instructions[definition_index + 1:]:
            assignment = split_tac_assignment(instruction)
            operands = assignment[1] if assignment else instruction
            if mentions(operands, target):
                return True
        return False

    constant_assignment_values: Dict[Tuple[int, str], int] = {}
    constant_values: Dict[str, int] = {}
    for line, instruction in tac_instructions:
        if instruction.startswith(("label ", "if ", "ifFalse ", "goto ", "call ")):
            constant_values.clear()
            continue
        assignment = split_tac_assignment(instruction)
        if assignment is None:
            continue
        target, expression = assignment
        if expression.lstrip("-").isdigit():
            constant_values[target] = int(expression)
            constant_assignment_values[(line, target)] = int(expression)
            continue
        binary = TAC_BINARY_EXPRESSION.fullmatch(expression)
        if binary:
            left, operator, right = binary.groups()
            first = int(left) if left.lstrip("-").isdigit() else constant_values.get(left)
            second = int(right) if right.lstrip("-").isdigit() else constant_values.get(right)
            if first is not None and second is not None:
                # The TAC pass models signed C int only.  Do not use a
                # Python-wide integer result to fold an operation whose C
                # operands would already be outside the signed-int domain.
                if not (
                    -(2**31) <= first < 2**31
                    and -(2**31) <= second < 2**31
                ):
                    constant_values.pop(target, None)
                    continue
                if operator == "+":
                    value = first + second
                elif operator == "-":
                    value = first - second
                elif operator == "*":
                    value = first * second
                elif operator == "/" and second:
                    quotient = abs(first) // abs(second)
                    value = -quotient if (first < 0) != (second < 0) else quotient
                elif operator == "%" and second:
                    quotient = abs(first) // abs(second)
                    quotient = -quotient if (first < 0) != (second < 0) else quotient
                    value = first - quotient * second
                else:
                    constant_values.pop(target, None)
                    continue
                if -(2**31) <= value < 2**31:
                    constant_values[target] = value
                    constant_assignment_values[(line, target)] = value
                    continue
            constant_values.pop(target, None)
        elif expression in constant_values:
            constant_values[target] = constant_values[expression]
            if -(2**31) <= constant_values[expression] < 2**31:
                constant_assignment_values[(line, target)] = constant_values[expression]
        else:
            constant_values.pop(target, None)

    def is_signed_int(record: Dict[str, Any]) -> bool:
        tokens = set(record["declaration"].split())
        return (
            "int" in tokens
            and not tokens.intersection(
                {"unsigned", "long", "short", "char", "float", "double", "volatile"}
            )
        )

    def is_side_effect_free_expression(expression: str) -> bool:
        """Return true only for the small TAC expression subset we can remove."""
        if not C_SIMPLE_EXPRESSION.fullmatch(expression):
            return False
        # A division/modulo may trap for a runtime zero divisor.  Keeping it is
        # the conservative choice for DCE; all other operators are pure in the
        # supported scalar TAC subset.
        return "/" not in expression and "%" not in expression

    def crosses_control_boundary(previous_end: int, next_start: int) -> bool:
        between = source[previous_end:next_start]
        return bool(
            re.search(
                r"[{}]|\b(if|else|for|while|switch|goto|return|break|continue)\b"
                r"|\b[A-Za-z_]\w*\s*\("
                r"|\b[A-Za-z_]\w*(?:\s*\[[^]]+\])?\s*=(?!=)"
                r"|\+\+|--|\+=|-=|\*=|/=|%=|&",
                between,
            )
        )

    def replace_expression(record: Dict[str, Any], expression: str, description: str) -> None:
        start = record["expression_start"]
        end = record["expression_end"]
        current = source[start:end]
        leading = current[: len(current) - len(current.lstrip())]
        trailing = current[len(current.rstrip()):]
        replacements.append((start, end, f"{leading}{expression}{trailing}"))
        original_instruction = source[record["start"]:record["end"]].strip()
        replacement_instruction = (
            source[record["start"]:start] + expression + source[end:record["end"]]
        ).strip()
        events.append(
            {
                "pass_id": pass_id,
                "pass_name": TAC_PASSES[pass_id],
                "source_line": record["source_line"],
                "description": description,
                "changed": True,
                "executed": True,
                "transformation_occurred": True,
                "original_instruction": original_instruction,
                "replacement": replacement_instruction,
            }
        )

    if pass_id == "CF":
        for record in assignments:
            match = TAC_BINARY_EXPRESSION.fullmatch(record["expression"])
            if not is_signed_int(record) or reads_volatile(record["expression"]):
                continue
            value = constant_assignment_values.get(
                (record["source_line"], record["target"])
            )
            if value is None:
                # A source assignment can lower to several TAC operations
                # (for example 2 + 3 * 4).  The final TAC assignment above is
                # the reliable source-to-result mapping; a source line alone
                # is not a reliable TAC instruction identity.
                continue
            if str(value) == record["expression"].strip():
                continue
            if -(2**31) <= value < 2**31:
                replace_expression(record, str(value), f"Folded a constant expression to {value}.")

    elif pass_id == "CP":
        copied_values: Dict[str, str] = {}
        previous_end = function_body_start + 1
        for record in local_assignments:
            between = source[previous_end:record["start"]]
            if crosses_control_boundary(previous_end, record["start"]):
                has_call = re.search(
                    r"\b(?!(?:if|for|while|switch|sizeof)\b)[A-Za-z_]\w*\s*\(",
                    between,
                )
                if has_call or "&" in between:
                    copied_values.clear()
                else:
                    tracked_names = set(copied_values)
                    tracked_names.update(copied_values.values())
                    changed_names = {
                        name
                        for name in tracked_names
                        if re.search(
                            r"(?:\+\+|--)\s*{}\b|\b{}\s*(?:\+\+|--|[+\-*/%]?=(?!=))".format(
                                re.escape(name), re.escape(name)
                            ),
                            between,
                        )
                    }
                    copied_values = {
                        name: value
                        for name, value in copied_values.items()
                        if name not in changed_names
                        and not any(mentions(value, changed) for changed in changed_names)
                    }
            target = record["target"]
            expression = record["expression"]
            copied_values.pop(target, None)
            copied_values = {
                name: value
                for name, value in copied_values.items()
                if not mentions(value, target)
            }
            if re.fullmatch(r"[A-Za-z_0-9\s+\-*/%]+", expression):
                propagated = re.sub(
                    r"\b[A-Za-z_]\w*\b",
                    lambda match: copied_values.get(match.group(), match.group()),
                    expression,
                )
                if propagated != expression:
                    replace_expression(
                        record,
                        propagated,
                        f"Propagated copied values into {target}.",
                    )
            else:
                propagated = expression
            copied_name = (
                propagated
                if TAC_ATOM.fullmatch(propagated)
                and not propagated.lstrip("-").isdigit()
                else None
            )
            target_type = variable_types.get(target)
            source_type = variable_types.get(copied_name) if copied_name else None
            if (
                copied_name
                and target_type
                and target_type == source_type
                and "volatile" not in target_type.split()
                and "*" not in target_type
            ):
                copied_values[target] = propagated
            previous_end = record["end"]

    elif pass_id == "CSE":
        prior_expressions: Dict[Tuple[str, str], str] = {}
        previous_end = function_body_start + 1
        for record in local_assignments:
            if crosses_control_boundary(previous_end, record["start"]):
                prior_expressions.clear()
            target = record["target"]
            expression = record["expression"]
            target_type = variable_types.get(target)
            # Invalidate before looking up the current expression.  This is
            # source-assignment based deliberately: TAC lowers one C
            # assignment into several instructions and multiple assignments
            # can share a source line, so a source-line/TAC-line join is not a
            # reliable identity.
            prior_expressions = {
                key: value
                for key, value in prior_expressions.items()
                if value != target
                and not mentions(key[0], target)
            }
            normalized = normalized_expression(expression)
            if (
                target_type
                and not any(
                    token in target_type.split()
                    for token in ("*", "volatile", "float", "double")
                )
                and not reads_volatile(expression)
                and TAC_BINARY_EXPRESSION.fullmatch(expression)
                and (normalized, target_type) in prior_expressions
            ):
                prior = prior_expressions[(normalized, target_type)]
                replace_expression(
                    record, prior, f"Reused the common expression stored in {prior}."
                )
            elif (
                target_type
                and not any(
                    token in target_type.split()
                    for token in ("*", "volatile", "float", "double")
                )
                and not reads_volatile(expression)
                and TAC_BINARY_EXPRESSION.fullmatch(expression)
            ):
                prior_expressions[(normalized, target_type)] = target
            previous_end = record["end"]

    elif pass_id == "SR":
        supported_loop = re.compile(
            r"\bfor\s*\(\s*int\s+([A-Za-z_]\w*)\s*=\s*(-?\d+)\s*;\s*"
            r"\1\s*<\s*(-?\d+)\s*;\s*\1\s*\+\+\s*\)\s*\{"
        )
        has_loop_multiplication = False
        loop_multiplication_line: Optional[int] = None
        int_min, int_max = -(2**31), 2**31 - 1

        def matching_brace(opening: int) -> Optional[int]:
            depth = 0
            for position in range(opening, len(source)):
                if source[position] == "{":
                    depth += 1
                elif source[position] == "}":
                    depth -= 1
                    if depth == 0:
                        return position
            return None

        for loop_match in supported_loop.finditer(source):
            induction, start_text, bound_text = loop_match.groups()
            start_value, bound = int(start_text), int(bound_text)
            closing_brace = matching_brace(loop_match.end() - 1)
            if closing_brace is None:
                continue
            body_start = loop_match.end()
            body = source[body_start:closing_brace]

            # The replacement is valid only for straight-line loop bodies:
            # the induction variable must not be changed or observed through a
            # control-flow/aliasing construct.  Other scalar statements are
            # allowed, which is why this does not inspect body TAC length.
            if re.search(
                r"\b(if|for|while|switch|goto|break|continue|return)\b|"
                r"\b{}\s*(?:\+\+|--|[+\-*/%]?=(?!=))|"
                r"[&]\s*{}\b".format(re.escape(induction), re.escape(induction)),
                body,
            ):
                continue
            multiplication = re.search(
                r"(?P<indent>^[ \t]*)(?P<target>[A-Za-z_]\w*)\s*\+=\s*"
                r"(?P<left>{})\s*\*\s*(?P<factor>-?\d+)\s*;".format(
                    re.escape(induction)
                ),
                body,
                re.MULTILINE,
            )
            if multiplication is None:
                multiplication = re.search(
                    r"(?P<indent>^[ \t]*)(?P<target>[A-Za-z_]\w*)\s*\+=\s*"
                    r"(?P<factor>-?\d+)\s*\*\s*(?P<right>{})\s*;".format(
                        re.escape(induction)
                    ),
                    body,
                    re.MULTILINE,
                )
            if multiplication is None:
                # Keep a useful diagnostic when TAC did contain a multiply,
                # even if its source form is outside this safe pattern.
                if re.search(r"\b{}\s*\*\s*-?\d+|-?\d+\s*\*\s*\b{}\b".format(
                    re.escape(induction), re.escape(induction)
                ), body):
                    has_loop_multiplication = True
                    loop_multiplication_line = source.count("\n", 0, body_start) + 1
                continue

            has_loop_multiplication = True
            loop_multiplication_line = source.count("\n", 0, body_start) + 1
            target = multiplication.group("target")
            factor_text = multiplication.group("factor")
            factor = int(factor_text)
            if factor == 0:
                continue
            target_type = variable_types.get(target, "")
            if not is_signed_int({"declaration": target_type}):
                continue
            if not (int_min <= start_value < bound <= int_max):
                continue
            start_product = start_value * factor
            end_product = bound * factor
            if not (int_min <= factor <= int_max and int_min <= start_product <= int_max
                    and int_min <= end_product <= int_max):
                continue

            # Do not introduce a shadowing name or a second update site.  The
            # source match is precise even when the TAC body has declarations,
            # temporaries, or other pure statements around the update.
            update_start = body_start + multiplication.start()
            update_end = body_start + multiplication.end()
            update_line = source.count("\n", 0, update_start) + 1
            line_start = source.rfind("\n", 0, loop_match.start()) + 1
            header_indent = source[line_start:loop_match.start()]
            # Inserting a declaration is only straightforward when the loop
            # header starts its source line.  A same-line preceding statement
            # could place the helper at file scope or in the wrong block.
            if header_indent.strip():
                continue
            scaled_name = "__tac_strength_reduced"
            suffix = 1
            while re.search(r"\b{}\b".format(scaled_name), source):
                suffix += 1
                scaled_name = f"__tac_strength_reduced_{suffix}"
            indent = multiplication.group("indent")
            line_ending = "\r\n" if "\r\n" in source else "\n"
            replacement = (
                f"{indent}{target} += {scaled_name}; "
                f"{scaled_name} += {factor_text};"
            )
            updated_source = source[:update_start] + replacement + source[update_end:]
            insertion = loop_match.start()
            updated_source = (
                updated_source[:line_start]
                + f"{header_indent}int {scaled_name} = {start_product};{line_ending}"
                + updated_source[line_start:]
            )
            tac_multiplication = next(
                (
                    instruction
                    for line, instruction in tac_instructions
                    if line == update_line
                    and re.fullmatch(
                        r"t\d+ = {} \* {}".format(
                            re.escape(induction), re.escape(factor_text)
                        ),
                        instruction,
                    )
                ),
                None,
            )
            events.append(
                {
                    "pass_id": pass_id,
                    "pass_name": TAC_PASSES[pass_id],
                    "source_line": update_line,
                    "description": (
                        "Replaced induction-variable multiplication after proving "
                        "the signed-int loop range and update are overflow-safe."
                    ),
                    "changed": True,
                    "executed": True,
                    "transformation_occurred": True,
                    "original_instruction": tac_multiplication
                    or f"{target} += {induction} * {factor_text};",
                    "replacement": f"{target} += {scaled_name}; {scaled_name} += {factor_text};",
                }
            )
            return updated_source, events

        if has_loop_multiplication:
            events.append(
                {
                    "pass_id": pass_id,
                    "pass_name": TAC_PASSES[pass_id],
                    "source_line": loop_multiplication_line,
                    "description": (
                        "A loop multiplication was found, but it was outside the "
                        "straight-line signed-int pattern required for "
                        "safe strength reduction."
                    ),
                    "changed": False,
                    "executed": True,
                    "transformation_occurred": False,
                    "original_instruction": None,
                    "replacement": None,
                }
            )

    elif pass_id == "DCE":
        current_source = source
        while True:
            removable: List[Dict[str, Any]] = []
            current_tac = [
                (item["source_line"], item["instruction"])
                for item in generate_tac(current_source, "c")
            ]
            for record in parse_c_assignments(current_source):
                if record["start"] <= function_body_start:
                    continue
                if record["target"] not in local_declared_targets:
                    continue
                if (
                    current_source[:record["start"]].count("{")
                    - current_source[:record["start"]].count("}")
                    != 1
                ):
                    continue
                declaration = record["declaration"].split()
                if "volatile" in declaration or "*" in declaration:
                    continue
                if reads_volatile(record["expression"]):
                    continue
                if not is_side_effect_free_expression(record["expression"]):
                    continue
                if not tac_reads_after(
                    record["source_line"], record["target"], current_tac
                ):
                    removable.append(record)
            if not removable:
                break

            for record in reversed(removable):
                start = record["start"]
                end = record["end"]
                original = current_source[start:end]
                removed_instruction = original.strip()
                current_source = (
                    current_source[:start]
                    + "".join(
                        "\n" if character == "\n" else " "
                        for character in original
                    )
                    + current_source[end:]
                )
                events.append(
                    {
                        "pass_id": pass_id,
                        "pass_name": TAC_PASSES[pass_id],
                        "source_line": record["source_line"],
                        "description": (
                            f"Removed the unused assignment to {record['target']}."
                        ),
                        "changed": True,
                        "executed": True,
                        "transformation_occurred": True,
                        "original_instruction": removed_instruction,
                        "replacement": None,
                    }
                )
        if current_source != source:
            return current_source, events

    updated_source = source
    for start, end, replacement in sorted(replacements, reverse=True):
        updated_source = updated_source[:start] + replacement + updated_source[end:]
    if not events:
        events.append(
            {
                "pass_id": pass_id,
                "pass_name": TAC_PASSES[pass_id],
                "source_line": None,
                "description": (
                    "No applicable safe transformation was found in the "
                    "supported TAC patterns."
                ),
                "changed": False,
                "executed": True,
                "transformation_occurred": False,
                "original_instruction": None,
                "replacement": None,
            }
        )
    return updated_source, events


def _tac_instruction_changes(
    before: List[Dict[str, Any]], after: List[Dict[str, Any]]
) -> List[Dict[str, Any]]:
    def normalized_instructions(instructions: List[Dict[str, Any]]) -> List[str]:
        return [
            re.sub(r"\bt\d+\b", "t", item["instruction"])
            for item in instructions
        ]

    before_instructions = normalized_instructions(before)
    after_instructions = normalized_instructions(after)
    changes: List[Dict[str, Any]] = []
    matcher = SequenceMatcher(a=before_instructions, b=after_instructions)
    for operation, before_start, before_end, after_start, after_end in matcher.get_opcodes():
        if operation == "equal":
            continue
        removed = before[before_start:before_end]
        added = after[after_start:after_end]
        changes.append(
            {
                "source_line": (
                    (removed or added)[0]["source_line"]
                    if removed or added
                    else None
                ),
                "removed": removed,
                "added": added,
            }
        )
    return changes


def optimize_tac(
    source_code: str,
    expected_original: Optional[Dict[str, Any]] = None,
) -> Dict[str, Any]:
    if len(source_code.encode("utf-8")) > MAX_SOURCE_SIZE_BYTES:
        raise OptimizationError("Source code exceeds the 50 KB optimization limit.")
    if not shutil.which("clang"):
        raise OptimizationError("Clang is required for LLVM-based C compilation.")
    try:
        original_tac = generate_tac(source_code, "c")
    except TacGenerationError as exc:
        raise OptimizationError(str(exc)) from exc

    (
        population_size,
        generations,
        max_sequence_length,
        benchmark_runs,
        objective,
    ) = _tac_ga_configuration()
    pass_ids = tuple(TAC_PASSES)

    with tempfile.TemporaryDirectory(prefix="tac_ga_") as work_dir:
        source_path = os.path.join(work_dir, "original.c")
        original_executable = os.path.join(work_dir, "original.out")
        original_ir = os.path.join(work_dir, "original.ll")
        with open(source_path, "w", encoding="utf-8") as source_file:
            source_file.write(source_code)
        _run_compiler(
            [
                "clang", "-std=c11", "-O0", "-S", "-emit-llvm", "-Xclang",
                "-disable-llvm-passes", "-Xclang", "-disable-O0-optnone",
                source_path, "-o", original_ir,
            ],
            work_dir,
        )
        _run_compiler(
            ["clang", "-std=c11", "-O0", source_path, "-o", original_executable],
            work_dir,
        )
        original_runs, original_valid = _benchmark(
            original_executable, work_dir, None, benchmark_runs
        )
        if not original_valid or not original_runs:
            raise OptimizationError("Original C program did not complete successfully.")
        original_signature = original_runs[0]
        if any(
            run["exit_code"] != original_signature["exit_code"]
            or run["stdout"] != original_signature["stdout"]
            or run["stderr"] != original_signature["stderr"]
            for run in original_runs
        ):
            raise OptimizationError("Original program produced inconsistent benchmark results.")
        if expected_original is not None and (
            original_signature["exit_code"] != expected_original.get("exit_code")
            or original_signature["stdout"] != expected_original.get("stdout")
            or original_signature["stderr"] != expected_original.get("stderr")
        ):
            raise OptimizationError(
                "Recompiled original output did not match the saved compilation result."
            )

        original_runtime = statistics.median(
            run["execution_time_ms"] for run in original_runs
        )
        original_size = os.path.getsize(original_executable)
        cache: Dict[Tuple[str, ...], Dict[str, Any]] = {}
        generator = random.Random(0)
        candidate_id = 0

        def runtime_mad(result: Dict[str, Any]) -> float:
            samples = [
                run["execution_time_ms"] for run in result["runs"]
            ]
            center = statistics.median(samples)
            return statistics.median(abs(sample - center) for sample in samples)

        def objectively_better(
            candidate: Dict[str, Any], current: Dict[str, Any]
        ) -> bool:
            if objective == "binary_size":
                return candidate["metric"] < current["metric"]
            noise_margin = runtime_mad(candidate) + runtime_mad(current)
            return candidate["metric"] < current["metric"] - noise_margin

        def selection_better(
            candidate: Dict[str, Any], current: Dict[str, Any]
        ) -> bool:
            # A TAC tie-break is useful for parent selection, but it must not
            # replace the original program when the configured measurable
            # objective did not improve.  Otherwise the API claims a selected
            # optimization even though the objective is unchanged.
            return objectively_better(candidate, current)

        def candidate_rank(candidate: Dict[str, Any]) -> Tuple[Any, ...]:
            return (
                candidate["fitness"],
                -len(candidate.get("tac", ())),
                -len(candidate["sequence"]),
                candidate["sequence"],
            )

        def evaluate(sequence: Tuple[str, ...]) -> Dict[str, Any]:
            nonlocal candidate_id
            if sequence in cache:
                return cache[sequence]
            candidate_id += 1
            current_candidate_id = f"candidate-{candidate_id}"
            candidate_source = source_code
            events: List[Dict[str, Any]] = []
            pass_diagnostics: List[Dict[str, Any]] = []
            candidate_source_path = os.path.join(
                work_dir, f"candidate_{len(cache)}.c"
            )
            candidate_binary = os.path.join(
                work_dir, f"candidate_{len(cache)}.out"
            )
            try:
                for pass_id in sequence:
                    before_tac = generate_tac(candidate_source, "c")
                    candidate_source, pass_events = _apply_tac_pass(
                        candidate_source, pass_id
                    )
                    after_tac = generate_tac(candidate_source, "c")
                    tac_changes = _tac_instruction_changes(before_tac, after_tac)
                    diagnostic = {
                        "candidate_id": current_candidate_id,
                        "pass_id": pass_id,
                        "pass_name": TAC_PASSES[pass_id],
                        "executed": True,
                        "instruction_count_before": len(before_tac),
                        "instruction_count_after": len(after_tac),
                        "transformations_applied": sum(
                            event["changed"] for event in pass_events
                        ),
                        "changed": any(event["changed"] for event in pass_events),
                        "reason": next(
                            (
                                event["description"]
                                for event in pass_events
                                if not event["changed"]
                            ),
                            "Transformation applied." if any(
                                event["changed"] for event in pass_events
                            ) else "Pass executed without a reported transformation.",
                        ),
                        "tac_instruction_changes": tac_changes,
                    }
                    pass_diagnostics.append(diagnostic)
                    for event in pass_events:
                        event["candidate_sequence"] = list(sequence)
                        event["candidate_id"] = current_candidate_id
                        event.update(diagnostic)
                    events.extend(pass_events)
                with open(candidate_source_path, "w", encoding="utf-8") as file:
                    file.write(candidate_source)
                _run_compiler(
                    ["clang", "-std=c11", "-O0", candidate_source_path, "-o", candidate_binary],
                    work_dir,
                )
                runs, equivalent = _benchmark(
                    candidate_binary, work_dir, original_signature, benchmark_runs
                )
                if not equivalent:
                    result = {
                        "sequence": sequence,
                        "candidate_id": current_candidate_id,
                        "fitness": 0.0,
                        "equivalent": False,
                        "candidate_status": "rejected",
                        "events": events,
                        "pass_diagnostics": pass_diagnostics,
                        "error": "Candidate changed output or exit status, failed, or timed out.",
                    }
                else:
                    binary_size = os.path.getsize(candidate_binary)
                    candidate_tac = generate_tac(candidate_source, "c")
                    runtime_ms = statistics.median(
                        run["execution_time_ms"] for run in runs
                    )
                    metric = binary_size if objective == "binary_size" else runtime_ms
                    result = {
                        "sequence": sequence,
                        "candidate_id": current_candidate_id,
                        "fitness": 1.0 / max(float(metric), 1.0),
                        "metric": metric,
                        "equivalent": True,
                        "candidate_status": "equivalent",
                        "source": candidate_source,
                        "tac": candidate_tac,
                        "events": events,
                        "pass_diagnostics": pass_diagnostics,
                        "runs": runs,
                        "binary": candidate_binary,
                        "binary_size": binary_size,
                        "runtime_ms": runtime_ms,
                        "transformations": sum(event["changed"] for event in events),
                    }
            except (OptimizationError, TacGenerationError) as exc:
                result = {
                    "sequence": sequence,
                    "candidate_id": current_candidate_id,
                    "fitness": 0.0,
                    "equivalent": False,
                    "candidate_status": "rejected",
                    "events": events,
                    "pass_diagnostics": pass_diagnostics,
                    "error": str(exc),
                }
            cache[sequence] = result
            return result

        baseline_metric = original_size if objective == "binary_size" else original_runtime
        baseline: Dict[str, Any] = {
            "sequence": (),
            "candidate_id": "baseline",
            "fitness": 1.0 / max(float(baseline_metric), 1.0),
            "metric": baseline_metric,
            "equivalent": True,
            "source": source_code,
            "tac": original_tac,
            "events": [],
            "pass_diagnostics": [],
            "runs": original_runs,
            "binary": original_executable,
            "binary_size": original_size,
            "runtime_ms": original_runtime,
            "transformations": 0,
        }
        best = baseline

        def random_sequence() -> Tuple[str, ...]:
            length = generator.randint(1, min(max_sequence_length, len(pass_ids)))
            return tuple(generator.sample(pass_ids, length))

        population: List[Tuple[str, ...]] = [
            (pass_id,) for pass_id in pass_ids[:population_size]
        ]
        while len(population) < population_size:
            population.append(random_sequence())
        generation_history: List[Dict[str, Any]] = []

        def select_parent(evaluated: List[Dict[str, Any]]) -> Tuple[str, ...]:
            contenders = generator.sample(evaluated, min(2, len(evaluated)))
            valid_contenders = [
                candidate for candidate in contenders if candidate["equivalent"]
            ]
            selected = (
                max(valid_contenders, key=candidate_rank)
                if valid_contenders
                else max(contenders, key=lambda item: item["fitness"])
            )
            return selected["sequence"]

        for generation in range(1, generations + 1):
            evaluated = [evaluate(candidate) for candidate in population]
            valid_evaluated = [
                candidate for candidate in evaluated if candidate["equivalent"]
            ]
            generation_best = (
                max(valid_evaluated, key=candidate_rank)
                if valid_evaluated
                else max(evaluated, key=lambda item: item["fitness"])
            )
            if (
                generation_best["equivalent"]
                and selection_better(generation_best, best)
            ):
                best = generation_best
            for candidate in evaluated:
                if candidate["equivalent"] and selection_better(candidate, best):
                    best = candidate
            generation_history.append(
                {
                    "generation": generation,
                    "best_fitness": best["fitness"],
                    "objective": objective,
                }
            )

            next_population = [generation_best["sequence"] or random_sequence()]
            while len(next_population) < population_size:
                attempts = 0
                while True:
                    first = select_parent(evaluated)
                    second = select_parent(evaluated)
                    first_cut = generator.randint(0, len(first))
                    second_cut = generator.randint(0, len(second))
                    child = tuple(
                        dict.fromkeys(first[:first_cut] + second[second_cut:])
                    )[:max_sequence_length]
                    if not child:
                        child = (generator.choice(pass_ids),)
                    if generator.random() < 0.35:
                        operation = generator.choice(("replace", "insert", "remove"))
                        mutable = list(child)
                        if operation == "replace":
                            index = generator.randrange(len(mutable))
                            available = [
                                pass_id
                                for pass_id in pass_ids
                                if pass_id not in mutable[:index] + mutable[index + 1:]
                            ]
                            if available:
                                mutable[index] = generator.choice(available)
                        elif (
                            operation == "insert"
                            and len(mutable) < min(max_sequence_length, len(pass_ids))
                        ):
                            available = [
                                pass_id for pass_id in pass_ids if pass_id not in mutable
                            ]
                            if available:
                                mutable.insert(
                                    generator.randrange(len(mutable) + 1),
                                    generator.choice(available),
                                )
                        elif operation == "remove" and len(mutable) > 1:
                            mutable.pop(generator.randrange(len(mutable)))
                        child = tuple(mutable)
                    if child not in next_population or attempts >= population_size * 4:
                        next_population.append(child)
                        break
                    attempts += 1
            population = next_population

        for sequence in population:
            result = evaluate(sequence)
            if result["equivalent"] and selection_better(result, best):
                best = result

        optimized_source_path = os.path.join(work_dir, "optimized.c")
        optimized_ir_path = os.path.join(work_dir, "optimized.ll")
        assembly_path = os.path.join(work_dir, "optimized.s")
        with open(optimized_source_path, "w", encoding="utf-8") as file:
            file.write(best["source"])
        _run_compiler(
            [
                "clang", "-std=c11", "-O0", "-S", "-emit-llvm", "-Xclang",
                "-disable-llvm-passes", "-Xclang", "-disable-O0-optnone",
                optimized_source_path, "-o", optimized_ir_path,
            ],
            work_dir,
        )
        _run_compiler(
            ["clang", "-std=c11", "-O0", "-S", optimized_source_path, "-o", assembly_path],
            work_dir,
        )

        optimized_runs = best["runs"]
        optimized_runtime = best["runtime_ms"]
        size_reduction = (
            (original_size - best["binary_size"]) / original_size * 100
            if original_size > 0
            else 0.0
        )
        time_improvement = (
            (original_runtime - optimized_runtime) / original_runtime * 100
            if original_runtime > 0
            else 0.0
        )
        pass_events = []
        pass_events.extend(best["events"])
        for event in pass_events:
            event["candidate_selected"] = True
        transformation_events = [
            event for event in best["events"] if event["changed"]
        ]
        improved = objectively_better(best, baseline)
        candidate_evaluations = []
        for candidate in cache.values():
            if candidate["equivalent"]:
                candidate_status = (
                    "measured_better"
                    if objectively_better(candidate, baseline)
                    else "equivalent_not_better"
                )
                objective_value = candidate["metric"]
                error_message = None
            else:
                candidate_status = "rejected"
                objective_value = None
                error_message = candidate.get("error")
            candidate_evaluations.append(
                {
                    "candidate_id": candidate.get("candidate_id"),
                    "pass_sequence": list(candidate["sequence"]),
                    "status": candidate_status,
                    "objective_value": objective_value,
                    "error_message": error_message,
                    "pass_diagnostics": candidate.get("pass_diagnostics", []),
                    "pass_events": candidate.get("events", []),
                }
            )
        optimized_tac = best["tac"]
        with open(assembly_path, encoding="utf-8") as file:
            assembly = file.read()

        metadata = {
            "optimization_path": "TAC",
            "pass_sequence": list(best["sequence"]),
            "pass_events": pass_events,
            "transformation_events": transformation_events,
            "pass_diagnostics": best["pass_diagnostics"],
            "generation_history": generation_history,
            "generations": generations,
            "population_size": population_size,
            "best_fitness": best["fitness"],
            "objective": objective,
            "equivalent": True,
            "improved": improved,
            "candidate_evaluations": candidate_evaluations,
        }
        return {
            "status": "success",
            "language": "c",
            "optimization_path": "TAC",
            "original_code": source_code,
            "optimized_source": best["source"],
            "original_tac": original_tac,
            "optimized_tac": optimized_tac,
            "optimized_code": assembly,
            "original_stdout": original_signature["stdout"],
            "optimized_stdout": optimized_runs[0]["stdout"],
            "original_execution_time_ms": original_runtime,
            "optimized_execution_time_ms": optimized_runtime,
            "time_improvement_percent": time_improvement,
            "original_instruction_count": len(original_tac),
            "optimized_instruction_count": len(optimized_tac),
            "code_size_reduction_percent": size_reduction,
            "tests_passed": len(optimized_runs),
            "tests_total": len(optimized_runs),
            "pass_sequence": list(best["sequence"]),
            "pass_events": pass_events,
            "transformation_events": transformation_events,
            "pass_diagnostics": best["pass_diagnostics"],
            "generation_history": generation_history,
            "generations": generations,
            "population_size": population_size,
            "best_fitness": best["fitness"],
            "simulation": False,
            "equivalent": True,
            "improved": improved,
            "candidate_evaluations": candidate_evaluations,
            "objective": objective,
            "original_exit_code": original_signature["exit_code"],
            "optimized_exit_code": optimized_runs[0]["exit_code"],
            "original_binary_size": original_size,
            "optimized_binary_size": best["binary_size"],
            "metadata": metadata,
        }


def _llvm_ga_configuration(overrides: Optional[Dict[str, Any]] = None) -> Dict[str, Any]:
    """Read GA settings once, with request values taking precedence over env vars."""
    overrides = overrides or {}

    def value(name: str, default: Any) -> Any:
        if overrides.get(name) is not None:
            return overrides[name]
        return os.getenv(name, default)

    try:
        configuration = {
            "population_size": int(value("population_size", os.getenv("GA_POPULATION_SIZE", "8"))),
            "generations": int(value("generations", os.getenv("GA_GENERATIONS", "5"))),
            "max_chromosome_length": int(
                value("max_chromosome_length", os.getenv("GA_MAX_CHROMOSOME_LENGTH", "5"))
            ),
            "benchmark_runs": int(value("benchmark_runs", os.getenv("GA_BENCHMARK_RUNS", "3"))),
            "tournament_size": int(value("tournament_size", os.getenv("GA_TOURNAMENT_SIZE", "3"))),
            "mutation_probability": float(
                value("mutation_probability", os.getenv("GA_MUTATION_PROBABILITY", "0.35"))
            ),
        }
    except (TypeError, ValueError) as exc:
        raise OptimizationError("LLVM GA configuration values have invalid types.") from exc

    objective = str(value("objective", os.getenv("GA_OBJECTIVE", "execution_time"))).strip().lower()
    seed_value = value("random_seed", os.getenv("GA_RANDOM_SEED", "0"))
    try:
        random_seed = None if seed_value in (None, "", "none", "None") else int(seed_value)
    except (TypeError, ValueError) as exc:
        raise OptimizationError("GA_RANDOM_SEED must be an integer or empty.") from exc
    configuration["objective"] = objective
    configuration["random_seed"] = random_seed

    if configuration["population_size"] < 2:
        raise OptimizationError("GA population size must be at least 2.")
    if configuration["generations"] < 1:
        raise OptimizationError("GA generations must be positive.")
    if configuration["max_chromosome_length"] < 1:
        raise OptimizationError("Maximum chromosome length must be positive.")
    if configuration["benchmark_runs"] < 1:
        raise OptimizationError("Benchmark run count must be positive.")
    if configuration["tournament_size"] < 1:
        raise OptimizationError("Tournament size must be positive.")
    if not 0.0 <= configuration["mutation_probability"] <= 1.0:
        raise OptimizationError("Mutation probability must be between 0 and 1.")
    if objective not in {"execution_time", "binary_size"}:
        raise OptimizationError("GA objective must be execution_time or binary_size.")
    return configuration


def _compile_source_binary(
    clang_path: str,
    source_path: str,
    output_path: str,
    level: str,
    work_dir: str,
    command_records: Optional[List[Dict[str, Any]]] = None,
) -> None:
    command = [clang_path, "-std=c11", f"-{level}", source_path, "-o", output_path]
    if command_records is None:
        _run_compiler(command, work_dir)
    else:
        _run_compiler_recorded(
            command,
            work_dir,
            command_records,
            f"compile_source_{level}",
            output_path=output_path,
        )


def _standard_level_result(
    clang_path: str,
    source_path: str,
    level: str,
    work_dir: str,
    expected: Dict[str, Any],
    benchmark_runs: int,
    command_records: Optional[List[Dict[str, Any]]] = None,
) -> Dict[str, Any]:
    binary = os.path.join(work_dir, f"standard_{level}.out")
    record_start = len(command_records) if command_records is not None else 0
    try:
        _compile_source_binary(
            clang_path, source_path, binary, level, work_dir, command_records
        )
        runs, equivalent = _benchmark(binary, work_dir, expected, benchmark_runs)
        first = runs[0] if runs else {}
        runtime_summary = _runtime_summary(runs) if equivalent else _runtime_summary([])
        return {
            "level": level,
            "compiled": True,
            "equivalent": equivalent,
            "runs": runs,
            "tests_passed": len(runs) if equivalent else 0,
            "tests_total": benchmark_runs,
            "runtime_ms": runtime_summary["runtime_ms"],
            "runtime_spread_ms": runtime_summary["runtime_spread_ms"],
            "runtime_min_ms": runtime_summary["runtime_min_ms"],
            "runtime_max_ms": runtime_summary["runtime_max_ms"],
            "binary_size": os.path.getsize(binary) if os.path.isfile(binary) else None,
            "stdout": first.get("stdout", ""),
            "stderr": first.get("stderr", ""),
            "exit_code": first.get("exit_code"),
            "command_records": (
                command_records[record_start:] if command_records is not None else []
            ),
            "error": None if equivalent else "Standard optimization changed observable behavior.",
        }
    except OptimizationError as exc:
        return {
            "level": level,
            "compiled": False,
            "equivalent": False,
            "runs": [],
            "tests_passed": 0,
            "tests_total": benchmark_runs,
            "runtime_ms": None,
            "runtime_spread_ms": None,
            "runtime_min_ms": None,
            "runtime_max_ms": None,
            "binary_size": None,
            "stdout": "",
            "stderr": "",
            "exit_code": None,
            "command_records": (
                command_records[record_start:] if command_records is not None else []
            ),
            "error": str(exc),
        }


def optimize_c(
    source_code: str,
    expected_original: Optional[Dict[str, Any]] = None,
    ga_config: Optional[Dict[str, Any]] = None,
) -> Dict[str, Any]:
    """Run the real LLVM-pass genetic optimizer for a C program.

    TAC is generated for the existing viewer, but source/TAC rewriting is not
    part of this optimizer. Every chromosome starts from the same pristine IR
    and is evaluated through native LLVM `opt`.
    """
    if len(source_code.encode("utf-8")) > MAX_SOURCE_SIZE_BYTES:
        raise OptimizationError("Source code exceeds the 50 KB optimization limit.")
    configuration = _llvm_ga_configuration(ga_config)
    try:
        clang_path = find_clang()
        opt_path = find_opt()
        active_registry, unsupported_passes = resolve_registry(opt_path, LLVM_PASS_REGISTRY)
        if len(active_registry) < 8:
            raise OptimizationError(
                "The installed LLVM toolchain supports fewer than eight registered passes. "
                f"Supported: {len(active_registry)}; unavailable: {', '.join(unsupported_passes) or 'none'}."
            )
        opt_version = tool_version(opt_path)
    except LLVMToolchainError as exc:
        raise OptimizationError(str(exc)) from exc

    try:
        original_tac = generate_tac(source_code, "c")
    except TacGenerationError:
        # TAC is a separate viewer; unsupported TAC syntax must not reject a
        # source program that Clang can compile and optimize as LLVM IR.
        original_tac = []

    with tempfile.TemporaryDirectory(prefix="llvm_ga_native_") as work_dir:
        command_records: List[Dict[str, Any]] = []
        source_path = os.path.join(work_dir, "source.c")
        original_ir_path = os.path.join(work_dir, "original.ll")
        original_binary = os.path.join(work_dir, "original_O0.out")
        with open(source_path, "w", encoding="utf-8") as source_file:
            source_file.write(source_code)

        original_ir_command = [
            clang_path, "-std=c11", "-O0", "-S", "-emit-llvm",
            "-Xclang", "-disable-llvm-passes", "-Xclang", "-disable-O0-optnone",
            source_path, "-o", original_ir_path,
        ]
        _run_compiler_recorded(
            original_ir_command,
            work_dir,
            command_records,
            "generate_original_o0_ir",
            output_path=original_ir_path,
        )
        verify_command = [opt_path, "-passes=verify", original_ir_path, "-disable-output"]
        try:
            verify_ir(opt_path, original_ir_path, work_dir)
            command_records.append(
                {
                    "stage": "verify_original_ir",
                    "command": verify_command,
                    "cwd": work_dir,
                    "compiler": opt_path,
                    "flags": verify_command[1:],
                    "input_ir_path": original_ir_path,
                    "returncode": 0,
                }
            )
        except LLVMToolchainError as exc:
            command_records.append(
                {
                    "stage": "verify_original_ir",
                    "command": verify_command,
                    "cwd": work_dir,
                    "compiler": opt_path,
                    "flags": verify_command[1:],
                    "input_ir_path": original_ir_path,
                    "returncode": None,
                    "error": str(exc),
                }
            )
            raise OptimizationError(f"Generated LLVM IR failed verification: {exc}") from exc
        _compile_source_binary(
            clang_path, source_path, original_binary, "O0", work_dir, command_records
        )
        original_runs, original_valid = _benchmark(
            original_binary, work_dir, None, configuration["benchmark_runs"]
        )
        if not original_valid or not original_runs:
            raise OptimizationError("Original C program did not complete successfully.")
        original_signature = original_runs[0]
        if any(
            run["exit_code"] != original_signature["exit_code"]
            or run["stdout"] != original_signature["stdout"]
            or run["stderr"] != original_signature["stderr"]
            for run in original_runs
        ):
            raise OptimizationError("Original program produced inconsistent benchmark results.")
        if expected_original is not None and (
            original_signature["exit_code"] != expected_original.get("exit_code")
            or original_signature["stdout"] != expected_original.get("stdout")
            or original_signature["stderr"] != expected_original.get("stderr")
        ):
            raise OptimizationError("Recompiled original output did not match saved execution.")

        expected = original_signature
        standard = {
            level: _standard_level_result(
                clang_path,
                source_path,
                level,
                work_dir,
                expected,
                configuration["benchmark_runs"],
                command_records,
            )
            for level in ("O0", "O1", "O2", "O3")
        }

        original_runtime_summary = _runtime_summary(original_runs)
        original_runtime = original_runtime_summary["runtime_ms"]
        original_size = os.path.getsize(original_binary)
        baseline_metric = (
            original_size
            if configuration["objective"] == "binary_size"
            else original_runtime
        )
        baseline = {
            "candidate_id": "baseline",
            "pass_sequence": [],
            "equivalent": True,
            "compiled": True,
            "fitness": calculate_fitness(baseline_metric, configuration["objective"], True),
            "runtime_ms": original_runtime,
            "runtime_spread_ms": original_runtime_summary["runtime_spread_ms"],
            "runtime_min_ms": original_runtime_summary["runtime_min_ms"],
            "runtime_max_ms": original_runtime_summary["runtime_max_ms"],
            "binary_size": original_size,
            "runs": original_runs,
            "comparison_baseline_runs": original_runs,
            "comparison_baseline_runtime_ms": original_runtime,
            "comparison_baseline_spread_ms": original_runtime_summary["runtime_spread_ms"],
            "tests_passed": len(original_runs),
            "tests_total": configuration["benchmark_runs"],
            "llvm_ir": Path(original_ir_path).read_text(encoding="utf-8"),
            "binary": original_binary,
            "artifact_dir": work_dir,
            "input_ir_path": original_ir_path,
            "output_ir_path": original_ir_path,
            "ir_sha256": ir_fingerprint(original_ir_path),
            "binary_sha256": artifact_fingerprint(original_binary),
            "compiled_from_ir": False,
            "command_records": command_records,
            "cache_hit": False,
            "pass_diagnostics": [],
            "pass_events": [],
            "status": "valid",
            "error": None,
        }

        def objective_metric(evaluation: Dict[str, Any]) -> Optional[float]:
            raw = (
                evaluation.get("binary_size")
                if configuration["objective"] == "binary_size"
                else evaluation.get("runtime_ms")
            )
            return float(raw) if raw is not None else None

        def objectively_better(
            candidate: Dict[str, Any], reference: Dict[str, Any]
        ) -> bool:
            candidate_metric = objective_metric(candidate)
            reference_metric = (
                candidate.get("comparison_baseline_runtime_ms")
                if configuration["objective"] == "execution_time"
                else objective_metric(reference)
            )
            if candidate_metric is None or reference_metric is None:
                return False
            if configuration["objective"] == "binary_size":
                return candidate_metric < reference_metric
            # A single process-startup measurement is not enough evidence for
            # a runtime winner. Keep the samples visible, but do not let a
            # noisy one-run result displace the baseline.
            reference_runs = candidate.get("comparison_baseline_runs") or reference.get("runs", [])
            if len(candidate.get("runs", [])) < 3 or len(reference_runs) < 3:
                return False
            candidate_mad = median_absolute_deviation(
                [run["execution_time_ms"] for run in candidate.get("runs", [])]
            )
            reference_mad = median_absolute_deviation(
                [run["execution_time_ms"] for run in reference_runs]
            )
            minimum_delta = max(0.01, abs(reference_metric) * 0.01)
            return candidate_metric < (
                reference_metric - candidate_mad - reference_mad - minimum_delta
            )

        registry_by_id = registry_map(active_registry)
        rng = random.Random(configuration["random_seed"])
        population = generate_population(
            configuration["population_size"],
            configuration["max_chromosome_length"],
            rng,
            active_registry,
        )
        initial_population = [
            {"candidate_id": chromosome.candidate_id, "pass_sequence": list(chromosome.sequence)}
            for chromosome in population
        ]
        id_counter = configuration["population_size"]
        source_hash = hashlib.sha256(source_code.encode("utf-8")).hexdigest()
        try:
            clang_version = tool_version(clang_path)
        except LLVMToolchainError as exc:
            raise OptimizationError(str(exc)) from exc
        target_config = f"{platform.system()}-{platform.machine()}"
        cache: Dict[Tuple[Any, ...], Dict[str, Any]] = {}
        all_evaluations: List[Dict[str, Any]] = []

        def next_id() -> str:
            nonlocal id_counter
            id_counter += 1
            return f"candidate-{id_counter:04d}"

        def evaluate(chromosome: Chromosome) -> Dict[str, Any]:
            cache_key = (
                source_hash,
                clang_version,
                opt_version,
                chromosome.sequence,
                configuration["objective"],
                configuration["benchmark_runs"],
                configuration["max_chromosome_length"],
                EXECUTION_TIMEOUT_SECONDS,
                MAX_OUTPUT_BYTES,
                DEFAULT_MEMORY_LIMIT_BYTES,
                target_config,
            )
            cached = cache.get(cache_key)
            if cached is not None:
                result = copy.deepcopy(cached)
                result["candidate_id"] = chromosome.candidate_id
                result["cache_hit"] = True
                result["artifact_source_candidate_id"] = cached.get(
                    "artifact_source_candidate_id", cached.get("candidate_id")
                )
                for diagnostic in result.get("pass_diagnostics", []):
                    diagnostic["candidate_id"] = chromosome.candidate_id
                for event in result.get("pass_events", []):
                    event["candidate_id"] = chromosome.candidate_id
                    event["candidate_sequence"] = list(chromosome.sequence)
                chromosome.evaluation = result
                all_evaluations.append(result)
                return result

            pass_diagnostics: List[Dict[str, Any]] = []
            candidate_dir = tempfile.mkdtemp(
                prefix=f"{chromosome.candidate_id}_", dir=work_dir
            )
            command_records: List[Dict[str, Any]] = []
            try:
                sequence_specs = [registry_by_id[pass_id] for pass_id in chromosome.sequence]
                candidate_ir, pass_diagnostics = apply_sequence(
                    opt_path, original_ir_path, sequence_specs, candidate_dir
                )
                for diagnostic in pass_diagnostics:
                    diagnostic["candidate_id"] = chromosome.candidate_id
                    diagnostic["candidate_sequence"] = list(chromosome.sequence)
                candidate_binary = os.path.join(candidate_dir, "candidate.out")
                compile_command = [
                    clang_path, "-x", "ir", "-O0", candidate_ir, "-o", candidate_binary
                ]
                _run_compiler_recorded(
                    compile_command,
                    candidate_dir,
                    command_records,
                    "compile_candidate_ir",
                    input_ir_path=candidate_ir,
                    output_path=candidate_binary,
                )
                comparison_baseline_runs, runs, equivalent = _benchmark_interleaved(
                    original_binary,
                    candidate_binary,
                    work_dir,
                    candidate_dir,
                    expected,
                    configuration["benchmark_runs"],
                )
                runtime_summary = _runtime_summary(runs) if equivalent else _runtime_summary([])
                comparison_summary = (
                    _runtime_summary(comparison_baseline_runs)
                    if equivalent
                    else _runtime_summary([])
                )
                runtime_ms = runtime_summary["runtime_ms"]
                binary_size = os.path.getsize(candidate_binary) if os.path.isfile(candidate_binary) else None
                metric = runtime_ms if configuration["objective"] == "execution_time" else binary_size
                fitness = calculate_fitness(metric, configuration["objective"], equivalent)
                result = {
                    "candidate_id": chromosome.candidate_id,
                    "pass_sequence": list(chromosome.sequence),
                    "equivalent": equivalent,
                    "compiled": True,
                    "fitness": fitness,
                    "runtime_ms": runtime_ms,
                    "runtime_spread_ms": runtime_summary["runtime_spread_ms"],
                    "runtime_min_ms": runtime_summary["runtime_min_ms"],
                    "runtime_max_ms": runtime_summary["runtime_max_ms"],
                    "binary_size": binary_size,
                    "runs": runs,
                    "comparison_baseline_runs": comparison_baseline_runs,
                    "comparison_baseline_runtime_ms": comparison_summary["runtime_ms"],
                    "comparison_baseline_spread_ms": comparison_summary["runtime_spread_ms"],
                    "tests_passed": len(runs) if equivalent else 0,
                    "tests_total": configuration["benchmark_runs"],
                    "llvm_ir": Path(candidate_ir).read_text(encoding="utf-8"),
                    "binary": candidate_binary,
                    "artifact_dir": candidate_dir,
                    "input_ir_path": original_ir_path,
                    "output_ir_path": candidate_ir,
                    "ir_sha256": ir_fingerprint(candidate_ir),
                    "binary_sha256": artifact_fingerprint(candidate_binary),
                    "compiled_from_ir": True,
                    "command_records": command_records,
                    "cache_hit": False,
                    "pass_diagnostics": pass_diagnostics,
                    "pass_events": [
                        {
                            **diagnostic,
                            "description": (
                                "LLVM pass executed and changed IR."
                                if diagnostic.get("ir_changed", diagnostic["changed"])
                                else "LLVM pass executed but produced no observable IR change."
                            ),
                            "changed": diagnostic.get("ir_changed", diagnostic["changed"]),
                        }
                        for diagnostic in pass_diagnostics
                    ],
                    "status": "valid" if equivalent and fitness is not None else "rejected",
                    "error": None if equivalent else "Candidate output or exit status differed from O0.",
                }
            except (OptimizationError, LLVMToolchainError, KeyError, OSError) as exc:
                pass_diagnostics = getattr(exc, "pass_diagnostics", pass_diagnostics)
                for diagnostic in pass_diagnostics:
                    diagnostic.setdefault("candidate_id", chromosome.candidate_id)
                    diagnostic.setdefault("candidate_sequence", list(chromosome.sequence))
                result = {
                    "candidate_id": chromosome.candidate_id,
                    "pass_sequence": list(chromosome.sequence),
                    "equivalent": False,
                    "compiled": False,
                    "fitness": None,
                    "runtime_ms": None,
                    "runtime_spread_ms": None,
                    "runtime_min_ms": None,
                    "runtime_max_ms": None,
                    "binary_size": None,
                    "runs": [],
                    "comparison_baseline_runs": [],
                    "comparison_baseline_runtime_ms": None,
                    "comparison_baseline_spread_ms": None,
                    "tests_passed": 0,
                    "tests_total": configuration["benchmark_runs"],
                    "llvm_ir": None,
                    "binary": None,
                    "artifact_dir": candidate_dir,
                    "input_ir_path": original_ir_path,
                    "output_ir_path": None,
                    "ir_sha256": None,
                    "binary_sha256": None,
                    "compiled_from_ir": False,
                    "command_records": command_records,
                    "cache_hit": False,
                    "pass_diagnostics": pass_diagnostics,
                    "pass_events": [
                        {
                            **diagnostic,
                            "candidate_id": chromosome.candidate_id,
                            "candidate_sequence": list(chromosome.sequence),
                        }
                        for diagnostic in pass_diagnostics
                    ],
                    "status": "rejected",
                    "error": str(exc),
                }
            for diagnostic in pass_diagnostics:
                diagnostic["compiled"] = result.get("compiled", False)
                diagnostic["equivalent"] = result.get("equivalent", False)
                diagnostic["objective_improved"] = bool(
                    result.get("equivalent") and objectively_better(result, baseline)
                )
            for event in result.get("pass_events", []):
                event["ir_changed"] = event.get("ir_changed", event.get("changed", False))
                event["ir_verified"] = event.get("ir_verified", False)
                event["compiled"] = result.get("compiled", False)
                event["equivalent"] = result.get("equivalent", False)
                event["objective_improved"] = bool(
                    result.get("equivalent") and objectively_better(result, baseline)
                )
            cache[cache_key] = copy.deepcopy(result)
            cache[cache_key]["artifact_source_candidate_id"] = chromosome.candidate_id
            chromosome.evaluation = result
            all_evaluations.append(result)
            return result

        def best_valid(evaluated: Sequence[Dict[str, Any]]) -> Optional[Dict[str, Any]]:
            valid = [item for item in evaluated if item.get("equivalent") and item.get("fitness") is not None]
            return max(valid, key=lambda item: item["fitness"]) if valid else None

        generation_history: List[Dict[str, Any]] = []
        global_best: Optional[Dict[str, Any]] = None

        for generation_number in range(1, configuration["generations"] + 1):
            evaluated = [evaluate(chromosome) for chromosome in population]
            for evaluation in evaluated:
                evaluation["generation"] = generation_number
            if generation_number == 1:
                initial_population = [
                    {
                        "candidate_id": evaluation["candidate_id"],
                        "pass_sequence": evaluation["pass_sequence"],
                        "status": evaluation.get("status"),
                        "compiled": evaluation.get("compiled", False),
                        "equivalent": evaluation.get("equivalent", False),
                        "fitness": evaluation.get("fitness"),
                        "runtime_ms": evaluation.get("runtime_ms"),
                        "binary_size": evaluation.get("binary_size"),
                        "tests_passed": evaluation.get("tests_passed", 0),
                        "tests_total": evaluation.get("tests_total", 0),
                        "error_message": evaluation.get("error"),
                    }
                    for evaluation in evaluated
                ]
            generation_best = best_valid(evaluated)
            valid = [item for item in evaluated if item.get("equivalent") and item.get("fitness") is not None]
            if generation_best and (
                global_best is None or generation_best["fitness"] > global_best["fitness"]
            ):
                global_best = copy.deepcopy(generation_best)
            runtime_values = [
                item["runtime_ms"] for item in valid if item.get("runtime_ms") is not None
            ]
            size_values = [
                item["binary_size"] for item in valid if item.get("binary_size") is not None
            ]
            generation_history.append(
                {
                    "generation": generation_number,
                    "best_fitness": generation_best["fitness"] if generation_best else None,
                    "average_fitness": statistics.mean(item["fitness"] for item in valid) if valid else None,
                    "best_execution_time_ms": generation_best.get("runtime_ms") if generation_best else None,
                    "average_execution_time_ms": statistics.mean(runtime_values) if runtime_values else None,
                    "best_binary_size": generation_best.get("binary_size") if generation_best else None,
                    "average_binary_size": statistics.mean(size_values) if size_values else None,
                    "best_pass_sequence": generation_best["pass_sequence"] if generation_best else [],
                    "best_chromosome_id": generation_best["candidate_id"] if generation_best else None,
                    "valid_candidates": len(valid),
                    "rejected_candidates": len(evaluated) - len(valid),
                    "objective": configuration["objective"],
                }
            )

            if generation_best is None:
                # Keep evolving so generation history remains truthful; there
                # is no valid parent, so retain the current population shape.
                continue
            next_population = [
                Chromosome(
                    tuple(generation_best["pass_sequence"]),
                    next_id(),
                    tuple(active_registry),
                    configuration["max_chromosome_length"],
                )
            ]
            while len(next_population) < configuration["population_size"]:
                first = tournament_select(population, rng, configuration["tournament_size"])
                second = tournament_select(population, rng, configuration["tournament_size"])
                child_sequence = one_point_crossover(
                    first.sequence,
                    second.sequence,
                    configuration["max_chromosome_length"],
                    rng,
                    active_registry,
                )
                child_sequence = mutate(
                    child_sequence,
                    configuration["mutation_probability"],
                    configuration["max_chromosome_length"],
                    rng,
                    active_registry,
                )
                next_population.append(
                    Chromosome(
                        child_sequence,
                        next_id(),
                        tuple(active_registry),
                        configuration["max_chromosome_length"],
                    )
                )
            population = next_population

        selected_best = (
            global_best
            if global_best is not None and objectively_better(global_best, baseline)
            else baseline
        )
        selected_result_type = "candidate" if selected_best is not baseline else "baseline"
        selection_reason = (
            "A valid GA candidate beat the original baseline under the configured objective."
            if selected_result_type == "candidate"
            else (
                "Baseline retained: no equivalent GA candidate was available."
                if global_best is None
                else "Baseline retained: no equivalent GA candidate measurably beat the original under the configured objective."
            )
        )

        # Materialize and re-run the selected candidate from its own IR. This
        # is deliberately separate from the per-candidate evaluation cache:
        # the final response must point at the exact IR and native binary that
        # supplied its displayed metrics.
        selected_command_records: List[Dict[str, Any]] = []
        selected_artifact_dir = tempfile.mkdtemp(
            prefix=f"selected_{selected_best['candidate_id']}_", dir=work_dir
        )
        selected_ir_path = os.path.join(selected_artifact_dir, "selected.ll")
        selected_binary_path = os.path.join(selected_artifact_dir, "selected.out")
        with open(selected_ir_path, "w", encoding="utf-8") as selected_ir_file:
            selected_ir_file.write(selected_best["llvm_ir"])
        if selected_result_type == "candidate":
            selected_compile_command = [
                clang_path,
                "-x",
                "ir",
                "-O0",
                selected_ir_path,
                "-o",
                selected_binary_path,
            ]
            try:
                _run_compiler_recorded(
                    selected_compile_command,
                    selected_artifact_dir,
                    selected_command_records,
                    "compile_selected_candidate_ir",
                    input_ir_path=selected_ir_path,
                    output_path=selected_binary_path,
                )
                selected_reference_runs, selected_runs, selected_equivalent = _benchmark_interleaved(
                    original_binary,
                    selected_binary_path,
                    work_dir,
                    selected_artifact_dir,
                    expected,
                    configuration["benchmark_runs"],
                )
            except OptimizationError as exc:
                selected_reference_runs, selected_runs, selected_equivalent = [], [], False
                selected_command_records.append(
                    {"stage": "execute_selected_candidate", "error": str(exc)}
                )
            if not selected_equivalent or not selected_runs:
                selected_best = baseline
                selected_result_type = "baseline"
                selection_reason = (
                    "Baseline retained: final selected-candidate artifact failed the same output/exit-status check."
                )
            else:
                selected_best = copy.deepcopy(selected_best)
                selected_best["runs"] = selected_runs
                selected_best["comparison_baseline_runs"] = selected_reference_runs
                selected_best["equivalent"] = True
                selected_best["compiled"] = True
                selected_runtime_summary = _runtime_summary(selected_runs)
                selected_reference_summary = _runtime_summary(selected_reference_runs)
                selected_best["runtime_ms"] = selected_runtime_summary["runtime_ms"]
                selected_best["runtime_spread_ms"] = selected_runtime_summary["runtime_spread_ms"]
                selected_best["runtime_min_ms"] = selected_runtime_summary["runtime_min_ms"]
                selected_best["runtime_max_ms"] = selected_runtime_summary["runtime_max_ms"]
                selected_best["comparison_baseline_runtime_ms"] = selected_reference_summary["runtime_ms"]
                selected_best["comparison_baseline_spread_ms"] = selected_reference_summary["runtime_spread_ms"]
                selected_best["binary_size"] = os.path.getsize(selected_binary_path)
                selected_best["fitness"] = calculate_fitness(
                    selected_best["runtime_ms"]
                    if configuration["objective"] == "execution_time"
                    else selected_best["binary_size"],
                    configuration["objective"],
                    True,
                )
                if not objectively_better(selected_best, baseline):
                    selected_best = baseline
                    selected_result_type = "baseline"
                    selection_reason = (
                        "Baseline retained: final artifact measurements did not reliably beat the original baseline."
                    )
                else:
                    selected_best["artifact_dir"] = selected_artifact_dir
                    selected_best["input_ir_path"] = original_ir_path
                    selected_best["output_ir_path"] = selected_ir_path
                    selected_best["binary"] = selected_binary_path
                    selected_best["ir_sha256"] = ir_fingerprint(selected_ir_path)
                    selected_best["binary_sha256"] = artifact_fingerprint(selected_binary_path)
                    selected_best["compiled_from_ir"] = True
                    selected_best["command_records"] = selected_command_records
                    selected_best["cache_hit"] = False

        # Update the retained evaluation record when the final materialization
        # succeeded, so sequence, metrics, and artifact identity cannot drift.
        if selected_result_type == "candidate":
            for evaluation in all_evaluations:
                if evaluation.get("candidate_id") == selected_best["candidate_id"]:
                    evaluation.update(
                        {
                            key: copy.deepcopy(selected_best[key])
                            for key in (
                                "runtime_ms",
                                "binary_size",
                                "runs",
                                "fitness",
                                "artifact_dir",
                                "input_ir_path",
                                "output_ir_path",
                                "binary",
                                "ir_sha256",
                                "binary_sha256",
                                "compiled_from_ir",
                                "command_records",
                            )
                            if key in selected_best
                        }
                    )

        best_ir_path = os.path.join(work_dir, "best.ll")
        with open(best_ir_path, "w", encoding="utf-8") as best_ir_file:
            best_ir_file.write(selected_best["llvm_ir"])
        assembly_path = os.path.join(work_dir, "best.s")
        _run_compiler_recorded(
            [clang_path, "-x", "ir", "-S", "-O0", best_ir_path, "-o", assembly_path],
            work_dir,
            selected_command_records,
            "emit_selected_assembly",
            input_ir_path=best_ir_path,
            output_path=assembly_path,
        )
        assembly = Path(assembly_path).read_text(encoding="utf-8")
        best_runtime = selected_best["runtime_ms"]
        best_size = selected_best["binary_size"]
        comparison_baseline_runtime = (
            selected_best.get("comparison_baseline_runtime_ms")
            if selected_result_type == "candidate"
            else baseline["runtime_ms"]
        )
        comparison_baseline_spread = (
            selected_best.get("comparison_baseline_spread_ms")
            if selected_result_type == "candidate"
            else baseline.get("runtime_spread_ms")
        )
        comparison_baseline_samples = (
            selected_best.get("comparison_baseline_runs", [])
            if selected_result_type == "candidate"
            else baseline.get("runs", [])
        )
        o3 = standard["O3"]
        runtime_comparison_reliable = (
            len(selected_best.get("runs", [])) >= 3
            and len(comparison_baseline_samples) >= 3
            and len(o3.get("runs", [])) >= 3
            and o3.get("equivalent")
        )
        benchmark_note = (
            "Runtime comparisons use at least three equivalent samples and a conservative noise margin."
            if runtime_comparison_reliable
            else "Runtime comparison is inconclusive: at least three equivalent samples are required."
        )
        improvement_over_o3 = (
            ((o3["runtime_ms"] - best_runtime) / o3["runtime_ms"] * 100)
            if runtime_comparison_reliable
            and o3.get("equivalent")
            and o3.get("runtime_ms")
            and best_runtime is not None
            else None
        )
        pass_events = copy.deepcopy(selected_best["pass_events"])
        for event in pass_events:
            event["candidate_selected"] = True
            event["candidate_sequence"] = list(selected_best["pass_sequence"])
        transformation_events = [event for event in pass_events if event.get("changed")]
        valid_candidate_records = [
            evaluation
            for evaluation in all_evaluations
            if evaluation.get("candidate_id") != "baseline"
            and evaluation.get("equivalent")
            and evaluation.get("runtime_ms") is not None
        ]
        fastest_measured = min(
            valid_candidate_records,
            key=lambda evaluation: float(evaluation["runtime_ms"]),
            default=None,
        )
        fastest_measured_summary = (
            {
                "candidate_id": fastest_measured["candidate_id"],
                "pass_sequence": list(fastest_measured["pass_sequence"]),
                "runtime_ms": fastest_measured["runtime_ms"],
                "runtime_spread_ms": fastest_measured.get("runtime_spread_ms"),
                "runtime_samples": fastest_measured.get("runs", []),
                "binary_size": fastest_measured.get("binary_size"),
                "equivalent": fastest_measured.get("equivalent", False),
                "fitness": fastest_measured.get("fitness"),
                "cache_hit": fastest_measured.get("cache_hit", False),
            }
            if fastest_measured
            else None
        )
        candidate_evaluations = [
            {
                "candidate_id": evaluation["candidate_id"],
                "pass_sequence": evaluation["pass_sequence"],
                "status": (
                    "rejected"
                    if not evaluation.get("equivalent")
                    else (
                        "measured_better"
                        if objectively_better(evaluation, baseline)
                        else "equivalent_not_better"
                    )
                ),
                "objective_value": objective_metric(evaluation),
                "runtime_ms": evaluation.get("runtime_ms"),
                "runtime_spread_ms": evaluation.get("runtime_spread_ms"),
                "runtime_min_ms": evaluation.get("runtime_min_ms"),
                "runtime_max_ms": evaluation.get("runtime_max_ms"),
                "binary_size": evaluation.get("binary_size"),
                "tests_passed": evaluation.get("tests_passed", 0),
                "tests_total": evaluation.get("tests_total", 0),
                "runs": evaluation.get("runs", []),
                "comparison_baseline_runs": evaluation.get("comparison_baseline_runs", []),
                "comparison_baseline_runtime_ms": evaluation.get("comparison_baseline_runtime_ms"),
                "comparison_baseline_spread_ms": evaluation.get("comparison_baseline_spread_ms"),
                "error_message": evaluation.get("error"),
                "pass_diagnostics": evaluation.get("pass_diagnostics", []),
                "pass_events": evaluation.get("pass_events", []),
                "generation": evaluation.get("generation"),
                "compiled": evaluation.get("compiled", False),
                "equivalent": evaluation.get("equivalent", False),
                "fitness": evaluation.get("fitness"),
                "selected": evaluation["candidate_id"] == selected_best["candidate_id"],
                "artifact_dir": evaluation.get("artifact_dir"),
                "input_ir_path": evaluation.get("input_ir_path"),
                "output_ir_path": evaluation.get("output_ir_path"),
                "ir_sha256": evaluation.get("ir_sha256"),
                "binary_path": evaluation.get("binary"),
                "binary_sha256": evaluation.get("binary_sha256"),
                "compiled_from_ir": evaluation.get("compiled_from_ir", False),
                "command_records": evaluation.get("command_records", []),
                "cache_hit": evaluation.get("cache_hit", False),
            }
            for evaluation in all_evaluations
        ]
        baseline_evaluation = {
            "candidate_id": baseline["candidate_id"],
            "pass_sequence": [],
            "status": "baseline",
            "objective_value": objective_metric(baseline),
            "runtime_ms": baseline["runtime_ms"],
            "runtime_spread_ms": baseline["runtime_spread_ms"],
            "runtime_min_ms": baseline["runtime_min_ms"],
            "runtime_max_ms": baseline["runtime_max_ms"],
            "binary_size": baseline["binary_size"],
            "tests_passed": baseline["tests_passed"],
            "tests_total": baseline["tests_total"],
            "runs": baseline["runs"],
            "comparison_baseline_runs": baseline["comparison_baseline_runs"],
            "comparison_baseline_runtime_ms": baseline["comparison_baseline_runtime_ms"],
            "comparison_baseline_spread_ms": baseline["comparison_baseline_spread_ms"],
            "error_message": None,
            "pass_diagnostics": [],
            "pass_events": [],
            "generation": 0,
            "compiled": True,
            "equivalent": True,
            "fitness": baseline["fitness"],
            "selected": selected_result_type == "baseline",
            "artifact_dir": baseline["artifact_dir"],
            "input_ir_path": baseline["input_ir_path"],
            "output_ir_path": baseline["output_ir_path"],
            "ir_sha256": baseline["ir_sha256"],
            "binary_path": baseline["binary"],
            "binary_sha256": baseline["binary_sha256"],
            "compiled_from_ir": False,
            "command_records": baseline["command_records"],
            "cache_hit": False,
        }
        candidate_evaluations.insert(0, baseline_evaluation)
        evaluated_pass_diagnostics = [
            diagnostic
            for evaluation in candidate_evaluations
            if evaluation["candidate_id"] != "baseline"
            for diagnostic in evaluation.get("pass_diagnostics", [])
        ]
        evaluated_pass_events = [
            event
            for evaluation in candidate_evaluations
            if evaluation["candidate_id"] != "baseline"
            for event in evaluation.get("pass_events", [])
        ]
        selected_artifact = {
            "candidate_id": selected_best["candidate_id"],
            "pass_sequence": list(selected_best["pass_sequence"]),
            "artifact_dir": selected_best.get("artifact_dir"),
            "input_ir_path": selected_best.get("input_ir_path"),
            "output_ir_path": selected_best.get("output_ir_path"),
            "ir_sha256": selected_best.get("ir_sha256"),
            "binary_path": selected_best.get("binary"),
            "binary_sha256": selected_best.get("binary_sha256"),
            "binary_size": selected_best.get("binary_size"),
            "compiled_from_ir": selected_best.get("compiled_from_ir", False),
            "command_records": selected_best.get("command_records", []),
            "ephemeral": True,
            "artifact_lifetime": "request",
        }
        best_valid_ga_candidate = (
            {
                "candidate_id": global_best["candidate_id"],
                "pass_sequence": list(global_best["pass_sequence"]),
                "llvm_ir": global_best.get("llvm_ir"),
                "runtime_ms": global_best.get("runtime_ms"),
                "runtime_spread_ms": global_best.get("runtime_spread_ms"),
                "binary_size": global_best.get("binary_size"),
                "equivalent": global_best.get("equivalent", False),
            }
            if global_best is not None
            else None
        )
        metadata = {
            "optimization_path": "LLVM",
            "toolchain": {
                "clang": clang_version,
                "opt": opt_version,
                "opt_path": opt_path,
                "target": target_config,
            },
            "original_llvm_ir": Path(original_ir_path).read_text(encoding="utf-8"),
            "optimized_llvm_ir": selected_best["llvm_ir"],
            "original_ir": Path(original_ir_path).read_text(encoding="utf-8"),
            "optimized_ir": selected_best["llvm_ir"],
            "original_ir_sha256": ir_fingerprint(original_ir_path),
            "optimized_ir_sha256": selected_best.get("ir_sha256"),
            "pass_registry": [spec.__dict__ for spec in active_registry],
            "unsupported_passes": [
                {"pipeline": pipeline, "reason": "Not exposed by the selected LLVM opt."}
                for pipeline in unsupported_passes
            ],
            "initial_population": initial_population,
            "candidate_evaluations": candidate_evaluations,
            "evaluated_pass_diagnostics": evaluated_pass_diagnostics,
            "evaluated_pass_events": evaluated_pass_events,
            "global_best_chromosome_id": global_best["candidate_id"] if global_best else None,
            "selected_result_type": selected_result_type,
            "selection_reason": selection_reason,
            "generation_history": generation_history,
            "standard_optimizations": standard,
            "configuration": configuration,
            "selected_artifact": selected_artifact,
            "best_valid_ga_candidate": best_valid_ga_candidate,
            "fastest_measured_candidate": fastest_measured_summary,
            "command_records": command_records + selected_command_records,
        }
        return {
            "status": "success",
            "language": "c",
            "optimization_path": "LLVM",
            "original_code": source_code,
            "optimized_source": source_code,
            "original_tac": original_tac,
            "optimized_tac": original_tac,
            "original_llvm_ir": Path(original_ir_path).read_text(encoding="utf-8"),
            "optimized_llvm_ir": selected_best["llvm_ir"],
            "original_ir": Path(original_ir_path).read_text(encoding="utf-8"),
            "optimized_ir": selected_best["llvm_ir"],
            "original_ir_sha256": ir_fingerprint(original_ir_path),
            "optimized_ir_sha256": selected_best.get("ir_sha256"),
            "optimized_code": assembly,
            "original_stdout": expected["stdout"],
            "optimized_stdout": selected_best["runs"][0]["stdout"],
            "original_stderr": expected["stderr"],
            "optimized_stderr": selected_best["runs"][0]["stderr"],
            "original_execution_time_ms": original_runtime,
            "optimized_execution_time_ms": best_runtime,
            "optimized_runtime_spread_ms": selected_best.get("runtime_spread_ms"),
            "optimized_runtime_samples": selected_best.get("runs", []),
            "baseline_runtime_spread_ms": comparison_baseline_spread,
            "baseline_runtime_samples": comparison_baseline_samples,
            "comparison_baseline_runtime_ms": comparison_baseline_runtime,
            "comparison_baseline_spread_ms": comparison_baseline_spread,
            "comparison_baseline_samples": comparison_baseline_samples,
            "time_improvement_percent": (
                ((comparison_baseline_runtime - best_runtime) / comparison_baseline_runtime * 100)
                if runtime_comparison_reliable and comparison_baseline_runtime and best_runtime is not None
                else None
            ),
            "improvement_over_o3_percent": improvement_over_o3,
            "original_instruction_count": len(original_tac),
            "optimized_instruction_count": len(original_tac),
            "code_size_reduction_percent": ((original_size - best_size) / original_size * 100) if original_size else None,
            "tests_passed": selected_best["tests_passed"],
            "tests_total": selected_best["tests_total"],
            "pass_sequence": selected_best["pass_sequence"],
            "best_chromosome_id": selected_best["candidate_id"],
            "global_best_chromosome_id": global_best["candidate_id"] if global_best else None,
            "selected_result_type": selected_result_type,
            "selection_reason": selection_reason,
            "pass_registry": [spec.__dict__ for spec in active_registry],
            "unsupported_passes": [
                {"pipeline": pipeline, "reason": "Not exposed by the selected LLVM opt."}
                for pipeline in unsupported_passes
            ],
            "pass_events": pass_events,
            "transformation_events": transformation_events,
            "pass_diagnostics": selected_best["pass_diagnostics"],
            "initial_population": initial_population,
            "generation_history": generation_history,
            "candidate_evaluations": candidate_evaluations,
            "evaluated_pass_diagnostics": evaluated_pass_diagnostics,
            "evaluated_pass_events": evaluated_pass_events,
            "standard_optimizations": standard,
            "generations": configuration["generations"],
            "population_size": configuration["population_size"],
            "max_chromosome_length": configuration["max_chromosome_length"],
            "mutation_probability": configuration["mutation_probability"],
            "random_seed": configuration["random_seed"],
            "best_fitness": selected_best["fitness"],
            "simulation": False,
            "equivalent": True,
            "improved": selected_best is not baseline,
            "objective": configuration["objective"],
            "benchmark_reliable": runtime_comparison_reliable,
            "benchmark_note": benchmark_note,
            "original_exit_code": expected["exit_code"],
            "optimized_exit_code": selected_best["runs"][0]["exit_code"],
            "original_binary_size": original_size,
            "optimized_binary_size": best_size,
            "selected_artifact": selected_artifact,
            "best_valid_ga_candidate": best_valid_ga_candidate,
            "fastest_measured_candidate": fastest_measured_summary,
            "command_records": command_records + selected_command_records,
            "clang_version": clang_version,
            "metadata": metadata,
        }
