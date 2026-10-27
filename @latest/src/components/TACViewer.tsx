import React, { useEffect, useState } from 'react';
import { Layers, Binary } from 'lucide-react';
import { getTac } from '../services/compilerApi';
import type {
  OptimizeResponse,
  TacInstruction,
  TacResponse,
} from '../types/compiler';

interface TACViewerProps {
  pId?: string;
  language: 'python' | 'c';
  optimizeResult: OptimizeResponse | null;
  isStale: boolean;
}

interface TacLoadState {
  pId: string;
  result: TacResponse;
  error?: string;
}

function toLines(value: string | TacInstruction[] | null | undefined): TacInstruction[] {
  if (typeof value === 'string') {
    const lines = value.replace(/\r\n/g, '\n').split('\n');
    if (lines[lines.length - 1] === '') {
      lines.pop();
    }
    return lines.map((instruction, index) => ({
      source_line: index + 1,
      instruction,
    }));
  }
  return value ?? [];
}

export const TACViewer: React.FC<TACViewerProps> = ({
  pId,
  language,
  optimizeResult,
  isStale,
}) => {
  const [tacLoad, setTacLoad] = useState<TacLoadState | null>(null);

  useEffect(() => {
    let isCurrent = true;

    if (!pId) {
      return;
    }

    getTac(pId)
      .then((response) => {
        if (isCurrent) {
          setTacLoad({ pId, result: response });
        }
      })
      .catch((requestError: unknown) => {
        if (isCurrent) {
          setTacLoad({
            pId,
            result: {
              p_id: pId,
              language,
              source_code: '',
              original_tac: '',
              optimized_tac: null,
              optimized_code: '',
              optimized_stdout: null,
              optimized_exit_code: null,
              optimized_execution_time_ms: null,
              fitness_score: null,
              equivalent: null,
              optimization_status: 'error',
            },
            error:
              requestError instanceof Error
                ? requestError.message
                : 'Unable to load TAC.',
          });
        }
      });

    return () => {
      isCurrent = false;
    };
  }, [pId, language]);

  const currentTacLoad = tacLoad?.pId === pId ? tacLoad : null;
  const savedResult = currentTacLoad?.result;
  const isLoading = Boolean(pId && !currentTacLoad);
  const error = currentTacLoad?.error ?? null;
  const showOptimization =
    optimizeResult !== null && optimizeResult.p_id === pId;
  if (!pId && !optimizeResult) {
    return (
      <div className="panel-card">
        <div className="panel-header">
          <div className="panel-title-area">
            <span className="panel-title">
              <Binary size={15} />
              {language === 'c' ? 'Three-Address Code (TAC) Viewer' : 'Python TAC Viewer'}
            </span>
          </div>
        </div>
        <div className="tac-empty-state">
          <Layers size={24} />
          <span className="tac-empty-title">No compilation job selected</span>
          <span className="tac-empty-desc">
            Run code to generate and view its saved TAC instructions.
          </span>
        </div>
      </div>
    );
  }

  const originalTac = toLines(
    showOptimization ? optimizeResult.original_tac : savedResult?.original_tac,
  );
  const title = language === 'c' ? 'Three-Address Code (TAC) Viewer' : 'Python TAC Viewer';

  return (
    <div className="panel-card">
      <div className="panel-header">
        <div className="panel-title-area">
          <span className="panel-title">
            <Binary size={15} />
            {title}
          </span>
          {isStale && (
            <span className="panel-badge" style={{ color: 'var(--warning-color)' }}>
              Stale
            </span>
          )}
        </div>

      </div>

      <div className="tac-single-pane" aria-live="polite">
        <div className="tac-comparison-pane">
          <div className="tac-comparison-title">
            Original TAC
            <span>{originalTac.length} instructions</span>
          </div>
          <TacCodeArea
            instructions={originalTac}
            isLoading={isLoading}
            error={error}
            loadingLabel="Loading original TAC..."
            emptyLabel="No original TAC is available for this job."
          />
        </div>
      </div>
    </div>
  );
};

interface TacCodeAreaProps {
  instructions: TacInstruction[];
  isLoading: boolean;
  error: string | null;
  loadingLabel: string;
  emptyLabel: string;
}

const TacCodeArea: React.FC<TacCodeAreaProps> = ({
  instructions,
  isLoading,
  error,
  loadingLabel,
  emptyLabel,
}) => (
  <div className="tac-code-area">
    {isLoading ? (
      <div className="tac-empty-desc">{loadingLabel}</div>
    ) : error ? (
      <div className="tac-empty-desc" role="alert">{error}</div>
    ) : instructions.length === 0 ? (
      <div className="tac-empty-desc">{emptyLabel}</div>
    ) : (
      instructions.map((instruction, index) => (
        <div key={`${instruction.source_line}-${index}`} className="tac-line">
          <span className="tac-line-number">{index + 1}</span>
          <span className="tac-source-line">L{instruction.source_line}</span>
          <span className="tac-instruction">{instruction.instruction}</span>
        </div>
      ))
    )}
  </div>
);

export default TACViewer;
