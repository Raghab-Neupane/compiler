/**
 * Compiler API Service
 * 
 * Connects frontend editor to the real FastAPI Python execution backend.
 */

const BACKEND_URL = 'http://127.0.0.1:8000';

/**
 * Evaluates test cases by comparing trimmed stdout against trimmed expected output.
 */
function evaluateTestCases(testCases = [], stdout = '') {
  const trimmedStdout = (stdout || '').trim();

  return testCases.map((tc) => {
    const trimmedExpected = (tc.expected_output || '').trim();
    const passed = trimmedStdout === trimmedExpected;

    return {
      id: tc.id,
      passed,
      actual_output: trimmedStdout,
      expected_output: trimmedExpected,
    };
  });
}

/**
 * Sends Python source code to the real FastAPI backend for execution.
 * 
 * @param {Object} payload 
 * @returns {Promise<Object>}
 */
export async function runCode(payload) {
  if (!payload) {
    throw new Error('Payload is required.');
  }

  if (payload.language !== 'python') {
    throw new Error(`Unsupported language: '${payload.language}'. Only Python is supported.`);
  }

  const sourceCode = payload.source_code ?? '';
  const testCases = payload.test_cases || [];

  if (sourceCode.trim() === '') {
    return {
      status: 'error',
      language: 'python',
      stdout: '',
      stderr: 'Error: Source code cannot be empty.',
      exit_code: 1,
      execution_time_ms: 0,
      tests_passed: 0,
      tests_total: testCases.length,
      test_results: testCases.map((tc) => ({
        id: tc.id,
        passed: false,
        actual_output: '',
        expected_output: (tc.expected_output || '').trim(),
      })),
      simulation: false,
      error_message: 'Source code cannot be empty.',
    };
  }

  try {
    const response = await fetch(`${BACKEND_URL}/run`, {
      method: 'POST',
      headers: {
        'Content-Type': 'application/json',
      },
      body: JSON.stringify({
        language: 'python',
        source_code: sourceCode,
      }),
    });

    if (!response.ok) {
      let errorDetail = `Backend HTTP Error: ${response.status} ${response.statusText}`;
      try {
        const errorData = await response.json();
        if (errorData.detail) {
          if (Array.isArray(errorData.detail)) {
            errorDetail = errorData.detail.map((d) => d.msg || JSON.stringify(d)).join('; ');
          } else {
            errorDetail = String(errorData.detail);
          }
        }
      } catch {
        // Response was not JSON
      }

      return {
        status: 'error',
        language: 'python',
        stdout: '',
        stderr: errorDetail,
        exit_code: response.status,
        execution_time_ms: 0,
        tests_passed: 0,
        tests_total: testCases.length,
        test_results: testCases.map((tc) => ({
          id: tc.id,
          passed: false,
          actual_output: '',
          expected_output: (tc.expected_output || '').trim(),
          error: errorDetail,
        })),
        simulation: false,
        error_message: errorDetail,
      };
    }

    const data = await response.json();

    // Evaluate test cases against actual program stdout
    const testResults = evaluateTestCases(testCases, data.stdout || '');
    const testsPassed = testResults.filter((t) => t.passed).length;

    return {
      status: data.status,
      language: 'python',
      stdout: data.stdout || '',
      stderr: data.stderr || '',
      exit_code: typeof data.exit_code === 'number' ? data.exit_code : 0,
      execution_time_ms: data.execution_time_ms || 0,
      tests_passed: testsPassed,
      tests_total: testCases.length,
      test_results: testResults,
      simulation: false,
    };
  } catch (err) {
    const networkErrorMsg =
      err instanceof Error
        ? `Backend connection failed: ${err.message}. Ensure the FastAPI server is running at ${BACKEND_URL}.`
        : `Network error connecting to backend at ${BACKEND_URL}.`;

    return {
      status: 'error',
      language: 'python',
      stdout: '',
      stderr: networkErrorMsg,
      exit_code: -1,
      execution_time_ms: 0,
      tests_passed: 0,
      tests_total: testCases.length,
      test_results: testCases.map((tc) => ({
        id: tc.id,
        passed: false,
        actual_output: '',
        expected_output: (tc.expected_output || '').trim(),
        error: networkErrorMsg,
      })),
      simulation: false,
      error_message: networkErrorMsg,
    };
  }
}

/**
 * Placeholder for Genetic Algorithm optimization backend.
 * Currently disabled until backend optimization is implemented.
 */
export async function optimizeCode() {
  return Promise.resolve({
    status: 'error',
    language: 'python',
    original_stdout: '',
    optimized_stdout: '',
    original_tac: [],
    optimized_tac: [],
    original_execution_time_ms: 0,
    optimized_execution_time_ms: 0,
    time_improvement_percent: 0,
    original_instruction_count: 0,
    optimized_instruction_count: 0,
    code_size_reduction_percent: 0,
    tests_passed: 0,
    tests_total: 0,
    pass_sequence: [],
    generations: 0,
    population_size: 0,
    best_fitness: 0,
    simulation: false,
    error_message: 'Compiler optimization backend (Genetic Algorithm & TAC) is currently in development.',
  });
}
