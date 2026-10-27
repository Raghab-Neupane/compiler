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
          <span className="tac-empty-title">LLVM optimization results</span>
          <span className="tac-empty-desc">
          Run a C compilation, then optimize it to view measured compiler results.
          </span>
        </div>
      </div>
    );
  }

  const {
    original_execution_time_ms,
    optimized_execution_time_ms,
    time_improvement_percent,
    code_size_reduction_percent,
    tests_passed,
    tests_total,
    simulation,
    equivalent,
    original_binary_size,
    optimized_binary_size,
  } = optimizeResult;

  const isTimeImproved = (time_improvement_percent ?? 0) > 0;
  const isSizeReduced = (code_size_reduction_percent ?? 0) > 0;
  const isTimeSlower = (time_improvement_percent ?? 0) < 0;
  const isSizeLarger = (code_size_reduction_percent ?? 0) < 0;
  const verificationPassed =
    equivalent === true
    && (tests_total ?? 0) > 0
    && tests_passed === tests_total;

  return (
    <div className="panel-card">
      <div className="panel-header">
        <div className="panel-title-area">
          <span className="panel-title">
            <BarChart3 size={15} />
            Optimization Metrics
          </span>
          {optimizeResult.status === 'success' && (
            <span className="panel-badge">
              {equivalent ? 'Equivalent' : 'Not verified'}
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
              {optimized_execution_time_ms?.toFixed(2) ?? '—'}
              <span className="metric-unit">ms</span>
            </div>
            <div
              className={`metric-diff ${
                isTimeImproved ? 'positive' : isTimeSlower ? 'negative' : 'neutral'
              }`}
            >
              <TrendingDown size={12} />
              <span>
                {time_improvement_percent === null
                  ? 'Not measured'
                  : isTimeImproved
                  ? `${time_improvement_percent.toFixed(1)}% faster`
                  : isTimeSlower
                  ? `${Math.abs(time_improvement_percent).toFixed(1)}% slower`
                  : 'No change'}
              </span>
            </div>
            <span className="metric-subinfo">
              Original: {original_execution_time_ms?.toFixed(2) ?? '—'} ms
            </span>
          </div>

          {/* TAC Instructions Count */}
          <div className="metric-card">
            <span className="metric-label">Native Binary Size</span>
            <div className="metric-value">
              {optimized_binary_size ?? '—'}
              <span className="metric-unit">bytes</span>
            </div>
            <div
              className={`metric-diff ${
                isSizeReduced ? 'positive' : isSizeLarger ? 'negative' : 'neutral'
              }`}
            >
              <Code size={12} />
              <span>
                {code_size_reduction_percent === null
                  ? 'Not measured'
                  : isSizeReduced
                  ? `${code_size_reduction_percent.toFixed(1)}% reduction`
                  : isSizeLarger
                  ? `${Math.abs(code_size_reduction_percent).toFixed(1)}% larger`
                  : 'No change'}
              </span>
            </div>
            <span className="metric-subinfo">
              Original: {original_binary_size ?? '—'} bytes
            </span>
          </div>

          {/* Test Verification */}
          <div className="metric-card">
            <span className="metric-label">Verification</span>
            <div className="metric-value">
              {(tests_total ?? 0) > 0 ? `${tests_passed ?? 0} / ${tests_total}` : '—'}
              <span className="metric-unit">passed</span>
            </div>
            <div
              className={`metric-diff ${
                verificationPassed ? 'positive' : equivalent === false ? 'negative' : 'neutral'
              }`}
            >
              {verificationPassed ? <CheckCircle size={12} /> : <Info size={12} />}
              <span>
                {verificationPassed
                  ? 'All tests passing'
                  : equivalent === false
                  ? 'Equivalence failed'
                  : 'Not verified'}
              </span>
            </div>
            <span className="metric-subinfo">
              {verificationPassed ? 'Outputs and exit codes matched' : 'No verified comparison'}
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
