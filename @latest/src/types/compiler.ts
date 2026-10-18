export interface TestCase {
  id: string;
  input: string;
  expected_output: string;
}

export interface TestCaseResult {
  id: string;
  passed: boolean;
  actual_output: string;
  expected_output: string;
  error?: string;
}

export interface RunPayload {
  language: 'python';
  source_code: string;
  test_cases: TestCase[];
}

export interface RunResponse {
  status: 'success' | 'error' | 'timeout';
  language: 'python';
  stdout: string;
  stderr: string;
  exit_code: number;
  execution_time_ms: number;
  tests_passed: number;
  tests_total: number;
  test_results: TestCaseResult[];
  simulation?: boolean;
  error_message?: string;
}

export interface OptimizePayload {
  language: 'python';
  source_code: string;
  test_cases: TestCase[];
}

export interface OptimizeResponse {
  status: 'success' | 'error';
  language: 'python';
  original_stdout: string;
  optimized_stdout: string;
  original_tac: string[];
  optimized_tac: string[];
  original_execution_time_ms: number;
  optimized_execution_time_ms: number;
  time_improvement_percent: number;
  original_instruction_count: number;
  optimized_instruction_count: number;
  code_size_reduction_percent: number;
  tests_passed: number;
  tests_total: number;
  test_results?: TestCaseResult[];
  pass_sequence: string[];
  generations: number;
  population_size: number;
  best_fitness: number;
  simulation: boolean;
  error_message?: string;
}
