import React from 'react';
import { Terminal, Clock, AlertCircle, AlertTriangle, ShieldCheck, Hash } from 'lucide-react';
import type { RunResponse, OptimizeResponse } from '../types/compiler';

interface OutputConsoleProps {
  runResult: RunResponse | null;
  optimizeResult: OptimizeResponse | null;
  isStale: boolean;
  status: 'idle' | 'running' | 'optimizing';
  language?: 'python' | 'c';
}

export const OutputConsole: React.FC<OutputConsoleProps> = ({
  runResult,
  optimizeResult,
  isStale,
  status,
  language = 'python',
}) => {
  const hasResult = Boolean(runResult || optimizeResult);

  const activeResult = runResult
    ? {
        pId: runResult.p_id,
        message: runResult.message,
        status: runResult.status,
        stdout: runResult.stdout || runResult.output || '',
        stderr: runResult.stderr,
        exitCode: runResult.exit_code,
        executionTime: runResult.execution_time_ms,
        source: `FastAPI Backend (${(runResult.language || language).toUpperCase()})`,
        errorMessage: runResult.error_message,
        isTimeout: runResult.status === 'timeout' || runResult.status === 'compile_timeout',
      }
    : optimizeResult
    ? {
        pId: undefined,
        message: undefined,
        status: optimizeResult.status,
        stdout: optimizeResult.optimized_stdout || optimizeResult.original_stdout,
        stderr: optimizeResult.optimized_stderr || optimizeResult.error_message || '',
        exitCode: optimizeResult.optimized_exit_code ?? optimizeResult.original_exit_code ?? -1,
        executionTime: optimizeResult.optimized_execution_time_ms,
        source: 'Optimized Run',
        errorMessage: optimizeResult.error_message,
        isTimeout: false,
      }
    : null;

  const isSuccess =
    (activeResult?.status === 'completed' || activeResult?.status === 'success') &&
    activeResult.exitCode === 0 &&
    !activeResult.isTimeout;
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
                ? 'Completed'
                : 'Failed'}
            </span>
          )}
        </div>
      </div>

      <div className="console-body">
        {status === 'running' || status === 'optimizing' ? (
          <div className="console-output-box">
            <span className="console-empty-text">
              {status === 'running'
                ? `Sending ${language === 'c' ? 'C' : 'Python'} code to FastAPI backend (/execute) and running...`
                : 'Processing request...'}
            </span>
          </div>
        ) : !activeResult ? (
          <div className="console-output-box">
            <span className="console-empty-text">
              Press <strong>Run Code</strong> to execute your {language === 'c' ? 'C' : 'Python'} program on the backend and view actual output.
            </span>
          </div>
        ) : (
          <>
            <div className="console-meta-bar">
              <div style={{ display: 'flex', alignItems: 'center', gap: 12, flexWrap: 'wrap' }}>
                <span className="meta-timing">
                  <Clock size={12} style={{ display: 'inline', marginRight: 4, verticalAlign: -1 }} />
                  Duration: {activeResult.executionTime} ms
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

                {activeResult.pId && (
                  <span className="meta-timing" title={`Job UUID: ${activeResult.pId}`}>
                    <Hash size={11} style={{ display: 'inline', marginRight: 2, verticalAlign: -1 }} />
                    Job ID: <code style={{ fontSize: '11px', padding: '1px 5px', background: 'var(--bg-subtle)' }}>{activeResult.pId.slice(0, 8)}...</code>
                  </span>
                )}
              </div>
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
                <span>Execution was terminated because it exceeded the timeout limit.</span>
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
