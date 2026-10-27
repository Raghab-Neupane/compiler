export type SupportedLanguage = 'python' | 'c';

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
  language: SupportedLanguage | string;
  source_code: string;
  test_cases?: TestCase[];
}

export interface RunResponse {
  p_id?: string;
  message?: string;
  status: 'completed' | 'failed' | 'timeout' | 'success' | 'error' | string;
  language: string;
  stdout: string;
  output?: string;
  stderr: string;
  exit_code: number;
  execution_time_ms: number;
  tests_passed?: number;
  tests_total?: number;
  test_results?: TestCaseResult[];
  simulation?: boolean;
  error_message?: string;
}

export interface TacInstruction {
  source_line: number;
  instruction: string;
}

export interface OptimizationEvent {
  pass_id: string;
  pass_name: string;
  source_line: number | null;
  description: string;
  changed: boolean;
  ir_changed?: boolean;
  ir_verified?: boolean;
  compiled?: boolean | null;
  equivalent?: boolean | null;
  objective_improved?: boolean | null;
  executed?: boolean;
  transformation_occurred?: boolean;
  candidate_selected?: boolean;
  original_instruction?: string | null;
  replacement?: string | null;
  candidate_sequence?: string[];
}

export interface GenerationFitness {
  generation: number;
  best_fitness: number | null;
  average_fitness?: number | null;
  best_execution_time_ms?: number | null;
  average_execution_time_ms?: number | null;
  best_binary_size?: number | null;
  average_binary_size?: number | null;
  best_pass_sequence?: string[];
  best_chromosome_id?: string | null;
  valid_candidates?: number;
  rejected_candidates?: number;
  objective: string;
}

export interface InitialPopulationCandidate {
  candidate_id: string;
  pass_sequence: string[];
  status?: string;
  compiled?: boolean;
  equivalent?: boolean;
  fitness?: number | null;
  runtime_ms?: number | null;
  binary_size?: number | null;
  tests_passed?: number;
  tests_total?: number;
  error_message?: string | null;
}

export interface LLVMPassSpec {
  pass_id: string;
  display_name: string;
  pipeline: string;
}

export interface StandardOptimizationResult {
  level: string;
  compiled: boolean;
  equivalent: boolean;
  runtime_ms: number | null;
  runtime_spread_ms?: number | null;
  runtime_min_ms?: number | null;
  runtime_max_ms?: number | null;
  binary_size: number | null;
  stdout: string;
  stderr: string;
  exit_code: number | null;
  tests_passed: number;
  tests_total: number;
  error?: string | null;
}

export interface CandidateEvaluation {
  candidate_id: string;
  pass_sequence: string[];
  status: 'baseline' | 'rejected' | 'equivalent_not_better' | 'measured_better';
  objective_value: number | null;
  runtime_ms?: number | null;
  runtime_spread_ms?: number | null;
  runtime_min_ms?: number | null;
  runtime_max_ms?: number | null;
  binary_size?: number | null;
  tests_passed?: number;
  tests_total?: number;
  runs?: Array<Record<string, string | number | boolean>>;
  error_message?: string | null;
  pass_diagnostics?: OptimizationPassDiagnostic[];
  pass_events?: OptimizationEvent[];
  generation?: number;
  compiled?: boolean;
  equivalent?: boolean;
  fitness?: number | null;
  selected?: boolean;
  comparison_baseline_runs?: Array<Record<string, string | number | boolean>>;
  comparison_baseline_runtime_ms?: number | null;
  comparison_baseline_spread_ms?: number | null;
}

export interface TacInstructionChange {
  source_line: number | null;
  removed: TacInstruction[];
  added: TacInstruction[];
}

export interface OptimizationPassDiagnostic {
  candidate_id: string;
  pass_id: string;
  pass_name: string;
  pipeline?: string;
  requested?: boolean;
  executed?: boolean;
  changed?: boolean;
  ir_changed?: boolean;
  ir_verified?: boolean;
  compiled?: boolean | null;
  equivalent?: boolean | null;
  objective_improved?: boolean | null;
  reason?: string;
  instruction_count_before?: number;
  instruction_count_after?: number;
  transformations_applied?: number;
  tac_instruction_changes?: TacInstructionChange[];
  diagnostics?: string;
}

