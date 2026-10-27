import os
import shutil
import subprocess
import tempfile
import unittest
import json
from pathlib import Path
from unittest.mock import Mock, patch

from app import database, routes
from app.llvm_optimizer import _apply_tac_pass, _tac_instruction_changes, optimize_tac
from app.schemas import OptimizationRequest
from app.tac_generator import generate_tac


REGRESSION_SOURCE = """#include <stdio.h>
int main(void) {
    int a = 10;
    int b = 20;
    int constant = 4 * 5;
    int copy1 = a;
    int copy2 = copy1;
    int sum1 = a + b;
    int sum2 = a + b;
    int unused1 = 3;
    int unused2 = unused1 + 4;
    int total = 0;
    for (int i = 0; i < 10; i++) {
        total += i * 4;
    }
    int result = constant + copy2 + sum1 + sum2 + total;
    printf("Constant: %d\\n", constant);
    printf("Copy: %d\\n", copy2);
    printf("Sum 1: %d\\n", sum1);
    printf("Sum 2: %d\\n", sum2);
    printf("Total: %d\\n", total);
    printf("Result: %d\\n", result);
    return 0;
}
"""
EXPECTED_OUTPUT = (
    "Constant: 20\n"
    "Copy: 10\n"
    "Sum 1: 30\n"
    "Sum 2: 30\n"
    "Total: 180\n"
    "Result: 270\n"
)

PROGRAM_FIXTURES = {
    "Matrix Multiplication": (
        """#include <stdio.h>
int main(void) {
    int a[3][3] = {{1,2,3},{4,5,6},{7,8,9}};
    int b[3][3] = {{9,8,7},{6,5,4},{3,2,1}};
    int c[3][3] = {{0}};
    for (int i = 0; i < 3; i++) {
        for (int j = 0; j < 3; j++) {
            for (int k = 0; k < 3; k++) {
                c[i][j] += a[i][k] * b[k][j];
            }
        }
    }
    for (int i = 0; i < 3; i++) {
        for (int j = 0; j < 3; j++) {
            printf("%d", c[i][j]);
            if (j < 2) printf(" ");
        }
        printf("\\n");
    }
    return 0;
}
""",
        "30 24 18\n84 69 54\n138 114 90\n",
    ),
    "Bubble Sort": (
        """#include <stdio.h>
int main(void) {
    int values[6] = {5,1,4,2,6,3};
    for (int i = 0; i < 6; i++) {
        for (int j = 0; j < 5 - i; j++) {
            if (values[j] > values[j + 1]) {
                int temporary = values[j];
                values[j] = values[j + 1];
                values[j + 1] = temporary;
            }
        }
    }
    for (int i = 0; i < 6; i++) {
        printf("%d", values[i]);
        if (i < 5) printf(" ");
    }
    printf("\\n");
    return 0;
}
""",
        "1 2 3 4 5 6\n",
    ),
    "Quick Sort": (
        """#include <stdio.h>
void quick_sort(int values[], int low, int high) {
    int i = low;
    int j = high;
    int pivot = values[(low + high) / 2];
    while (i <= j) {
        while (values[i] < pivot) i++;
        while (values[j] > pivot) j--;
        if (i <= j) {
            int temporary = values[i];
            values[i] = values[j];
            values[j] = temporary;
            i++;
            j--;
        }
    }
    if (low < j) quick_sort(values, low, j);
    if (i < high) quick_sort(values, i, high);
}
int main(void) {
    int values[7] = {5,3,8,1,9,2,7};
    quick_sort(values, 0, 6);
    for (int i = 0; i < 7; i++) {
        printf("%d", values[i]);
        if (i < 6) printf(" ");
    }
    printf("\\n");
    return 0;
}
""",
        "1 2 3 5 7 8 9\n",
    ),
    "Prime Generation": (
        """#include <stdio.h>
int main(void) {
    int count = 0;
    for (int number = 2; number <= 29; number++) {
        int prime = 1;
        for (int divisor = 2; divisor * divisor <= number; divisor++) {
            if (number % divisor == 0) prime = 0;
        }
        if (prime) {
            printf("%d", number);
            if (count < 9) printf(" ");
            count++;
        }
    }
    printf("\\n");
    return 0;
}
""",
        "2 3 5 7 11 13 17 19 23 29\n",
    ),
    "Fibonacci": (
        """#include <stdio.h>
int main(void) {
    int previous = 0;
    int current = 1;
    for (int index = 1; index < 11; index++) {
        int next = previous + current;
        previous = current;
        current = next;
    }
    printf("%d\\n", current);
    return 0;
}
""",
        "89\n",
    ),
    "Array Processing": (
        """#include <stdio.h>
int main(void) {
    int values[6] = {2,3,4,23,4,6};
    int sum = 0;
    int weighted = 0;
    for (int index = 0; index < 6; index++) {
        sum += values[index];
        weighted += values[index] * (index + 1);
    }
    printf("sum %d\\n", sum);
    printf("weighted %d\\n", weighted);
    return 0;
}
""",
        "sum 42\nweighted 168\n",
    ),
    "Polynomial Evaluation": (
        """#include <stdio.h>
int main(void) {
    int x = 3;
    int value = 2 * x * x + 3 * x + 4;
    printf("%d\\n", value);
    return 0;
}
""",
        "31\n",
    ),
    "Matrix Transpose": (
        """#include <stdio.h>
int main(void) {
    int matrix[3][3] = {{1,2,3},{4,5,6},{7,8,9}};
    int transposed[3][3] = {{0}};
    for (int i = 0; i < 3; i++) {
        for (int j = 0; j < 3; j++) {
            transposed[j][i] = matrix[i][j];
        }
    }
    for (int i = 0; i < 3; i++) {
        for (int j = 0; j < 3; j++) {
            printf("%d", transposed[i][j]);
            if (j < 2) printf(" ");
        }
        printf("\\n");
    }
    return 0;
}
""",
        "1 4 7\n2 5 8\n3 6 9\n",
    ),
    "Searching": (
        """#include <stdio.h>
int main(void) {
    int values[6] = {8,3,14,6,21,9};
    int target = 21;
    int found = -1;
    for (int index = 0; index < 6; index++) {
        if (values[index] == target) found = index;
    }
    printf("index %d\\n", found);
    return 0;
}
""",
        "index 4\n",
    ),
    "Numerical Loops": (
        """#include <stdio.h>
int main(void) {
    int total = 0;
    for (int i = 1; i < 100; i++) {
        total += i * 8;
    }
    printf("%d\\n", total);
    return 0;
}
""",
        "39600\n",
    ),
}


