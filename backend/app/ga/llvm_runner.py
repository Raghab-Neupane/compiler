from __future__ import annotations

import hashlib
import os
import shutil
import subprocess
from pathlib import Path
from typing import Dict, Iterable, List, Sequence, Tuple

from .chromosome import PassSpec


class LLVMToolchainError(RuntimeError):
    pass


def _run(command: Sequence[str], cwd: str, timeout: int = 15) -> subprocess.CompletedProcess[str]:
    try:
        result = subprocess.run(
            list(command), cwd=cwd, capture_output=True, text=True, timeout=timeout, check=False
        )
    except subprocess.TimeoutExpired as exc:
        raise LLVMToolchainError("LLVM toolchain command timed out.") from exc
    except OSError as exc:
        raise LLVMToolchainError(f"Unable to start LLVM toolchain command: {exc}") from exc
    if result.returncode != 0:
        detail = (result.stderr or result.stdout or "LLVM toolchain command failed.").strip()
        error = LLVMToolchainError(detail[-4000:])
        error.returncode = result.returncode
        error.stdout = result.stdout
        error.stderr = result.stderr
        error.command = list(command)
        raise error
    return result


def find_opt() -> str:
    configured = os.getenv("LLVM_OPT")
    candidates = []
    if configured:
        candidates.append(configured)
    candidates.extend(
        [
            shutil.which("opt") or "",
            "/opt/homebrew/opt/llvm/bin/opt",
            "/usr/local/opt/llvm/bin/opt",
        ]
    )
    path = next((candidate for candidate in candidates if candidate and os.path.isfile(candidate)), None)
    if not path:
        raise LLVMToolchainError(
            "The LLVM `opt` executable is required for native LLVM pass-sequence optimization. "
            "Set LLVM_OPT or install the LLVM tools package."
        )
    return path


def find_clang() -> str:
    configured = os.getenv("LLVM_CLANG")
    candidates = []
    if configured:
        candidates.append(configured)
    candidates.extend(
        [
            "/opt/homebrew/opt/llvm/bin/clang",
            "/usr/local/opt/llvm/bin/clang",
            shutil.which("clang") or "",
        ]
    )
    path = next((candidate for candidate in candidates if candidate and os.path.isfile(candidate)), None)
    if not path:
        raise LLVMToolchainError(
            "A compatible LLVM `clang` executable is required. "
            "Set LLVM_CLANG or install the LLVM tools package."
        )
    return path


def discover_passes(opt_path: str) -> set[str]:
    result = _run((opt_path, "--print-passes"), os.getcwd())
    passes: set[str] = set()
    for line in result.stdout.splitlines():
        line = line.strip()
        if line and not line.startswith("Passes:") and not line.startswith("Target-specific"):
            passes.update(
                token.strip().lstrip("-").split("<", 1)[0]
                for token in line.split(",")
                if token.strip()
            )
    return passes


def validate_registry(opt_path: str, registry: Sequence[PassSpec]) -> None:
    _, missing = resolve_registry(opt_path, registry)
    if missing:
        raise LLVMToolchainError(
            "Installed LLVM opt does not support registered pass(es): " + ", ".join(missing)
        )


def resolve_registry(
    opt_path: str, registry: Sequence[PassSpec]
) -> Tuple[Tuple[PassSpec, ...], Tuple[str, ...]]:
    """Return the registered passes supported by this exact opt executable.

    A newer or older LLVM may omit a pass or expose a different pipeline name.
    Unsupported entries are reported to the caller instead of being silently
    replaced or making all otherwise-valid candidates unusable.
    """
    available = discover_passes(opt_path)
    supported = tuple(spec for spec in registry if spec.pipeline in available)
    missing = tuple(spec.pipeline for spec in registry if spec.pipeline not in available)
    return supported, missing


def tool_version(executable: str) -> str:
    result = _run((executable, "--version"), os.getcwd(), timeout=5)
    return result.stdout.splitlines()[0] if result.stdout else executable


def ir_fingerprint(path: str) -> str:
    return hashlib.sha256(Path(path).read_bytes()).hexdigest()


