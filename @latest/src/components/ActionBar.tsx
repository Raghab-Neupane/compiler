import React from 'react';
import { Play, Sparkles, RotateCcw, AlertTriangle, CheckCircle2, XCircle, Loader2 } from 'lucide-react';

interface ActionBarProps {
  onRun: () => void;
  onOptimize: () => void;
  onReset: () => void;
  status: 'idle' | 'running' | 'optimizing';
  isStale: boolean;
  feedback?: {
    type: 'success' | 'error' | 'info';
    message: string;
  } | null;
}

export const ActionBar: React.FC<ActionBarProps> = ({
  onRun,
  onReset,
  status,
  isStale,
  feedback,
}) => {
  const isBusy = status !== 'idle';

  return (
    <div className="action-bar-container">
      <div className="action-buttons-group">
        <button
          type="button"
          className="btn-base btn-run"
          onClick={onRun}
          disabled={isBusy}
          title="Send Python source code to FastAPI backend for execution"
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
          disabled={true}
          style={{ opacity: 0.6, cursor: 'not-allowed', backgroundColor: '#e2e8f0', color: '#64748b' }}
          title="Optimization backend (Genetic Algorithm & Intermediate TAC) is currently in development."
        >
          <Sparkles size={14} />
          Optimize Code (Backend Pending)
        </button>

        <button
          type="button"
          className="btn-base btn-reset"
          onClick={onReset}
          disabled={isBusy}
          title="Reset editor to default code and clear results"
        >
          <RotateCcw size={13} />
          Reset
        </button>
      </div>

      <div className="action-bar-feedback">
        {isStale && !isBusy && (
          <div className="feedback-stale" title="Source code or test cases were modified since the last execution.">
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
