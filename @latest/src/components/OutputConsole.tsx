import React from 'react';
import { Terminal, Check, X, Clock, AlertCircle, AlertTriangle, ShieldCheck } from 'lucide-react';
import type { RunResponse, OptimizeResponse } from '../types/compiler';

interface OutputConsoleProps {
  runResult: RunResponse | null;
  optimizeResult: OptimizeResponse | null;
  isStale: boolean;
  status: 'idle' | 'running' | 'optimizing';
}

export const OutputConsole: React.FC<OutputConsoleProps> = ({
  runResult,
  optimizeResult,
  isStale,
  status,
}) => {
  const hasResult = Boolean(runResult || optimizeResult);

  const activeResult = runResult
    ? {
        status: runResult.status,
        stdout: runResult.stdout,
        stderr: runResult.stderr,
        exitCode: runResult.exit_code,
        executionTime: runResult.execution_time_ms,
        testsPassed: runResult.tests_passed,
        testsTotal: runResult.tests_total,
        testResults: runResult.test_results || [],
        source: 'Python Backend Execution',
        errorMessage: runResult.error_message,
        isTimeout: runResult.status === 'timeout',
      }
    : optimizeResult
    ? {
        status: optimizeResult.status,
        stdout: optimizeResult.optimized_stdout || optimizeResult.original_stdout,
        stderr: optimizeResult.error_message ? optimizeResult.error_message : '',
        exitCode: 0,
        executionTime: optimizeResult.optimized_execution_time_ms,
        testsPassed: optimizeResult.tests_passed,
        testsTotal: optimizeResult.tests_total,
        testResults: optimizeResult.test_results || [],
        source: 'Optimized Run',
        errorMessage: optimizeResult.error_message,
        isTimeout: false,
      }
    : null;

  const isSuccess = activeResult?.status === 'success' && activeResult.exitCode === 0;
  const isTimeout = activeResult?.isTimeout;
  const hasError = !isSuccess;

  return (
    <div className="panel-card">
      <div className="panel-header">
        <div className="panel-title-area">
          <span className="panel-title">
            <Terminal size={15} />
            Output Console
          </span>
          {activeResult && (
            <span className="panel-badge" style={{ display: 'inline-flex', alignItems: 'center', gap: 4 }}>
              <ShieldCheck size={11} color="var(--primary-color)" />
              {activeResult.source}
            </span>
          )}
          {isStale && hasResult && (
            <span className="panel-badge" style={{ color: 'var(--warning-color)' }}>
              Stale
            </span>
          )}
        </div>

        <div className="panel-actions">
          {activeResult && (
            <span
              className={`meta-status-pill ${
                isStale
                  ? 'stale'
                  : isTimeout
                  ? 'error'
                  : isSuccess
                  ? 'success'
                  : 'error'
              }`}
            >
              {isStale
                ? 'Stale Output'
                : isTimeout
                ? 'Timed Out'
                : isSuccess
                ? 'Success'
                : 'Execution Error'}
            </span>
          )}
        </div>
      </div>

      <div className="console-body">
        {status === 'running' || status === 'optimizing' ? (
          <div className="console-output-box">
            <span className="console-empty-text">
              {status === 'running'
                ? 'Sending source code to FastAPI backend and executing with Python 3...'
                : 'Processing request...'}
            </span>
          </div>
        ) : !activeResult ? (
          <div className="console-output-box">
            <span className="console-empty-text">
              Press <strong>Run Code</strong> to execute your Python program on the backend and view actual stdout.
            </span>
          </div>
        ) : (
          <>
            <div className="console-meta-bar">
              <div style={{ display: 'flex', alignItems: 'center', gap: 12 }}>
                <span className="meta-timing">
                  <Clock size={12} style={{ display: 'inline', marginRight: 4, verticalAlign: -1 }} />
                  Duration: {activeResult.executionTime.toFixed(2)} ms
                </span>

                <span
                  className="meta-timing"
                  style={{
                    fontWeight: 600,
                    color: activeResult.exitCode === 0 ? 'var(--success-color)' : 'var(--danger-color)',
                  }}
                >
                  Exit code: {activeResult.exitCode}
                </span>
              </div>

              {activeResult.testsTotal > 0 && (
                <span className="meta-timing">
                  Tests: {activeResult.testsPassed} / {activeResult.testsTotal} passed
                </span>
              )}
            </div>

            {/* Standard Output and Error Box */}
            <div className={`console-output-box ${hasError ? 'has-error' : ''}`}>
              {activeResult.stdout ? (
                <div>{activeResult.stdout}</div>
              ) : !activeResult.stderr ? (
                <span className="console-empty-text">[No stdout produced]</span>
              ) : null}

              {activeResult.stderr && (
                <div style={{ marginTop: activeResult.stdout ? 8 : 0 }}>
                  <div style={{ fontWeight: 600, color: 'var(--danger-color)', marginBottom: 2 }}>
                    Standard Error (stderr):
                  </div>
                  <pre style={{ margin: 0, fontFamily: 'inherit', whiteSpace: 'pre-wrap' }}>
                    {activeResult.stderr}
                  </pre>
                </div>
              )}
            </div>

            {/* Timeout Banner */}
            {isTimeout && (
              <div className="feedback-error">
                <AlertTriangle size={13} />
                <span>Execution was terminated because it exceeded the 5.0 second timeout limit.</span>
              </div>
            )}

            {/* Test Results Breakdown */}
            {activeResult.testResults && activeResult.testResults.length > 0 && (
              <div className="console-tests-area">
                <span className="console-tests-title">Test Results Breakdown</span>
                {activeResult.testResults.map((tr, idx) => (
                  <div
                    key={tr.id || idx}
                    className={`test-result-row ${tr.passed ? 'passed' : 'failed'}`}
                  >
                    <div className="test-result-info">
                      {tr.passed ? (
                        <Check size={14} color="var(--success-color)" />
                      ) : (
                        <X size={14} color="var(--danger-color)" />
                      )}
                      <span>Test Case #{idx + 1}</span>
                      <span
                        className={`test-result-badge ${
                          tr.passed ? 'passed' : 'failed'
                        }`}
                      >
                        {tr.passed ? 'PASS' : 'FAIL'}
                      </span>
                    </div>

                    <div className="test-result-outputs">
                      <span title="Expected output">
                        Expected: {JSON.stringify(tr.expected_output)}
                      </span>
                      <span>|</span>
                      <span title="Actual output">
                        Actual: {JSON.stringify(tr.actual_output)}
                      </span>
                    </div>
                  </div>
                ))}
              </div>
            )}

            {activeResult.errorMessage && !activeResult.stderr && (
              <div className="feedback-error">
                <AlertCircle size={13} />
                <span>{activeResult.errorMessage}</span>
              </div>
            )}
          </>
        )}
      </div>
    </div>
  );
};

export default OutputConsole;
