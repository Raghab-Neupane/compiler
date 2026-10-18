import React from 'react';
import { BarChart3, TrendingDown, Clock, Code, CheckCircle, Info } from 'lucide-react';
import type { OptimizeResponse } from '../types/compiler';

interface OptimizationMetricsProps {
  optimizeResult: OptimizeResponse | null;
  isStale: boolean;
}

export const OptimizationMetrics: React.FC<OptimizationMetricsProps> = ({
  optimizeResult,
  isStale,
}) => {
  if (!optimizeResult) {
    return (
      <div className="panel-card">
        <div className="panel-header">
          <div className="panel-title-area">
            <span className="panel-title">
              <BarChart3 size={15} />
              Optimization Metrics
            </span>
          </div>
        </div>
        <div className="tac-empty-state">
          <Clock size={24} />
          <span className="tac-empty-title">Optimization Backend Pending</span>
          <span className="tac-empty-desc">
            Comparative benchmarks and execution speedups will display here once the Genetic Algorithm optimization backend is implemented.
          </span>
        </div>
      </div>
    );
  }

  const {
    original_execution_time_ms,
    optimized_execution_time_ms,
    time_improvement_percent,
    original_instruction_count,
    optimized_instruction_count,
    code_size_reduction_percent,
    tests_passed,
    tests_total,
    simulation,
  } = optimizeResult;

  const isTimeImproved = time_improvement_percent > 0;
  const isSizeReduced = code_size_reduction_percent > 0;

  return (
    <div className="panel-card">
      <div className="panel-header">
        <div className="panel-title-area">
          <span className="panel-title">
            <BarChart3 size={15} />
            Optimization Metrics
          </span>
          {simulation && (
            <span className="panel-badge simulated" title="These benchmark values are simulated by the mock compiler">
              Simulated result
            </span>
          )}
          {isStale && (
            <span className="panel-badge" style={{ color: 'var(--warning-color)' }}>
              Stale
            </span>
          )}
        </div>
      </div>

      <div className="metrics-body">
        <div className="metrics-grid">
          {/* Execution Time Comparison */}
          <div className="metric-card">
            <span className="metric-label">Execution Time</span>
            <div className="metric-value">
              {optimized_execution_time_ms.toFixed(1)}
              <span className="metric-unit">ms</span>
            </div>
            <div
              className={`metric-diff ${
                isTimeImproved ? 'positive' : 'neutral'
              }`}
            >
              <TrendingDown size={12} />
              <span>
                {isTimeImproved ? `${time_improvement_percent.toFixed(1)}% faster` : 'No speedup'}
              </span>
            </div>
            <span className="metric-subinfo">
              Original: {original_execution_time_ms.toFixed(1)} ms
            </span>
          </div>

          {/* TAC Instructions Count */}
          <div className="metric-card">
            <span className="metric-label">TAC Instructions</span>
            <div className="metric-value">
              {optimized_instruction_count}
              <span className="metric-unit">ops</span>
            </div>
            <div
              className={`metric-diff ${
                isSizeReduced ? 'positive' : 'neutral'
              }`}
            >
              <Code size={12} />
              <span>
                {isSizeReduced ? `${code_size_reduction_percent.toFixed(1)}% reduction` : '0% change'}
              </span>
            </div>
            <span className="metric-subinfo">
              Original: {original_instruction_count} ops
            </span>
          </div>

          {/* Test Verification */}
          <div className="metric-card">
            <span className="metric-label">Verification</span>
            <div className="metric-value">
              {tests_passed} / {tests_total}
              <span className="metric-unit">passed</span>
            </div>
            <div className="metric-diff positive">
              <CheckCircle size={12} />
              <span>
                {tests_total > 0 && tests_passed === tests_total
                  ? 'All tests passing'
                  : `${tests_passed} tests passed`}
              </span>
            </div>
            <span className="metric-subinfo">
              Semantic equivalence checked
            </span>
          </div>
        </div>

        {simulation && (
          <div style={{ marginTop: 10, display: 'flex', alignItems: 'center', gap: 6, fontSize: 11, color: 'var(--text-light)' }}>
            <Info size={12} />
            <span>Metrics are simulated frontend estimates for compiler optimization analysis.</span>
          </div>
        )}
      </div>
    </div>
  );
};

export default OptimizationMetrics;
