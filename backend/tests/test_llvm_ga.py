import os
import shutil
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path
from unittest import skipUnless
from unittest.mock import patch

from app.ga.chromosome import Chromosome, LLVM_PASS_REGISTRY, PassSpec, validate_sequence
from app.ga.crossover import one_point_crossover
from app.ga.fitness import calculate_fitness, median_metric
from app.ga.llvm_runner import (
    apply_sequence,
    discover_passes,
    find_clang,
    find_opt,
    instruction_count,
    resolve_registry,
)
from app.limited_process import run_limited_process
from app.schemas import CodeRequest
from app.ga.mutation import mutate
from app.ga.population import generate_population
from app.ga.selection import tournament_select
import app.llvm_optimizer as llvm_optimizer
from app.llvm_optimizer import OptimizationError, _llvm_ga_configuration, optimize_c


class LLVMGAModuleTests(unittest.TestCase):
    def test_source_request_rejects_blank_and_oversized_source(self):
        with self.assertRaises(ValueError):
            CodeRequest(language="c", source_code="   ")
        with self.assertRaises(ValueError):
            CodeRequest(language="c", source_code="x" * (50 * 1024 + 1))

    def test_bounded_runner_handles_timeout_and_output_limit(self):
        timed_out = run_limited_process(
            [sys.executable, "-c", "while True: pass"],
            None,
            timeout_seconds=0.1,
            max_output_bytes=1024,
        )
        self.assertTrue(timed_out["timed_out"])
        output_limited = run_limited_process(
            [sys.executable, "-c", "print('x' * 10000)"],
            None,
            timeout_seconds=5,
            max_output_bytes=1024,
        )
        self.assertTrue(output_limited["output_limited"])

    def test_invalid_ga_configurations_are_rejected(self):
        for configuration in (
            {"population_size": 1},
            {"generations": 0},
            {"max_chromosome_length": 0},
            {"benchmark_runs": 0},
            {"mutation_probability": 1.1},
            {"tournament_size": 0},
            {"objective": "unknown"},
        ):
            with self.subTest(configuration=configuration):
                with self.assertRaises(OptimizationError):
                    _llvm_ga_configuration(configuration)

    def test_chromosome_rejects_unknown_pass_and_preserves_order(self):
        chromosome = Chromosome(("instcombine", "gvn", "dce"), "candidate-1")
        self.assertEqual(chromosome.pass_sequence, ("instcombine", "gvn", "dce"))
        with self.assertRaises(ValueError):
            Chromosome(("not-a-real-llvm-pass",), "candidate-2")

    def test_population_is_seeded_with_registered_passes_when_large_enough(self):
        import random

        population = generate_population(12, 3, random.Random(7))
        self.assertEqual(len(population), 12)
        self.assertTrue(all(candidate.validate() for candidate in population))
        self.assertEqual(
            {candidate.sequence[0] for candidate in population[:len(LLVM_PASS_REGISTRY)]},
            {spec.pass_id for spec in LLVM_PASS_REGISTRY},
        )

    def test_crossover_and_mutation_keep_sequences_valid_and_bounded(self):
        import random

        rng = random.Random(11)
        first = ("instcombine", "gvn")
        second = ("dce",)
        child = one_point_crossover(first, second, 3, rng, LLVM_PASS_REGISTRY)
        mutated = mutate(child, 1.0, 3, rng, LLVM_PASS_REGISTRY)
        self.assertGreaterEqual(len(mutated), 1)
        self.assertLessEqual(len(mutated), 3)
        validate_sequence(mutated, LLVM_PASS_REGISTRY, 3)

    def test_selection_prefers_equivalent_candidates(self):
        import random

        candidates = [
            Chromosome(("dce",), "bad", evaluation={"equivalent": False, "fitness": 100.0}),
            Chromosome(("instcombine",), "good", evaluation={"equivalent": True, "fitness": 0.1}),
        ]
        selected = tournament_select(candidates, random.Random(1), tournament_size=2)
        self.assertEqual(selected.candidate_id, "good")

    def test_fitness_rejects_incorrect_candidates_and_keeps_raw_metric(self):
        self.assertIsNone(calculate_fitness(1.0, "execution_time", False))
        self.assertEqual(calculate_fitness(4.0, "execution_time", True), 0.25)
        self.assertEqual(calculate_fitness(128, "binary_size", True), 1 / 128)
        self.assertEqual(median_metric([3.0, 1.0, 2.0]), 2.0)

    def test_pass_discovery_parser_uses_actual_opt_output(self):
        with tempfile.TemporaryDirectory(prefix="fake_opt_") as directory:
            executable = Path(directory) / "opt"
            executable.write_text(
                "#!/bin/sh\n"
                "if [ \"$1\" = \"--print-passes\" ]; then\n"
                "  echo '  --simplifycfg, --instcombine, --sroa'\n"
                "fi\n",
                encoding="utf-8",
            )
            executable.chmod(0o755)
            self.assertEqual(discover_passes(str(executable)), {"simplifycfg", "instcombine", "sroa"})

    def test_registry_resolution_reports_missing_passes_without_substitution(self):
        with tempfile.TemporaryDirectory(prefix="partial_opt_") as directory:
            executable = Path(directory) / "opt"
            executable.write_text(
                "#!/bin/sh\n"
                "if [ \"$1\" = \"--print-passes\" ]; then\n"
                "  echo '  --simplifycfg, --instcombine'\n"
                "fi\n",
                encoding="utf-8",
            )
            executable.chmod(0o755)
            supported, missing = resolve_registry(str(executable), LLVM_PASS_REGISTRY)
            self.assertEqual([spec.pass_id for spec in supported], ["simplifycfg", "instcombine"])
            self.assertIn("sroa", missing)

    def test_instruction_count_reads_real_ir_lines(self):
        with tempfile.TemporaryDirectory(prefix="llvm_ir_count_") as directory:
            ir = Path(directory) / "input.ll"
            ir.write_text("define i32 @main() {\nentry:\n  %x = add i32 1, 2\n  ret i32 %x\n}\n", encoding="utf-8")
            self.assertEqual(instruction_count(str(ir)), 2)

    def test_ga_orchestration_records_no_change_for_a_pass_through_opt(self):
        """Exercise the full evaluator without pretending a fake opt is LLVM."""
        source = "int main(void) { return 0; }\n"
        with tempfile.TemporaryDirectory(prefix="pass_through_opt_") as directory:
            executable = Path(directory) / "opt"
            executable.write_text(
                "#!/usr/bin/env python3\n"
                "import shutil, sys\n"
                "if '--print-passes' in sys.argv:\n"
                "    print('  --simplifycfg, --instcombine, --sroa, --early-cse, --reassociate, --gvn, --dce, --adce, --loop-simplify, --licm, --indvars')\n"
                "    raise SystemExit(0)\n"
                "if '--version' in sys.argv:\n"
                "    print('fake opt for orchestration tests')\n"
                "    raise SystemExit(0)\n"
                "if '-passes=verify' in sys.argv:\n"
                "    raise SystemExit(0)\n"
                "output = sys.argv[sys.argv.index('-o') + 1]\n"
                "inputs = [arg for arg in sys.argv[1:] if arg.endswith('.ll') and arg != output]\n"
                "shutil.copyfile(inputs[0], output)\n",
                encoding="utf-8",
            )
            executable.chmod(0o755)
            with patch.dict(os.environ, {"LLVM_OPT": str(executable)}):
                result = optimize_c(
                    source,
                    {"exit_code": 0, "stdout": "", "stderr": ""},
                    {"population_size": 2, "generations": 1, "max_chromosome_length": 1, "benchmark_runs": 1, "random_seed": 1, "objective": "binary_size"},
                )
        self.assertEqual(result["optimization_path"], "LLVM")
        self.assertEqual(result["pass_sequence"], [])
        self.assertFalse(result["improved"])
        self.assertTrue(result["pass_diagnostics"] == [])
        self.assertEqual(result["generation_history"][0]["valid_candidates"], 2)
        diagnostics = next(
            candidate["pass_diagnostics"]
            for candidate in result["candidate_evaluations"]
            if candidate["candidate_id"] != "baseline"
        )
        self.assertTrue(diagnostics[0]["requested"])
        self.assertTrue(diagnostics[0]["executed"])
        self.assertFalse(diagnostics[0]["changed"])
        self.assertIn("without an observable", diagnostics[0]["reason"])

    def test_baseline_is_returned_when_all_ga_candidates_fail(self):
        source = "int main(void) { return 0; }\n"
        with tempfile.TemporaryDirectory(prefix="failing_opt_") as directory:
            executable = Path(directory) / "opt"
            executable.write_text(
                "#!/usr/bin/env python3\n"
                "import sys\n"
                "if '--print-passes' in sys.argv:\n"
                "    print('  --simplifycfg, --instcombine, --sroa, --early-cse, --reassociate, --gvn, --dce, --adce, --loop-simplify, --licm, --indvars')\n"
                "    raise SystemExit(0)\n"
                "if '--version' in sys.argv:\n"
                "    print('fake failing opt')\n"
                "    raise SystemExit(0)\n"
                "if '-passes=verify' in sys.argv:\n"
                "    raise SystemExit(0)\n"
                "output = sys.argv[sys.argv.index('-o') + 1]\n"
                "open(output, 'w', encoding='utf-8').write('not LLVM IR\\n')\n",
                encoding="utf-8",
            )
            executable.chmod(0o755)
            with patch.dict(os.environ, {"LLVM_OPT": str(executable)}):
                result = optimize_c(
                    source,
                    {"exit_code": 0, "stdout": "", "stderr": ""},
                    {"population_size": 2, "generations": 1, "max_chromosome_length": 1, "benchmark_runs": 1, "random_seed": 1, "objective": "binary_size"},
                )
        self.assertEqual(result["best_chromosome_id"], "baseline")
        self.assertEqual(result["selected_result_type"], "baseline")
        self.assertIsNone(result["global_best_chromosome_id"])
        self.assertEqual(result["optimized_stdout"], "")
        self.assertEqual(sum(candidate["status"] == "rejected" for candidate in result["candidate_evaluations"]), 2)

    def test_one_failed_llvm_pass_does_not_abort_other_candidates(self):
        source = "int main(void) { return 0; }\n"
        with tempfile.TemporaryDirectory(prefix="instcombine_failure_opt_") as directory:
            executable = Path(directory) / "opt"
            executable.write_text(
                "#!/usr/bin/env python3\n"
                "import shutil, sys\n"
                "if '--print-passes' in sys.argv:\n"
                "    print('  --simplifycfg, --instcombine, --sroa, --early-cse, --reassociate, --gvn, --dce, --adce, --loop-simplify, --licm, --indvars')\n"
                "    raise SystemExit(0)\n"
                "if '--version' in sys.argv:\n"
                "    print('fake instcombine failure opt')\n"
                "    raise SystemExit(0)\n"
                "if '-passes=verify' in sys.argv:\n"
                "    raise SystemExit(0)\n"
                "if '-passes=instcombine' in sys.argv:\n"
                "    print('instcombine fixpoint failure', file=sys.stderr)\n"
                "    raise SystemExit(1)\n"
                "output = sys.argv[sys.argv.index('-o') + 1]\n"
                "inputs = [arg for arg in sys.argv[1:] if arg.endswith('.ll') and arg != output]\n"
                "shutil.copyfile(inputs[0], output)\n",
                encoding="utf-8",
            )
            executable.chmod(0o755)
            with patch.dict(os.environ, {"LLVM_OPT": str(executable)}):
                result = optimize_c(
                    source,
                    {"exit_code": 0, "stdout": "", "stderr": ""},
                    {
                        "population_size": 2,
                        "generations": 1,
                        "max_chromosome_length": 1,
                        "benchmark_runs": 1,
                        "random_seed": 1,
                        "objective": "binary_size",
                    },
                )
        self.assertEqual(result["generation_history"][0]["valid_candidates"], 1)
        instcombine = next(
            diagnostic
            for candidate in result["candidate_evaluations"]
            for diagnostic in candidate["pass_diagnostics"]
            if diagnostic["pass_id"] == "instcombine"
        )
        self.assertTrue(instcombine["requested"])
        self.assertFalse(instcombine["executed"])
        self.assertEqual(instcombine["returncode"], 1)
        self.assertIn("fixpoint failure", instcombine["diagnostics"])


