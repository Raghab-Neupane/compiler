import React, { useState, useCallback } from 'react';
import Header from './components/Header';
import ActionBar from './components/ActionBar';
import CodeEditor from './components/CodeEditor';
import TestCases from './components/TestCases';
import OutputConsole from './components/OutputConsole';
import OptimizationMetrics from './components/OptimizationMetrics';
import TACViewer from './components/TACViewer';
import GADetails from './components/GADetails';
import { runCode, optimizeCode } from './services/compilerApi';
import type { TestCase, RunResponse, OptimizeResponse } from './types/compiler';
import './App.css';

const DEFAULT_PYTHON_CODE = `def calculate():
    x = 10
    y = 20
    z = x + y
    result = z * 2
    print(result)

calculate()`;

const INITIAL_TEST_CASES: TestCase[] = [
  {
    id: 'test-1',
    input: '',
    expected_output: '60',
  },
];

export const App: React.FC = () => {
  const [code, setCode] = useState<string>(DEFAULT_PYTHON_CODE);
  const [testCases, setTestCases] = useState<TestCase[]>(INITIAL_TEST_CASES);
  const [runResult, setRunResult] = useState<RunResponse | null>(null);
  const [optimizeResult, setOptimizeResult] = useState<OptimizeResponse | null>(null);
  const [isStale, setIsStale] = useState<boolean>(false);
  const [status, setStatus] = useState<'idle' | 'running' | 'optimizing'>('idle');
  const [feedback, setFeedback] = useState<{
    type: 'success' | 'error' | 'info';
    message: string;
  } | null>(null);

  // Invalidate previous results when code changes
  const handleCodeChange = useCallback((newCode: string) => {
    setCode(newCode);
    if (runResult || optimizeResult) {
      setIsStale(true);
    }
  }, [runResult, optimizeResult]);

  // Invalidate previous results when test cases change
  const handleTestCasesChange = useCallback((updatedCases: TestCase[]) => {
    setTestCases(updatedCases);
    if (runResult || optimizeResult) {
      setIsStale(true);
    }
  }, [runResult, optimizeResult]);

  // Execute Code
  const handleRunCode = async () => {
    if (status !== 'idle') return;

    setStatus('running');
    setFeedback(null);

    try {
      const response = await runCode({
        language: 'python',
        source_code: code,
        test_cases: testCases,
      });

      setRunResult(response as RunResponse);
      setIsStale(false);

      if (response.status === 'success' && !response.stderr) {
        setFeedback({
          type: 'success',
          message: `Execution completed in ${response.execution_time_ms.toFixed(1)} ms.`,
        });
      } else if (response.status === 'timeout') {
        setFeedback({
          type: 'error',
          message: 'Execution timed out after 5.0 seconds.',
        });
      } else {
        setFeedback({
          type: 'error',
          message: response.stderr || response.error_message || 'Execution error.',
        });
      }
    } catch (err: unknown) {
      const msg = err instanceof Error ? err.message : 'Unknown execution error occurred.';
      setRunResult({
        status: 'error',
        language: 'python',
        stdout: '',
        stderr: msg,
        exit_code: -1,
        execution_time_ms: 0,
        tests_passed: 0,
        tests_total: testCases.length,
        test_results: [],
        simulation: false,
        error_message: msg,
      });
      setFeedback({ type: 'error', message: msg });
    } finally {
      setStatus('idle');
    }
  };

  // Optimize Code
  const handleOptimizeCode = async () => {
    if (status !== 'idle') return;

    setStatus('optimizing');
    setFeedback(null);

    try {
      const response = await optimizeCode({
        language: 'python',
        source_code: code,
        test_cases: testCases,
      });

      setOptimizeResult(response as OptimizeResponse);
      setIsStale(false);

      if (response.status === 'success') {
        setFeedback({
          type: 'success',
          message: `Optimized: ${response.code_size_reduction_percent}% size reduction (${response.pass_sequence.length} passes).`,
        });
      } else {
        setFeedback({
          type: 'error',
          message: response.error_message || 'Optimization failed.',
        });
      }
    } catch (err: unknown) {
      const msg = err instanceof Error ? err.message : 'Unknown optimization error occurred.';
      setOptimizeResult({
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
        tests_total: testCases.length,
        pass_sequence: [],
        generations: 0,
        population_size: 0,
        best_fitness: 0,
        simulation: true,
        error_message: msg,
      });
      setFeedback({ type: 'error', message: msg });
    } finally {
      setStatus('idle');
    }
  };

  // Reset Everything to Default State
  const handleReset = () => {
    setCode(DEFAULT_PYTHON_CODE);
    setTestCases(INITIAL_TEST_CASES);
    setRunResult(null);
    setOptimizeResult(null);
    setIsStale(false);
    setFeedback({
      type: 'info',
      message: 'Restored default code and cleared results.',
    });
  };

  return (
    <div className="app-container">
      {/* Top Header */}
      <Header status={status} />

      {/* Action Bar */}
      <ActionBar
        onRun={handleRunCode}
        onOptimize={handleOptimizeCode}
        onReset={handleReset}
        status={status}
        isStale={isStale}
        feedback={feedback}
      />

      {/* Main Workspace Layout */}
      <main className="workspace-grid">
        {/* Left Column: Code Editor, Test Cases, Output Console */}
        <section className="workspace-column">
          <CodeEditor
            code={code}
            onChange={handleCodeChange}
            disabled={status !== 'idle'}
          />

          <TestCases
            testCases={testCases}
            onChange={handleTestCasesChange}
            disabled={status !== 'idle'}
          />

          <OutputConsole
            runResult={runResult}
            optimizeResult={optimizeResult}
            isStale={isStale}
            status={status}
          />
        </section>

        {/* Right Column: Optimization Results & GA Details */}
        <section className="workspace-column">
          <OptimizationMetrics
            optimizeResult={optimizeResult}
            isStale={isStale}
          />

          <TACViewer
            optimizeResult={optimizeResult}
            isStale={isStale}
          />

          <GADetails
            optimizeResult={optimizeResult}
            isStale={isStale}
          />
        </section>
      </main>
    </div>
  );
};

export default App;
