import React from 'react';
import { Dna, ArrowRight, Activity, AlertCircle } from 'lucide-react';
import type { OptimizeResponse } from '../types/compiler';

interface GADetailsProps {
  optimizeResult: OptimizeResponse | null;
  isStale: boolean;
}

export const GADetails: React.FC<GADetailsProps> = ({
  optimizeResult,
  isStale,
}) => {
  if (!optimizeResult) {
    return (
      <div className="panel-card">
        <div className="panel-header">
          <div className="panel-title-area">
            <span className="panel-title">
              <Dna size={15} />
              Genetic Algorithm Details
            </span>
          </div>
        </div>
        <div className="tac-empty-state">
          <Activity size={24} />
          <span className="tac-empty-title">GA Optimizer (Backend Pending)</span>
          <span className="tac-empty-desc">
            Pass sequencing, population evolution, generations, and fitness metrics will display once the Genetic Algorithm optimization backend is connected.
          </span>
        </div>
      </div>
    );
  }

  const {
    pass_sequence = [],
    generations = 0,
    population_size = 0,
    best_fitness = 0,
    status,
  } = optimizeResult;

  return (
    <div className="panel-card">
      <div className="panel-header">
        <div className="panel-title-area">
          <span className="panel-title">
            <Dna size={15} />
            Genetic Algorithm Details
          </span>
          <span className="panel-badge simulated">Simulated GA Evolution</span>
          {isStale && (
            <span className="panel-badge" style={{ color: 'var(--warning-color)' }}>
              Stale
            </span>
          )}
        </div>
        <div className="panel-actions">
          <span
            className={`meta-status-pill ${
              status === 'success' ? 'success' : 'error'
            }`}
          >
            {status === 'success' ? 'Converged' : 'Failed'}
          </span>
        </div>
      </div>

      <div className="ga-body">
        {/* GA Parameters */}
        <div className="ga-params-grid">
          <div className="ga-param-box">
            <div className="ga-param-label">Generations</div>
            <div className="ga-param-val">{generations}</div>
          </div>
          <div className="ga-param-box">
            <div className="ga-param-label">Population Size</div>
            <div className="ga-param-val">{population_size}</div>
          </div>
          <div className="ga-param-box">
            <div className="ga-param-label">Best Fitness</div>
            <div className="ga-param-val">{best_fitness.toFixed(2)}</div>
          </div>
        </div>

        {/* Pass Sequence */}
        <div className="ga-sequence-area">
          <span className="ga-sequence-title">Best Optimization Pass Sequence</span>
          {pass_sequence.length === 0 ? (
            <span className="tac-empty-desc">No passes selected</span>
          ) : (
            <div className="ga-passes-list">
              {pass_sequence.map((passName, index) => (
                <React.Fragment key={index}>
                  <div className="ga-pass-badge">
                    <span>{index + 1}.</span>
                    <span>{passName}</span>
                  </div>
                  {index < pass_sequence.length - 1 && (
                    <ArrowRight className="ga-pass-arrow" size={12} />
                  )}
                </React.Fragment>
              ))}
            </div>
          )}
        </div>

        {/* Disclaimer */}
        <div className="ga-disclaimer">
          <AlertCircle size={13} style={{ flexShrink: 0 }} />
          <span>
            Simulated results: These represent expected heuristics from a Genetic Algorithm pass selector and are not from a live backend compiler.
          </span>
        </div>
      </div>
    </div>
  );
};

export default GADetails;