class TacOptimizationPassTests(unittest.TestCase):
    def test_constant_folding_preserves_c_integer_division(self) -> None:
        source = """int main(void) {
    int quotient = -7 / 3;
    return quotient == -2 ? 0 : 1;
}
"""
        optimized, events = _apply_tac_pass(source, "CF")
        self.assertIn("int quotient = -2;", optimized)
        self.assertEqual(events[0]["original_instruction"], "int quotient = -7 / 3;")
        self.assertEqual(events[0]["replacement"], "int quotient = -2;")

    def test_copy_propagation_invalidates_reassigned_sources(self) -> None:
        source = """int main(void) {
    int a = 10;
    int copy1 = a;
    a = 12;
    int copy2 = copy1;
    return copy2;
}
"""
        optimized, events = _apply_tac_pass(source, "CP")
        self.assertEqual(optimized, source)
        self.assertFalse(any(event["changed"] for event in events))

    def test_copy_propagation_reaches_expression_uses(self) -> None:
        source = """int main(void) {
    int a = 10;
    int copy1 = a;
    int copy2 = copy1;
    int result = copy2 + 5;
    return result;
}
"""
        optimized, events = _apply_tac_pass(source, "CP")
        self.assertIn("int copy2 = a;", optimized)
        self.assertIn("int result = a + 5;", optimized)
        self.assertEqual(
            [event["original_instruction"] for event in events],
            ["int copy2 = copy1;", "int result = copy2 + 5;"],
        )
        self.assertEqual(
            [event["replacement"] for event in events],
            ["int copy2 = a;", "int result = a + 5;"],
        )

    def test_copy_propagation_does_not_cross_control_flow(self) -> None:
        source = """int main(void) {
    int a = 10;
    int copy = a;
    if (a > 0) {
        a = 12;
    }
    int result = copy + a;
    return result;
}
"""
        optimized, events = _apply_tac_pass(source, "CP")
        self.assertIn("int result = copy + a;", optimized)
        self.assertFalse(
            any(event["original_instruction"] == "int result = copy + a;" for event in events)
        )

    def test_cse_handles_commuted_expressions_and_invalidates_reassignments(self) -> None:
        source = """int main(void) {
    int a = 4;
    int b = 5;
    int first = a + b;
    int second = b + a;
    a = 8;
    int third = a + b;
    return first + second + third;
}
"""
        optimized, events = _apply_tac_pass(source, "CSE")
        self.assertIn("int second = first;", optimized)
        self.assertIn("int third = a + b;", optimized)
        self.assertEqual(
            [event["original_instruction"] for event in events],
            ["int second = b + a;"],
        )

    def test_cse_does_not_reuse_across_control_flow(self) -> None:
        source = """int main(void) {
    int a = 4;
    int b = 5;
    int first = a + b;
    if (a > 0) {
        b = 7;
    }
    int second = a + b;
    return first + second;
}
"""
        optimized, events = _apply_tac_pass(source, "CSE")
        self.assertEqual(optimized, source)
        self.assertFalse(any(event["changed"] for event in events))

    def test_dead_code_elimination_preserves_global_writes(self) -> None:
        source = """int state = 0;
int main(void) {
    state = 1;
    return 0;
}
"""
        optimized, events = _apply_tac_pass(source, "DCE")
        self.assertEqual(optimized, source)
        self.assertFalse(any(event["changed"] for event in events))

    def test_passes_preserve_volatile_reads(self) -> None:
        source = """int main(void) {
    volatile int state = 10;
    int copy = state;
    int first = state + 2;
    int second = state + 2;
    int unused = state;
    return copy + first + second;
}
"""
        propagated, cp_events = _apply_tac_pass(source, "CP")
        self.assertEqual(propagated, source)
        self.assertFalse(any(event["changed"] for event in cp_events))

        commoned, cse_events = _apply_tac_pass(source, "CSE")
        self.assertEqual(commoned, source)
        self.assertFalse(any(event["changed"] for event in cse_events))

        cleaned, dce_events = _apply_tac_pass(source, "DCE")
        self.assertIn("int unused = state;", cleaned)
        self.assertFalse(any(event["original_instruction"] == "int unused = state;" for event in dce_events))

    def test_tac_diagnostics_report_removed_operations_not_temp_renumbering(self) -> None:
        original_tac = generate_tac(REGRESSION_SOURCE, "c")
        dce_source, _ = _apply_tac_pass(REGRESSION_SOURCE, "DCE")
        dce_tac = generate_tac(dce_source, "c")
        changes = _tac_instruction_changes(original_tac, dce_tac)
        removed = [
            instruction["instruction"]
            for change in changes
            for instruction in change["removed"]
        ]
        added = [
            instruction["instruction"]
            for change in changes
            for instruction in change["added"]
        ]
        self.assertIn("unused1 = 3", removed)
        self.assertIn("unused2 = t4", removed)
        self.assertEqual(added, [])

    def test_five_regression_program_passes(self) -> None:
        constant_folded, cf_events = _apply_tac_pass(REGRESSION_SOURCE, "CF")
        self.assertIn("int constant = 20;", constant_folded)
        self.assertEqual(cf_events[0]["replacement"], "int constant = 20;")
        self.assertIn(
            "constant = 20",
            [item["instruction"] for item in generate_tac(constant_folded, "c")],
        )

        propagated, cp_events = _apply_tac_pass(REGRESSION_SOURCE, "CP")
        self.assertIn("int copy2 = a;", propagated)
        self.assertEqual(cp_events[0]["original_instruction"], "int copy2 = copy1;")
        self.assertIn(
            "copy2 = a",
            [item["instruction"] for item in generate_tac(propagated, "c")],
        )
        self.assertIn(
            "t7 = constant + a",
            [item["instruction"] for item in generate_tac(propagated, "c")],
        )

        commoned, cse_events = _apply_tac_pass(REGRESSION_SOURCE, "CSE")
        self.assertIn("int sum2 = sum1;", commoned)
        self.assertEqual(cse_events[0]["replacement"], "int sum2 = sum1;")
        self.assertIn(
            "sum2 = sum1",
            [item["instruction"] for item in generate_tac(commoned, "c")],
        )

        dead_code_removed, dce_events = _apply_tac_pass(REGRESSION_SOURCE, "DCE")
        self.assertNotIn("unused1", dead_code_removed)
        self.assertNotIn("unused2", dead_code_removed)
        optimized_dce_tac = [
            item["instruction"] for item in generate_tac(dead_code_removed, "c")
        ]
        self.assertFalse(any("unused1" in item or "unused2" in item for item in optimized_dce_tac))
        self.assertEqual(
            [event["original_instruction"] for event in dce_events],
            ["int unused2 = unused1 + 4;", "int unused1 = 3;"],
        )

        strength_reduced, sr_events = _apply_tac_pass(REGRESSION_SOURCE, "SR")
        self.assertNotEqual(strength_reduced, REGRESSION_SOURCE)
        self.assertIn("int __tac_strength_reduced = 0;", strength_reduced)
        self.assertIn(
            "total += __tac_strength_reduced; __tac_strength_reduced += 4;",
            strength_reduced,
        )
        self.assertNotIn("total += i * 4;", strength_reduced)
        self.assertTrue(sr_events[0]["changed"])
        self.assertEqual(sr_events[0]["original_instruction"], "t6 = i * 4")

    def test_strength_reduction_rejects_possible_signed_overflow(self) -> None:
        source = """int main(void) {
    int total = 0;
    for (int i = 2147483646; i < 2147483647; i++) {
        total += i * 4;
    }
    return total;
}
"""
        optimized, events = _apply_tac_pass(source, "SR")
        self.assertEqual(optimized, source)
        self.assertFalse(events[0]["changed"])
        self.assertIn("signed-int pattern", events[0]["description"])

    def test_strength_reduction_i_times_8_preserves_execution(self) -> None:
        source = """#include <stdio.h>
int main(void) {
    int total = 0;
    for (int i = 0; i < 10; i++) {
        total += i * 8;
    }
    printf("%d\\n", total);
    return 0;
}
"""
        optimized, events = _apply_tac_pass(source, "SR")
        self.assertIn(
            "total += __tac_strength_reduced; __tac_strength_reduced += 8;",
            optimized,
        )
        self.assertTrue(events[0]["changed"])

        clang = shutil.which("clang")
        if clang is None:
            self.fail("Clang is required for strength-reduction execution verification.")
        with tempfile.TemporaryDirectory(prefix="tac_strength_reduction_") as directory:
            runs = []
            for name, candidate in (("original", source), ("optimized", optimized)):
                source_path = Path(directory) / f"{name}.c"
                executable = Path(directory) / name
                source_path.write_text(candidate, encoding="utf-8")
                subprocess.run(
                    [clang, "-std=c11", str(source_path), "-o", str(executable)],
                    check=True,
                    capture_output=True,
                    text=True,
                    timeout=15,
                )
                runs.append(
                    subprocess.run(
                        [str(executable)],
                        capture_output=True,
                        text=True,
                        timeout=5,
                        check=False,
                    )
                )
        self.assertEqual(runs[0].returncode, runs[1].returncode)
        self.assertEqual(runs[0].stdout, "360\n")
        self.assertEqual(runs[1].stdout, runs[0].stdout)
        self.assertEqual(runs[1].stderr, runs[0].stderr)

    def test_transformed_candidate_preserves_program_output(self) -> None:
        clang = shutil.which("clang")
        if clang is None:
            self.fail("Clang is required for the candidate execution regression test.")
        candidate = REGRESSION_SOURCE
        for pass_id in ("CF", "CP", "CSE", "DCE", "SR"):
            candidate, _ = _apply_tac_pass(candidate, pass_id)

        with tempfile.TemporaryDirectory(prefix="tac_pass_test_") as directory:
            source_path = Path(directory) / "candidate.c"
            executable_path = Path(directory) / "candidate"
            source_path.write_text(candidate, encoding="utf-8")
            subprocess.run(
                [clang, "-std=c11", str(source_path), "-o", str(executable_path)],
                check=True,
                capture_output=True,
                text=True,
                timeout=15,
            )
            run = subprocess.run(
                [str(executable_path)],
                check=True,
                capture_output=True,
                text=True,
                timeout=5,
            )
        self.assertEqual(run.stdout, EXPECTED_OUTPUT)
        self.assertEqual(run.returncode, 0)

    def test_full_ga_returns_selected_tac_when_objective_ties(self) -> None:
        environment = {
            "GA_POPULATION_SIZE": "6",
            "GA_GENERATIONS": "3",
            "GA_MAX_SEQUENCE_LENGTH": "3",
            "GA_BENCHMARK_RUNS": "2",
            "GA_OBJECTIVE": "binary_size",
        }
        job = {
            "language": "c",
            "exit_code": 0,
            "source_code": REGRESSION_SOURCE,
            "original_stdout": EXPECTED_OUTPUT,
            "original_stderr": "",
            "execution_time_ms": 1,
        }
        with patch.dict(os.environ, environment):
            with (
                patch.object(routes, "get_compilation_job", return_value=job),
                patch.object(routes, "save_optimization_run") as save_result,
            ):
                with patch.object(
                    routes,
                    "optimize_c",
                    side_effect=lambda source, expected, _config: optimize_tac(source, expected),
                ):
                    result = routes.optimize_job(OptimizationRequest(p_id="test-p_id"))

        save_result.assert_called_once_with("test-p_id", result)
        self.assertEqual(result["original_stdout"], EXPECTED_OUTPUT)
        self.assertEqual(result["optimized_stdout"], EXPECTED_OUTPUT)
        self.assertEqual(result["original_exit_code"], 0)
        self.assertEqual(result["optimized_exit_code"], 0)
        self.assertTrue(result["equivalent"])
        self.assertEqual(result["objective"], "binary_size")
        self.assertEqual(result["original_tac"], generate_tac(REGRESSION_SOURCE, "c"))
        self.assertEqual(
            result["optimized_tac"],
            generate_tac(result["optimized_source"], "c"),
        )
        self.assertTrue(
            all(
                len(candidate["pass_sequence"])
                == len(set(candidate["pass_sequence"]))
                for candidate in result["candidate_evaluations"]
            )
        )
        if not result["improved"]:
            self.assertFalse(result["improved"])
            self.assertEqual(result["optimized_tac"], result["original_tac"])
            self.assertEqual(result["optimized_source"], REGRESSION_SOURCE)
            self.assertEqual(result["pass_sequence"], [])
            self.assertEqual(result["pass_events"], [])
            self.assertEqual(result["transformation_events"], [])
            self.assertEqual(result["pass_diagnostics"], [])
            self.assertEqual(
                [entry["best_fitness"] for entry in result["generation_history"]],
                [result["best_fitness"]] * result["generations"],
            )
        else:
            self.assertTrue(result["improved"])
            self.assertTrue(result["pass_sequence"])
            self.assertTrue(result["transformation_events"])
            self.assertTrue(result["pass_diagnostics"])
            self.assertTrue(
                all(
                    event["candidate_id"]
                    == result["pass_diagnostics"][0]["candidate_id"]
                    for event in result["pass_events"]
                )
            )
            self.assertTrue(
                all(
                    event["candidate_selected"]
                    and event["candidate_sequence"] == result["pass_sequence"]
                    for event in result["pass_events"]
                )
            )

        connection = Mock()
        cursor = connection.cursor.return_value
        cursor.fetchone.side_effect = [("test-p_id",), ("optimization-row",)]
        with patch.object(database, "get_connection", return_value=connection):
            database.save_optimization_run("test-p_id", result)

        saved_values = cursor.execute.call_args_list[-1].args[1]
        self.assertEqual(json.loads(saved_values[0]), result["original_tac"])
        self.assertEqual(json.loads(saved_values[1]), result["optimized_tac"])
        stored_optimization = json.loads(saved_values[2])
        self.assertEqual(
            stored_optimization["metadata"]["pass_diagnostics"],
            result["pass_diagnostics"],
        )
        self.assertEqual(
            stored_optimization["metadata"]["pass_events"],
            result["pass_events"],
        )

        stored_row = {
            "original_tac": json.dumps(result["original_tac"]),
            "optimized_tac": json.dumps(result["optimized_tac"]),
            "optimized_code": saved_values[2],
        }
        read_connection = Mock()
        read_cursor = read_connection.cursor.return_value
        read_cursor.fetchone.return_value = stored_row
        with patch.object(database, "get_connection", return_value=read_connection):
            loaded = database.get_optimization_result("test-p_id")
        self.assertEqual(loaded["optimized_tac"], result["optimized_tac"])
        self.assertEqual(
            loaded["optimization_metadata"]["pass_diagnostics"],
            result["pass_diagnostics"],
        )
        self.assertEqual(
            loaded["optimization_metadata"]["pass_events"],
            result["pass_events"],
        )

    def test_execution_time_fitness_uses_measured_median(self) -> None:
        environment = {
            "GA_POPULATION_SIZE": "2",
            "GA_GENERATIONS": "1",
            "GA_MAX_SEQUENCE_LENGTH": "1",
            "GA_BENCHMARK_RUNS": "3",
            "GA_OBJECTIVE": "execution_time",
        }
        with patch.dict(os.environ, environment):
            result = optimize_tac(REGRESSION_SOURCE)

        self.assertEqual(result["objective"], "execution_time")
        self.assertGreater(result["original_execution_time_ms"], 0)
        self.assertGreater(result["optimized_execution_time_ms"], 0)
        self.assertAlmostEqual(
            result["best_fitness"],
            1.0 / max(result["optimized_execution_time_ms"], 1.0),
        )
        self.assertEqual(result["original_stdout"], result["optimized_stdout"])
        self.assertEqual(result["original_exit_code"], result["optimized_exit_code"])

    def test_ten_program_regression_fixtures(self) -> None:
        environment = {
            "GA_POPULATION_SIZE": "2",
            "GA_GENERATIONS": "1",
            "GA_MAX_SEQUENCE_LENGTH": "1",
            "GA_BENCHMARK_RUNS": "1",
            "GA_OBJECTIVE": "binary_size",
        }
        clang = shutil.which("clang")
        if clang is None:
            self.fail("Clang is required for the ten-program regression suite.")

        with tempfile.TemporaryDirectory(prefix="tac_fixture_baseline_") as directory:
            for index, (name, (source, expected_output)) in enumerate(PROGRAM_FIXTURES.items()):
                with self.subTest(program=name):
                    source_path = Path(directory) / f"fixture_{index}.c"
                    executable = Path(directory) / f"fixture_{index}"
                    source_path.write_text(source, encoding="utf-8")
                    subprocess.run(
                        [clang, "-std=c11", str(source_path), "-o", str(executable)],
                        check=True,
                        capture_output=True,
                        text=True,
                        timeout=15,
                    )
                    baseline = subprocess.run(
                        [str(executable)],
                        capture_output=True,
                        text=True,
                        timeout=5,
                        check=False,
                    )
                    self.assertEqual(baseline.returncode, 0, name)
                    self.assertEqual(baseline.stdout, expected_output, name)
                    original_tac = generate_tac(source, "c")
                    self.assertTrue(original_tac, name)
                    if name == "Matrix Multiplication":
                        instructions = [item["instruction"] for item in original_tac]
                        self.assertEqual(
                            sum(instruction.startswith("label for_cond_") for instruction in instructions),
                            5,
                        )
                        self.assertTrue(any("= load a[" in instruction for instruction in instructions))
                        self.assertTrue(any("= load b[" in instruction for instruction in instructions))
                        self.assertTrue(any(instruction.startswith("c[") and " = " in instruction for instruction in instructions))
                        self.assertTrue(any(" * " in instruction for instruction in instructions))

                    for pass_id in ("CF", "CP", "DCE", "CSE", "SR"):
                        candidate_source, events = _apply_tac_pass(source, pass_id)
                        self.assertTrue(events, f"{name}: {pass_id} must report evaluation")
                        candidate_path = Path(directory) / f"fixture_{index}_{pass_id}.c"
                        candidate_binary = Path(directory) / f"fixture_{index}_{pass_id}"
                        candidate_path.write_text(candidate_source, encoding="utf-8")
                        subprocess.run(
                            [clang, "-std=c11", str(candidate_path), "-o", str(candidate_binary)],
                            check=True,
                            capture_output=True,
                            text=True,
                            timeout=15,
                        )
                        optimized_run = subprocess.run(
                            [str(candidate_binary)],
                            capture_output=True,
                            text=True,
                            timeout=5,
                            check=False,
                        )
                        self.assertEqual(optimized_run.returncode, baseline.returncode, name)
                        self.assertEqual(optimized_run.stdout, baseline.stdout, name)
                        self.assertEqual(optimized_run.stderr, baseline.stderr, name)

                    with patch.dict(os.environ, environment):
                        result = optimize_tac(
                            source,
                            {
                                "exit_code": baseline.returncode,
                                "stdout": baseline.stdout,
                                "stderr": baseline.stderr,
                            },
                        )
                    self.assertTrue(result["equivalent"], name)
                    self.assertEqual(result["original_stdout"], expected_output, name)
                    self.assertEqual(result["optimized_stdout"], expected_output, name)
                    self.assertEqual(result["original_exit_code"], baseline.returncode, name)
                    self.assertEqual(result["optimized_exit_code"], baseline.returncode, name)
                    self.assertEqual(result["original_tac"], original_tac, name)
                    self.assertEqual(
                        result["optimized_tac"],
                        generate_tac(result["optimized_source"], "c"),
                        name,
                    )
                    self.assertTrue(
                        all(event["candidate_id"] == result["pass_diagnostics"][0]["candidate_id"]
                            for event in result["pass_events"]),
                        name,
                    )
                    self.assertTrue(
                        all(event["candidate_selected"] for event in result["pass_events"]),
                        name,
                    )


if __name__ == "__main__":
    unittest.main()