export interface TacResponse {
  p_id: string;
  language: string;
  source_code: string;
  original_tac: string | TacInstruction[];
  optimized_tac: string | TacInstruction[] | null;
  optimized_code: string;
  optimized_stdout: string | null;
  optimized_exit_code: number | null;
  optimized_execution_time_ms: number | null;
  fitness_score: number | null;
  equivalent: boolean | null;
  optimization_status: string;
  pass_sequence?: string[];
  applied_passes?: string[];
  pass_events?: OptimizationEvent[];
  transformation_events?: OptimizationEvent[];
  generation_history?: GenerationFitness[];
  optimization_path?: string;
  best_fitness?: number | null;
  generations?: number;
  population_size?: number;
  improved?: boolean;
  candidate_evaluations?: CandidateEvaluation[];
  pass_diagnostics?: OptimizationPassDiagnostic[];
  error_message?: string;
}

export interface OptimizePayload {
  language: SupportedLanguage | string;
  source_code: string;
  test_cases?: TestCase[];
}

export interface OptimizeResponse {
  status: 'success' | 'error';
  optimization_status: string;
  p_id: string;
  language: string;
  original_code: string;
  optimized_source?: string;
  optimized_code: string;
  original_stdout: string;
  original_stderr?: string;
  optimized_stdout: string;
  optimized_stderr?: string;
  original_tac: string | TacInstruction[];
  optimized_tac: string | TacInstruction[];
  original_llvm_ir?: string;
  optimized_llvm_ir?: string;
  original_ir?: string;
  optimized_ir?: string;
  original_execution_time_ms: number | null;
  optimized_execution_time_ms: number | null;
  optimized_runtime_spread_ms?: number | null;
  optimized_runtime_samples?: Array<Record<string, string | number | boolean>>;
  baseline_runtime_spread_ms?: number | null;
  baseline_runtime_samples?: Array<Record<string, string | number | boolean>>;
  comparison_baseline_runtime_ms?: number | null;
  comparison_baseline_spread_ms?: number | null;
  comparison_baseline_samples?: Array<Record<string, string | number | boolean>>;
  time_improvement_percent: number | null;
  original_instruction_count: number | null;
  optimized_instruction_count: number | null;
  code_size_reduction_percent: number | null;
  tests_passed?: number;
  tests_total?: number;
  test_results?: TestCaseResult[];
  pass_sequence: string[];
  pass_events?: OptimizationEvent[];
  transformation_events?: OptimizationEvent[];
  generation_history?: GenerationFitness[];
  optimization_path?: string;
  best_chromosome_id?: string;
  pass_registry?: LLVMPassSpec[];
  unsupported_passes?: Array<{ pipeline: string; reason: string }>;
  initial_population?: InitialPopulationCandidate[];
  evaluated_pass_diagnostics?: OptimizationPassDiagnostic[];
  evaluated_pass_events?: OptimizationEvent[];
  global_best_chromosome_id?: string | null;
  selected_result_type?: 'baseline' | 'candidate';
  selection_reason?: string;
  standard_optimizations?: Record<string, StandardOptimizationResult>;
  improvement_over_o3_percent?: number | null;
  benchmark_reliable?: boolean;
  benchmark_note?: string;
  max_chromosome_length?: number;
  mutation_probability?: number;
  random_seed?: number | null;
  generations: number;
  population_size: number;
  best_fitness: number | null;
  improved?: boolean;
  candidate_evaluations?: CandidateEvaluation[];
  pass_diagnostics?: OptimizationPassDiagnostic[];
  simulation: boolean;
  equivalent: boolean | null;
  original_exit_code: number | null;
  optimized_exit_code: number | null;
  original_binary_size?: number;
  optimized_binary_size?: number;
  original_ir_sha256?: string;
  optimized_ir_sha256?: string | null;
  best_valid_ga_candidate?: {
    candidate_id: string;
    pass_sequence: string[];
    llvm_ir?: string | null;
    runtime_ms?: number | null;
    runtime_spread_ms?: number | null;
    binary_size?: number | null;
    equivalent: boolean;
  } | null;
  selected_artifact?: {
    candidate_id: string;
    pass_sequence: string[];
    artifact_dir?: string | null;
    input_ir_path?: string | null;
    output_ir_path?: string | null;
    ir_sha256?: string | null;
    binary_path?: string | null;
    binary_sha256?: string | null;
    binary_size?: number | null;
    compiled_from_ir?: boolean;
    artifact_lifetime?: string;
  };
  fastest_measured_candidate?: {
    candidate_id: string;
    pass_sequence: string[];
    runtime_ms?: number | null;
    runtime_spread_ms?: number | null;
    runtime_samples?: Array<Record<string, string | number | boolean>>;
    binary_size?: number | null;
    equivalent?: boolean;
    fitness?: number | null;
    cache_hit?: boolean;
  } | null;
  command_records?: Array<Record<string, unknown>>;
  objective?: string;
  applied_passes?: string[];
  clang_version?: string;
  error_message?: string;
}