_NATIVE_OPT = shutil.which("opt") or os.getenv("LLVM_OPT") or next(
    (
        path
        for path in ("/opt/homebrew/opt/llvm/bin/opt", "/usr/local/opt/llvm/bin/opt")
        if os.path.isfile(path)
    ),
    None,
)


@skipUnless(_NATIVE_OPT, "LLVM opt is not installed")
class NativeLLVMGAIntegrationTests(unittest.TestCase):
    def test_candidate_win_keeps_selected_ir_and_metrics_aligned(self):
        source = "int main(void) { return 0; }\n"

        def deterministic_interleaved(*args, **kwargs):
            candidate_path = args[1]

            def sample(milliseconds):
                return {
                    "exit_code": 0,
                    "stdout": "",
                    "stderr": "",
                    "execution_time_ms": milliseconds,
                    "timed_out": False,
                    "output_limited": False,
                }

            reference = [sample(10.0), sample(10.0), sample(10.0)]
            candidate = [sample(5.0), sample(5.0), sample(5.0)]
            return reference, candidate, True

        with patch.object(llvm_optimizer, "_benchmark_interleaved", deterministic_interleaved):
            result = optimize_c(
                source,
                {"exit_code": 0, "stdout": "", "stderr": ""},
                {
                    "population_size": 2,
                    "generations": 1,
                    "max_chromosome_length": 1,
                    "benchmark_runs": 3,
                    "random_seed": 1,
                    "objective": "execution_time",
                },
            )

        self.assertEqual(result["selected_result_type"], "candidate")
        self.assertNotEqual(result["best_chromosome_id"], "baseline")
        self.assertEqual(result["optimized_ir"], result["optimized_llvm_ir"])
        self.assertEqual(result["selected_artifact"]["candidate_id"], result["best_chromosome_id"])
        self.assertTrue(result["selected_artifact"]["compiled_from_ir"])
        self.assertEqual(result["optimized_execution_time_ms"], 5.0)
        self.assertEqual(result["optimized_runtime_spread_ms"], 0.0)
        selected = next(item for item in result["candidate_evaluations"] if item["selected"])
        self.assertEqual(selected["candidate_id"], result["best_chromosome_id"])
        self.assertEqual(selected["runtime_ms"], result["optimized_execution_time_ms"])

    def test_native_ga_evaluates_equivalent_candidates_and_standard_levels(self):
        source = """
#include <stdio.h>
int main(void) {
    int x = 4 * 5;
    printf("%d\\n", x);
    return 0;
}
"""
        result = optimize_c(
            source,
            {"exit_code": 0, "stdout": "20\n", "stderr": ""},
            {
                "population_size": 8,
                "generations": 2,
                "max_chromosome_length": 2,
                "benchmark_runs": 1,
                "random_seed": 3,
                "objective": "binary_size",
            },
        )
        self.assertEqual(result["optimization_path"], "LLVM")
        self.assertTrue(result["equivalent"])
        self.assertEqual(set(result["standard_optimizations"]), {"O0", "O1", "O2", "O3"})
        self.assertEqual(len(result["generation_history"]), 2)
        self.assertEqual(len(result["initial_population"]), 8)
        self.assertTrue(result["pass_registry"])
        self.assertTrue(result["candidate_evaluations"])
        candidate_ids = [candidate["candidate_id"] for candidate in result["candidate_evaluations"]]
        self.assertEqual(len(candidate_ids), len(set(candidate_ids)))
        self.assertTrue(
            all(
                diagnostic["candidate_id"] == candidate["candidate_id"]
                for candidate in result["candidate_evaluations"]
                for diagnostic in candidate["pass_diagnostics"]
            )
        )
        self.assertTrue(
            any(
                diagnostic["executed"]
                for candidate in result["candidate_evaluations"]
                for diagnostic in candidate["pass_diagnostics"]
            )
        )
        self.assertTrue(
            all(
                "ir_verified" in diagnostic
                and "compiled" in diagnostic
                and "equivalent" in diagnostic
                and "objective_improved" in diagnostic
                for candidate in result["candidate_evaluations"]
                for diagnostic in candidate["pass_diagnostics"]
            )
        )
        self.assertEqual(result["optimized_stdout"], "20\n")
        self.assertTrue(result["command_records"])
        selected = next(
            candidate
            for candidate in result["candidate_evaluations"]
            if candidate["selected"]
        )
        self.assertEqual(selected["candidate_id"], result["best_chromosome_id"])
        self.assertEqual(selected["pass_sequence"], result["pass_sequence"])
        self.assertEqual(selected["runtime_ms"], result["optimized_execution_time_ms"])
        self.assertEqual(selected["binary_size"], result["optimized_binary_size"])
        self.assertEqual(
            result["selected_artifact"]["candidate_id"], result["best_chromosome_id"]
        )
        self.assertTrue(result["selected_artifact"]["ir_sha256"])
        self.assertTrue(result["selected_artifact"]["binary_sha256"])
        if result["selected_result_type"] == "candidate":
            self.assertTrue(result["selected_artifact"]["compiled_from_ir"])
            self.assertTrue(
                any(
                    record["stage"] == "compile_selected_candidate_ir"
                    for record in result["selected_artifact"]["command_records"]
                )
            )

    def test_repeated_instcombine_passes_verify_and_produce_ir(self):
        source = "int main(void) { int x = 4 * 5; return x; }\n"
        with tempfile.TemporaryDirectory(prefix="repeated_llvm_pass_") as directory:
            source_path = Path(directory) / "source.c"
            ir_path = Path(directory) / "original.ll"
            source_path.write_text(source, encoding="utf-8")
            subprocess.run(
                [
                    find_clang(), "-O0", "-S", "-emit-llvm",
                    "-Xclang", "-disable-llvm-passes",
                    "-Xclang", "-disable-O0-optnone",
                    str(source_path), "-o", str(ir_path),
                ],
                check=True,
                capture_output=True,
                text=True,
            )
            specs = [spec for spec in LLVM_PASS_REGISTRY if spec.pass_id == "instcombine"]
            candidate_ir, diagnostics = apply_sequence(
                find_opt(), str(ir_path), specs * 2, directory
            )
            self.assertTrue(Path(candidate_ir).is_file())
            self.assertEqual(len(diagnostics), 2)
            self.assertTrue(all(item["executed"] and item["ir_verified"] for item in diagnostics))

    def test_nonzero_exit_status_is_part_of_equivalence(self):
        source = "int main(void) { return 7; }\n"
        result = optimize_c(
            source,
            {"exit_code": 7, "stdout": "", "stderr": ""},
            {
                "population_size": 2,
                "generations": 1,
                "max_chromosome_length": 1,
                "benchmark_runs": 1,
                "random_seed": 9,
                "objective": "binary_size",
            },
        )
        self.assertTrue(result["equivalent"])
        self.assertEqual(result["optimized_exit_code"], 7)

    def test_representative_program_family_preserves_equivalence(self):
        programs = [
            ("int main(void){int a[4]={1,2,3,4}; int s=0; for(int i=0;i<4;i++) s+=a[i]*2; return s==20?0:1;}\n", 0),
            ("int fib(int n){return n<2?n:fib(n-1)+fib(n-2);} int main(void){return fib(8)==21?0:1;}\n", 0),
            ("struct Pair { int left; int right; }; int main(void){struct Pair p={3,4}; int *q=&p.left; return *q+p.right==7?0:1;}\n", 0),
            ("int main(void){int x=3; switch(x){case 1:return 1; case 3:return 0; default:return 2;}}\n", 0),
            ("int main(void){double x=0.5; double y=x*4.0+1.0; return y==3.0?0:1;}\n", 0),
        ]
        for source, exit_code in programs:
            with self.subTest(source=source):
                result = optimize_c(
                    source,
                    {"exit_code": exit_code, "stdout": "", "stderr": ""},
                    {
                        "population_size": 2,
                        "generations": 1,
                        "max_chromosome_length": 1,
                        "benchmark_runs": 1,
                        "random_seed": 13,
                        "objective": "binary_size",
                    },
                )
                self.assertTrue(result["equivalent"])
                self.assertEqual(result["optimized_exit_code"], exit_code)

    def test_matrix_multiplication_retains_output_and_exit_status(self):
        source = r'''
#include <stdio.h>
#define N 3
int main(void) {
    int A[N][N] = {{1, 2, 3}, {4, 5, 6}, {7, 8, 9}};
    int B[N][N] = {{9, 8, 7}, {6, 5, 4}, {3, 2, 1}};
    int C[N][N] = {0};
    int unused = 100 * 200;
    int i, j, k;
    for (i = 0; i < N; i++) {
        for (j = 0; j < N; j++) {
            for (k = 0; k < N; k++) {
                int index = i * N + j;
                int duplicate = i * N + j;
                int product = A[i][k] * B[k][j];
                C[i][j] = C[i][j] + product;
                C[i][j] = C[i][j] + 0;
            }
        }
    }
    for (i = 0; i < N; i++) {
        for (j = 0; j < N; j++) printf("%d ", C[i][j]);
        printf("\n");
    }
    return 0;
}
'''
        expected = "30 24 18 \n84 69 54 \n138 114 90 \n"
        result = optimize_c(
            source,
            {"exit_code": 0, "stdout": expected, "stderr": ""},
            {
                "population_size": 2,
                "generations": 1,
                "max_chromosome_length": 1,
                "benchmark_runs": 1,
                "random_seed": 5,
                "objective": "binary_size",
            },
        )
        self.assertTrue(result["equivalent"])
        self.assertEqual(result["optimized_stdout"], expected)
        self.assertEqual(result["optimized_exit_code"], 0)
        self.assertEqual(len(result["standard_optimizations"]), 4)
        self.assertTrue(any(item["pass_diagnostics"] for item in result["candidate_evaluations"][1:]))


if __name__ == "__main__":
    unittest.main()
