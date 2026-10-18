import React, { useState } from 'react';
import { Layers, Binary } from 'lucide-react';
import type { OptimizeResponse } from '../types/compiler';

interface TACViewerProps {
  optimizeResult: OptimizeResponse | null;
  isStale: boolean;
}

export const TACViewer: React.FC<TACViewerProps> = ({
  optimizeResult,
  isStale,
}) => {
  const [activeTab, setActiveTab] = useState<'original' | 'optimized'>('optimized');

  if (!optimizeResult) {
    return (
      <div className="panel-card">
        <div className="panel-header">
          <div className="panel-title-area">
            <span className="panel-title">
              <Binary size={15} />
              Three-Address Code (TAC) Viewer
            </span>
          </div>
        </div>
        <div className="tac-empty-state">
          <Layers size={24} />
          <span className="tac-empty-title">Intermediate TAC Viewer (Backend Pending)</span>
          <span className="tac-empty-desc">
            Three-Address Code (TAC) generation will display here once the compiler intermediate representation pipeline is implemented.
          </span>
        </div>
      </div>
    );
  }

  const { original_tac = [], optimized_tac = [] } = optimizeResult;
  const currentInstructions =
    activeTab === 'original' ? original_tac : optimized_tac;

  return (
    <div className="panel-card">
      <div className="panel-header">
        <div className="panel-title-area">
          <span className="panel-title">
            <Binary size={15} />
            Three-Address Code (TAC)
          </span>
          {isStale && (
            <span className="panel-badge" style={{ color: 'var(--warning-color)' }}>
              Stale
            </span>
          )}
        </div>

        <div className="panel-actions">
          <div className="tac-tabs">
            <button
              type="button"
              className={`tac-tab-btn ${
                activeTab === 'original' ? 'active' : ''
              }`}
              onClick={() => setActiveTab('original')}
            >
              Original ({original_tac.length})
            </button>
            <button
              type="button"
              className={`tac-tab-btn ${
                activeTab === 'optimized' ? 'active' : ''
              }`}
              onClick={() => setActiveTab('optimized')}
            >
              Optimized ({optimized_tac.length})
            </button>
          </div>
        </div>
      </div>

      <div className="tac-code-area">
        {currentInstructions.length === 0 ? (
          <div className="tac-empty-desc">[Empty TAC Stream]</div>
        ) : (
          currentInstructions.map((instruction, index) => (
            <div key={index} className="tac-line">
              <span className="tac-line-number">{index + 1}</span>
              <span className="tac-instruction">{instruction}</span>
            </div>
          ))
        )}
      </div>
    </div>
  );
};

export default TACViewer;
