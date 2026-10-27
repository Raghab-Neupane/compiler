import React from 'react';
import { Play, Sparkles, RotateCcw, AlertTriangle, CheckCircle2, XCircle, Loader2, Terminal } from 'lucide-react';

interface ActionBarProps {
  onRun: () => void;
  onOptimize: () => void;
  onReset: () => void;
  status: 'idle' | 'running' | 'optimizing';
  isStale: boolean;
  language: 'python' | 'c';
  canOptimize: boolean;
  onLanguageChange: (lang: 'python' | 'c') => void;
  feedback?: {
    type: 'success' | 'error' | 'info';
    message: string;
  } | null;
}

export const ActionBar: React.FC<ActionBarProps> = ({
  onRun,
  onOptimize,
  onReset,
  status,
  isStale,
  language,
  canOptimize,
  onLanguageChange,
  feedback,
}) => {
  const isBusy = status !== 'idle';

  return (
    <div className="action-bar-container">
      <div className="action-buttons-group">
        {/* Language Dropdown Selector */}
        <div className="language-selector-wrapper" title="Select target programming language">
          <Terminal size={13} className="language-icon" />
          <select
            id="language-dropdown"
            className="language-select"
            value={language}
            onChange={(e) => onLanguageChange(e.target.value as 'python' | 'c')}
            disabled={isBusy}
            aria-label="Target language"
          >
            <option value="python">Python 3</option>
            <option value="c">C (Clang)</option>
          </select>
        </div>

        <button
          type="button"
          className="btn-base btn-run"
          onClick={onRun}
          disabled={isBusy}
          title={`Send ${language === 'c' ? 'C' : 'Python'} source code to FastAPI backend for execution`}
        >
          {status === 'running' ? (
            <>
              <Loader2 size={14} className="status-dot processing" style={{ animation: 'spin 1s linear infinite' }} />
              Running on Backend...
            </>
          ) : (
            <>
              <Play size={14} fill="currentColor" />
              Run Code
            </>
          )}
        </button>

        <button
          type="button"
          className="btn-base btn-optimize"
            onClick={onOptimize}
            disabled={isBusy || !canOptimize}
            title={canOptimize ? 'Run the LLVM IR genetic optimizer on the latest C compilation' : 'Run the current C source successfully before optimizing'}
        >
          <Sparkles size={14} />
            {status === 'optimizing' ? 'Optimizing...' : 'Optimize Code'}
        </button>

        <button
          type="button"
          className="btn-base btn-reset"
          onClick={onReset}
          disabled={isBusy}
          title={`Reset editor to default ${language === 'c' ? 'C' : 'Python'} code and clear results`}
        >
          <RotateCcw size={13} />
          Reset
        </button>
      </div>

      <div className="action-bar-feedback">
        {isStale && !isBusy && (
          <div className="feedback-stale" title="Source code or language was modified since the last execution.">
            <AlertTriangle size={13} />
            <span>Code changed (previous execution stale)</span>
          </div>
        )}

        {feedback && !isStale && !isBusy && (
          <div className={`feedback-${feedback.type}`}>
            {feedback.type === 'success' && <CheckCircle2 size={13} />}
            {feedback.type === 'error' && <XCircle size={13} />}
            <span>{feedback.message}</span>
          </div>
        )}
      </div>
    </div>
  );
};

export default ActionBar;
