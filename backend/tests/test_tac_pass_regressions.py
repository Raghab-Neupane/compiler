import shutil
import subprocess
import tempfile
import unittest
from pathlib import Path

from app.llvm_optimizer import _apply_tac_pass
from app.tac_generator import generate_tac


class FocusedTacPassRegressionTests(unittest.TestCase):
    def compile_and_run(self, original: str, optimized: str) -> None:
        clang = shutil.which("clang")
        if clang is None:
            self.skipTest("Clang is required for TAC equivalence checks.")
        with tempfile.TemporaryDirectory(prefix="tac_focused_") as directory:
            results = []
            for name, source in (("original", original), ("optimized", optimized)):
                source_path = Path(directory) / f"{name}.c"
                binary_path = Path(directory) / name
                source_path.write_text(source, encoding="utf-8")
                subprocess.run(
                    [clang, "-std=c11", str(source_path), "-o", str(binary_path)],
                    check=True,
                    capture_output=True,
                    text=True,
                    timeout=15,
                )
                results.append(
                    subprocess.run(
                        [str(binary_path)],
                        check=False,
                        capture_output=True,
                        text=True,
                        timeout=5,
                    )
                )
            self.assertEqual(results[0].returncode, results[1].returncode)
            self.assertEqual(results[0].stdout, results[1].stdout)
            self.assertEqual(results[0].stderr, results[1].stderr)

    def assert_transformed_and_equivalent(self, source: str, pass_id: str, needle: str) -> None:
        before_tac = generate_tac(source, "c")
        optimized, events = _apply_tac_pass(source, pass_id)
        after_tac = generate_tac(optimized, "c")
        changed = [event for event in events if event["changed"]]
        self.assertTrue(changed, events)
        self.assertIn(needle, optimized)
        self.assertNotEqual(before_tac, after_tac)
        self.assertTrue(all(event["pass_id"] == pass_id for event in events))
        self.compile_and_run(source, optimized)

    def test_cf_folds_constant_arithmetic(self) -> None:
        source = """#include <stdio.h>
int main(void) {
    int x = 4 * 5;
    printf("%d\\n", x);
    return 0;
}
"""
        self.assert_transformed_and_equivalent(source, "CF", "int x = 20;")

    def test_cp_propagates_straight_line_copies(self) -> None:
        source = """#include <stdio.h>
int main(void) {
    int a = 10;
    int b = a;
    int c = b + 5;
    printf("%d\\n", c);
    return 0;
}
"""
        self.assert_transformed_and_equivalent(source, "CP", "int c = a + 5;")

    def test_cse_reuses_repeated_expression(self) -> None:
        source = """#include <stdio.h>
int main(void) {
    int a = 10;
    int b = 20;
    int x = a + b;
    int y = a + b;
    printf("%d\\n", y);
    return 0;
}
"""
        self.assert_transformed_and_equivalent(source, "CSE", "int y = x;")

    def test_dce_removes_unused_pure_assignment(self) -> None:
        source = """#include <stdio.h>
int main(void) {
    int unused = 4 + 5;
    printf("ok\\n");
    return 0;
}
"""
        optimized, events = _apply_tac_pass(source, "DCE")
        self.assertNotIn("int unused", optimized)
        self.assertTrue(any(event["changed"] for event in events))
        self.assertNotEqual(generate_tac(source, "c"), generate_tac(optimized, "c"))
        self.compile_and_run(source, optimized)

    def test_sr_accepts_another_tac_instruction_in_loop_body(self) -> None:
        source = """#include <stdio.h>
int main(void) {
    int total = 0;
    for (int i = 0; i < 10; i++) {
        int scratch = i + 1;
        total += i * 4;
    }
    printf("%d\\n", total);
    return 0;
}
"""
        optimized, events = _apply_tac_pass(source, "SR")
        self.assertTrue(any(event["changed"] for event in events), events)
        self.assertIn("total += __tac_strength_reduced;", optimized)
        self.assertNotIn("total += i * 4;", optimized)
        self.assertNotEqual(generate_tac(source, "c"), generate_tac(optimized, "c"))
        self.compile_and_run(source, optimized)


if __name__ == "__main__":
    unittest.main()
