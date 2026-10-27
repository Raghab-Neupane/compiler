import React, { useState, useCallback } from 'react';
import Header from './components/Header';
import ActionBar from './components/ActionBar';
import CodeEditor from './components/CodeEditor';
import OutputConsole from './components/OutputConsole';
import OptimizationMetrics from './components/OptimizationMetrics';
import TACViewer from './components/TACViewer';
import GADetails from './components/GADetails';
import GAConfigPanel, { type GAConfiguration } from './components/GAConfigPanel';
import { runCode, optimizeCode } from './services/compilerApi';
import type { RunResponse, OptimizeResponse } from './types/compiler';
import './App.css';

const DEFAULT_PYTHON_CODE = `def calculate():
    x = 10
    y = 20
    z = x + y
    result = z * 2
    print(result)

calculate()`;

const DEFAULT_C_CODE = `#include <stdio.h>

int main() {
    int x = 10;
    int y = 20;
    int z = x + y;
    int result = z * 2;
    printf("%d\\n", result);
    return 0;
}
`;

export const App: React.FC = () => {
  const [language, setLanguage] = useState<'python' | 'c'>('python');
  const [codeByLanguage, setCodeByLanguage] = useState<Record<'python' | 'c', string>>({
    python: DEFAULT_PYTHON_CODE,
    c: DEFAULT_C_CODE,
  });
  const [runResult, setRunResult] = useState<RunResponse | null>(null);
  const [optimizeResult, setOptimizeResult] = useState<OptimizeResponse | null>(null);
  const [isStale, setIsStale] = useState<boolean>(false);
  const [status, setStatus] = useState<'idle' | 'running' | 'optimizing'>('idle');
  const [feedback, setFeedback] = useState<{
    type: 'success' | 'error' | 'info';
    message: string;
  } | null>(null);
  const [gaConfiguration, setGaConfiguration] = useState<GAConfiguration>({
    population_size: 8,
    generations: 5,
    max_chromosome_length: 5,
    mutation_probability: 0.35,
    benchmark_runs: 3,
    random_seed: 0,
    objective: 'execution_time',
    tournament_size: 3,
  });

  const currentCode = codeByLanguage[language];
  const canOptimizeRun =
    language === 'c'
    && !isStale
    && Boolean(runResult?.p_id)
    && ![
      'compile_failed',
      'compiler_unavailable',
      'compile_timeout',
      'timeout',
      'error',
    ].includes(runResult?.status ?? '');

  // Invalidate previous results when code changes
  const handleCodeChange = useCallback((newCode: string) => {
    setCodeByLanguage((prev) => ({
      ...prev,
      [language]: newCode,
    }));
    if (runResult || optimizeResult) {
      setIsStale(true);
    }
  }, [language, runResult, optimizeResult]);

  // Handle switching between Python and C
  const handleLanguageChange = useCallback((newLang: 'python' | 'c') => {
    setLanguage(newLang);
    if (runResult || optimizeResult) {
      setIsStale(true);
    }
    setFeedback(null);
  }, [runResult, optimizeResult]);

  // Execute Code
  const handleRunCode = async () => {
    if (status !== 'idle') return;

    setStatus('running');
    setFeedback(null);
    setOptimizeResult(null);

    try {
      const response = await runCode({
        language: language,
        source_code: currentCode,
      });

      setRunResult(response as RunResponse);
      setIsStale(false);

      const isSuccess =
        (response.status === 'completed' || response.status === 'success') &&
        response.exit_code === 0 &&
        !response.stderr;

      if (isSuccess) {
        setFeedback({
          type: 'success',
          message: response.message || `Execution completed in ${response.execution_time_ms} ms.`,
        });
      } else if (response.status === 'timeout' || response.status === 'compile_timeout') {
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
        p_id: '',
        message: msg,
        status: 'failed',
        language: language,
        stdout: '',
        stderr: msg,
        exit_code: -1,
        execution_time_ms: 0,
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
    if (
      language !== 'c'
      || !runResult?.p_id
      || !canOptimizeRun
      || isStale
    ) {
      setFeedback({
        type: 'error',
        message: 'Run the current C source successfully before optimizing.',
      });
      return;
    }

    setStatus('optimizing');
    setFeedback(null);
    // Do not leave the previous run visible while a new API response is pending.
    setOptimizeResult(null);

    try {
      const response = await optimizeCode(runResult.p_id, gaConfiguration);

      setOptimizeResult(response as OptimizeResponse);
      setIsStale(false);

      if (response.status === 'success' && response.equivalent === true) {
        setFeedback({
          type: 'success',
          message: `Best LLVM pass sequence verified across ${response.tests_passed ?? 0} execution runs.`,
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
        optimization_status: 'error',
        p_id: runResult?.p_id || '',
        language: language,
        original_code: currentCode,
        optimized_code: '',
        original_stdout: '',
        optimized_stdout: '',
        original_tac: '',
        optimized_tac: '',
        original_execution_time_ms: null,
        optimized_execution_time_ms: null,
        time_improvement_percent: null,
        original_instruction_count: null,
        optimized_instruction_count: null,
        code_size_reduction_percent: null,
        pass_sequence: [],
        generations: 0,
        population_size: 0,
        best_fitness: null,
        simulation: false,
        equivalent: null,
        original_exit_code: null,
        optimized_exit_code: null,
        error_message: msg,
      });
      setFeedback({ type: 'error', message: msg });
    } finally {
      setStatus('idle');
    }
  };

  // Reset Everything to Default State for current language
  const handleReset = () => {
    setCodeByLanguage((prev) => ({
      ...prev,
      [language]: language === 'c' ? DEFAULT_C_CODE : DEFAULT_PYTHON_CODE,
    }));
    setRunResult(null);
    setOptimizeResult(null);
    setIsStale(false);
    setFeedback({
      type: 'info',
      message: `Restored default ${language === 'c' ? 'C' : 'Python'} code and cleared results.`,
    });
  };

  return (
    <div className="app-container">
      {/* Top Header */}
      <Header status={status} language={language} />

      {/* Action Bar */}
      <ActionBar
        onRun={handleRunCode}
        onOptimize={handleOptimizeCode}
        onReset={handleReset}
        status={status}
        isStale={isStale}
        language={language}
        canOptimize={
          canOptimizeRun
        }
        onLanguageChange={handleLanguageChange}
        feedback={feedback}
      />

      {/* Main Workspace Layout */}
      <main className="workspace-grid">
        {/* Left Column: Code Editor, Output Console */}
        <section className="workspace-column">
          <CodeEditor
            code={currentCode}
            onChange={handleCodeChange}
            disabled={status !== 'idle'}
            language={language}
          />

          <OutputConsole
            runResult={runResult}
            optimizeResult={optimizeResult}
            isStale={isStale}
            status={status}
            language={language}
          />
        </section>

        {/* Right Column: Optimization Results & GA Details */}
        <section className="workspace-column">
          <GAConfigPanel
            configuration={gaConfiguration}
            disabled={status !== 'idle'}
            onChange={setGaConfiguration}
          />
          <OptimizationMetrics
            optimizeResult={optimizeResult}
            isStale={isStale}
          />
          <GADetails
            optimizeResult={optimizeResult}
            isStale={isStale}
            status={status}
          />
        </section>
      </main>

    </div>
  );
};

export default App;