def artifact_fingerprint(path: str) -> str:
    """Return the content identity of an emitted IR or native artifact."""
    return ir_fingerprint(path)


def instruction_count(path: str) -> int:
    return sum(
        bool(line.strip())
        and not line.lstrip().startswith((";", "!", "attributes", "source_filename"))
        and ("=" in line or line.lstrip().startswith(("ret ", "br ", "switch ", "store ", "call ")))
        for line in Path(path).read_text(encoding="utf-8").splitlines()
    )


def verify_ir(opt_path: str, ir_path: str, work_dir: str) -> None:
    """Verify an LLVM module with the new pass manager before GA evaluation."""
    _run((opt_path, "-passes=verify", ir_path, "-disable-output"), work_dir)


def apply_pass(
    opt_path: str,
    input_ir: str,
    output_ir: str,
    spec: PassSpec,
    work_dir: str,
) -> Dict[str, object]:
    if os.path.exists(output_ir):
        os.remove(output_ir)
    before_hash = ir_fingerprint(input_ir)
    before_count = instruction_count(input_ir)
    result = _run(
        (
            opt_path,
            "-S",
            "-verify-each",
            "-debug-pass-manager",
            f"-passes={spec.pipeline}",
            input_ir,
            "-o",
            output_ir,
        ),
        work_dir,
    )
    if not os.path.isfile(output_ir):
        raise LLVMToolchainError(
            f"LLVM pass {spec.pipeline} completed without producing an IR output file."
        )
    after_hash = ir_fingerprint(output_ir)
    after_count = instruction_count(output_ir)
    ir_changed = before_hash != after_hash
    return {
        "pass_id": spec.pass_id,
        "pass_name": spec.display_name,
        "pipeline": spec.pipeline,
        "requested": True,
        "executed": True,
        "changed": ir_changed,
        "ir_changed": ir_changed,
        "ir_verified": True,
        "compiled": None,
        "equivalent": None,
        "objective_improved": None,
        "reason": (
            "Pass executed and changed the LLVM IR."
            if ir_changed
            else "Pass executed without an observable LLVM IR change."
        ),
        "instruction_count_before": before_count,
        "instruction_count_after": after_count,
        "command": list(result.args) if isinstance(result.args, (list, tuple)) else [str(result.args)],
        "cwd": work_dir,
        "returncode": result.returncode,
        "input_ir_path": input_ir,
        "output_ir_path": output_ir,
        "tool": opt_path,
        "diagnostics": result.stderr[-4000:],
    }


def apply_sequence(
    opt_path: str,
    original_ir: str,
    sequence: Sequence[PassSpec],
    work_dir: str,
) -> Tuple[str, List[Dict[str, object]]]:
    current = original_ir
    diagnostics: List[Dict[str, object]] = []
    for index, spec in enumerate(sequence):
        output = os.path.join(work_dir, f"pass_{index}.ll")
        try:
            diagnostics.append(apply_pass(opt_path, current, output, spec, work_dir))
        except LLVMToolchainError as exc:
            diagnostics.append(
                {
                    "pass_id": spec.pass_id,
                    "pass_name": spec.display_name,
                    "pipeline": spec.pipeline,
                    "requested": True,
                    "executed": False,
                    "changed": False,
                    "ir_changed": False,
                    "ir_verified": False,
                    "compiled": False,
                    "equivalent": False,
                    "objective_improved": False,
                    "reason": "Pass could not be executed by the installed LLVM toolchain.",
                    "command": [
                        opt_path,
                        "-S",
                        "-verify-each",
                        "-debug-pass-manager",
                        f"-passes={spec.pipeline}",
                        current,
                        "-o",
                        output,
                    ],
                    "cwd": work_dir,
                    "returncode": getattr(exc, "returncode", None),
                    "input_ir_path": current,
                    "output_ir_path": output,
                    "tool": opt_path,
                    "diagnostics": getattr(exc, "stderr", None) or str(exc),
                }
            )
            exc.pass_diagnostics = diagnostics
            raise
        current = output
    return current, diagnostics
