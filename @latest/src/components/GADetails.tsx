import React from 'react';
import { Activity, AlertCircle, ArrowRight, Dna } from 'lucide-react';
import type { OptimizeResponse } from '../types/compiler';

interface GADetailsProps {
  optimizeResult: OptimizeResponse | null;
  isStale: boolean;
  status: 'idle' | 'running' | 'optimizing';
}

const numberValue = (value: number | null | undefined, digits = 4) => (
  value === null || value === undefined || !Number.isFinite(value)
    ? '—'
    : value.toPrecision(digits)
);

const passLabel = (passId: string, result: OptimizeResponse) => (
  result.pass_registry?.find((pass) => pass.pass_id === passId)?.display_name ?? passId
);

export const GADetails: React.FC<GADetailsProps> = ({ optimizeResult, isStale, status }) => {
  if (!optimizeResult) {
    return (
      <div className="panel-card">
        <div className="panel-header"><span className="panel-title"><Dna size={15} /> Genetic LLVM optimizer</span></div>
        <div className="tac-empty-state"><Activity size={24} /><span className="tac-empty-title">{status === 'optimizing' ? 'LLVM optimization in progress' : 'LLVM pass search'}</span><span className="tac-empty-desc">{status === 'optimizing' ? 'Evaluating native pass sequences and validating their output.' : 'Results appear after optimizing a C compilation.'}</span></div>
      </div>
    );
  }

  const result = optimizeResult;
  if (result.status === 'error') {
    return (
      <div className="panel-card">
        <div className="panel-header"><span className="panel-title"><Dna size={15} /> Genetic LLVM optimizer</span></div>
        <div className="tac-empty-state" role="alert"><AlertCircle size={24} /><span className="tac-empty-title">Optimization failed</span><span className="tac-empty-desc">{result.error_message ?? 'The backend did not return an optimization result.'}</span></div>
      </div>
    );
  }
  const generations = result.generation_history ?? [];
  const evaluations = result.candidate_evaluations ?? [];
  const events = result.pass_events ?? [];
  const diagnostics = result.pass_diagnostics ?? [];
  const verified = result.status === 'success' && result.equivalent === true;
  const selectedCandidate = result.selected_result_type === 'candidate';
  const bestValidCandidate = result.best_valid_ga_candidate;
  const originalIr = result.original_ir ?? result.original_llvm_ir;
  const selectedIr = result.optimized_ir ?? result.optimized_llvm_ir;
  const evaluatedDiagnostics = result.evaluated_pass_diagnostics
    ?? evaluations.flatMap((candidate) => candidate.pass_diagnostics ?? []);
  const evaluatedEvents = result.evaluated_pass_events
    ?? evaluations.flatMap((candidate) => candidate.pass_events ?? []);
  const activityDiagnostics = selectedCandidate ? diagnostics : evaluatedDiagnostics;
  const activityEvents = selectedCandidate ? events : evaluatedEvents;
  const changed = activityEvents.length > 0
    ? activityEvents.filter((event) => event.changed)
    : activityDiagnostics.filter((diagnostic) => diagnostic.changed);
  const requested = activityEvents.length || activityDiagnostics.length;
  const rejected = evaluations.filter((candidate) => candidate.status === 'rejected');
  const maxFitness = Math.max(...generations.map((row) => row.best_fitness ?? 0), 0);
  const standard = result.standard_optimizations ?? {};
  const maxRuntime = Math.max(
    ...generations.map((row) => row.best_execution_time_ms ?? 0),
    result.optimized_execution_time_ms ?? 0,
    0,
  );
  const comparisonRuntime = ['O0', 'O1', 'O2', 'O3', 'GA']
    .map((level) => level === 'GA' ? result.optimized_execution_time_ms : standard[level]?.runtime_ms)
    .map((value) => value ?? 0);
  const maxComparisonRuntime = Math.max(...comparisonRuntime, 0);

  return (
    <div className="panel-card">
      <div className="panel-header">
        <div className="panel-title-area"><span className="panel-title"><Dna size={15} /> Genetic LLVM optimizer</span><span className="panel-badge">native LLVM passes</span>{isStale && <span className="panel-badge" style={{ color: 'var(--warning-color)' }}>Stale</span>}</div>
        <span className={`meta-status-pill ${verified ? 'success' : 'error'}`}>{verified ? (selectedCandidate ? 'Verified candidate' : 'Verified baseline') : 'Not verified'}</span>
      </div>

      <div className="ga-body">
        <div className="ga-params-grid">
          <div className="ga-param-box"><div className="ga-param-label">Completed generations</div><div className="ga-param-val">{generations.length} / {result.generations}</div></div>
          <div className="ga-param-box"><div className="ga-param-label">Population</div><div className="ga-param-val">{result.population_size}</div></div>
          <div className="ga-param-box"><div className="ga-param-label">Best fitness</div><div className="ga-param-val">{verified ? numberValue(result.best_fitness) : '—'}</div></div>
          <div className="ga-param-box"><div className="ga-param-label">Objective</div><div className="ga-param-val">{result.objective ?? '—'}</div></div>
        </div>

        <div className="ga-sequence-area"><span className="ga-sequence-title">Final selected result · {result.best_chromosome_id ?? '—'}</span>
          {verified && selectedCandidate && result.pass_sequence.length > 0 ? <div className="ga-passes-list">{result.pass_sequence.map((passId, index) => <React.Fragment key={`${passId}-${index}`}><div className="ga-pass-badge completed" title={passLabel(passId, result)}><span>{passId}</span><span className="ga-pass-name">{passLabel(passId, result)}</span></div>{index < result.pass_sequence.length - 1 && <ArrowRight className="ga-pass-arrow" size={12} />}</React.Fragment>)}</div> : <span className="tac-empty-desc">{result.selected_result_type === 'baseline' ? 'Baseline retained; no GA chromosome beat the configured objective.' : 'No verified LLVM chromosome was retained.'}</span>}
          {result.selection_reason && <span className="tac-empty-desc">{result.selection_reason}</span>}
        </div>

        <div className="ga-sequence-area">
          <span className="ga-sequence-title">Best valid GA candidate · {bestValidCandidate?.candidate_id ?? 'none'}</span>
          {bestValidCandidate ? <>
            <span className="tac-empty-desc">Pass sequence: {bestValidCandidate.pass_sequence.length > 0 ? bestValidCandidate.pass_sequence.join(' → ') : '(empty)'}</span>
            <span className="tac-empty-desc">Runtime: {numberValue(bestValidCandidate.runtime_ms, 5)} ms ± {numberValue(bestValidCandidate.runtime_spread_ms, 5)} ms · binary: {bestValidCandidate.binary_size ?? '—'} bytes · equivalent: {bestValidCandidate.equivalent ? 'yes' : 'no'}</span>
          </> : <span className="tac-empty-desc">No valid GA chromosome was retained; the baseline is the only verified result.</span>}
        </div>

        {result.unsupported_passes && result.unsupported_passes.length > 0 && <div className="ga-sequence-area"><span className="ga-sequence-title">Unavailable LLVM passes</span><span className="tac-empty-desc">{result.unsupported_passes.map((pass) => pass.pipeline).join(', ')} · excluded because the selected opt does not expose them.</span></div>}

        {generations.length > 0 && <div className="ga-sequence-area"><span className="ga-sequence-title">Fitness versus generation</span><div className="ga-fitness-chart" aria-label="Fitness versus generation">{generations.map((row) => <div className="ga-fitness-point" key={row.generation}><div className="ga-fitness-bar-track"><div className="ga-fitness-bar" style={{ height: `${maxFitness > 0 && row.best_fitness !== null && row.best_fitness !== undefined ? (row.best_fitness / maxFitness) * 100 : 0}%` }} /></div><span>G{row.generation}</span><span className="ga-fitness-value">{numberValue(row.best_fitness)}</span></div>)}</div></div>}

        {generations.length > 0 && <div className="ga-sequence-area"><span className="ga-sequence-title">Execution time versus generation</span><div className="ga-fitness-chart" aria-label="Execution time versus generation">{generations.map((row) => <div className="ga-fitness-point" key={`runtime-${row.generation}`}><div className="ga-fitness-bar-track"><div className="ga-fitness-bar" style={{ height: `${maxRuntime > 0 && row.best_execution_time_ms !== null && row.best_execution_time_ms !== undefined ? (row.best_execution_time_ms / maxRuntime) * 100 : 0}%` }} /></div><span>G{row.generation}</span><span className="ga-fitness-value">{numberValue(row.best_execution_time_ms, 5)} ms</span></div>)}</div></div>}

        <div className="ga-sequence-area"><span className="ga-sequence-title">Generation history</span>{generations.length > 0 ? <div style={{ overflowX: 'auto' }}><table className="metrics-table"><thead><tr><th>Gen</th><th>Best fitness</th><th>Avg fitness</th><th>Best ms</th><th>Best bytes</th><th>Valid / rejected</th></tr></thead><tbody>{generations.map((row) => <tr key={row.generation}><td>{row.generation}</td><td>{numberValue(row.best_fitness)}</td><td>{numberValue(row.average_fitness)}</td><td>{numberValue(row.best_execution_time_ms, 5)}</td><td>{row.best_binary_size ?? '—'}</td><td>{row.valid_candidates ?? 0} / {row.rejected_candidates ?? 0}</td></tr>)}</tbody></table></div> : <span className="tac-empty-desc">No generation has been evaluated.</span>}</div>

        <div className="ga-sequence-area"><span className="ga-sequence-title">Standard LLVM versus GA</span><div className="ga-fitness-chart" aria-label="Standard LLVM versus GA runtime">{['O0', 'O1', 'O2', 'O3', 'GA'].map((level, index) => <div className="ga-fitness-point" key={`comparison-${level}`}><div className="ga-fitness-bar-track"><div className="ga-fitness-bar" style={{ height: `${maxComparisonRuntime > 0 ? (comparisonRuntime[index] / maxComparisonRuntime) * 100 : 0}%` }} /></div><span>{level === 'GA' ? 'GA' : `-${level}`}</span><span className="ga-fitness-value">{numberValue(comparisonRuntime[index], 5)} ms</span></div>)}</div><div style={{ overflowX: 'auto' }}><table className="metrics-table"><thead><tr><th>Level</th><th>Runtime (ms)</th><th>Binary (bytes)</th><th>Equivalent</th><th>Samples</th></tr></thead><tbody>{['O0', 'O1', 'O2', 'O3'].map((level) => { const row = standard[level]; return <tr key={level}><td>-{level}</td><td>{numberValue(row?.runtime_ms, 5)}</td><td>{row?.binary_size ?? '—'}</td><td>{row?.equivalent ? 'yes' : 'no'}</td><td>{row?.tests_passed ?? 0} / {row?.tests_total ?? 0}</td></tr>; })}</tbody></table></div><span className="tac-empty-desc">GA versus -O3: {numberValue(result.improvement_over_o3_percent, 5)}%</span>{result.benchmark_note && <span className="tac-empty-desc">{result.benchmark_note}</span>}</div>

        <div className="ga-sequence-area"><span className="ga-sequence-title">Correctness result</span><span className="tac-empty-desc">Exit status: {result.original_exit_code ?? '—'} → {result.optimized_exit_code ?? '—'} · stdout/stderr match: {result.equivalent === true ? 'yes' : 'no'}</span><div className="output-grid" style={{ display: 'grid', gridTemplateColumns: '1fr 1fr', gap: 10, marginTop: 8 }}><div><span className="ga-param-label">Original stdout</span><pre style={{ whiteSpace: 'pre-wrap' }}>{result.original_stdout || '[empty]'}</pre></div><div><span className="ga-param-label">Optimized stdout</span><pre style={{ whiteSpace: 'pre-wrap' }}>{result.optimized_stdout || '[empty]'}</pre></div></div></div>

        <div className="ga-sequence-area">
          <span className="ga-sequence-title">LLVM IR returned by the backend</span>
          <div className="ir-grid" style={{ display: 'grid', gridTemplateColumns: '1fr 1fr', gap: 10, marginTop: 8 }}>
            <div><span className="ga-param-label">Original LLVM IR</span><pre style={{ maxHeight: 320, overflow: 'auto', whiteSpace: 'pre-wrap' }}>{originalIr ?? '[Original IR was not returned]'}</pre></div>
            <div><span className="ga-param-label">Final selected LLVM IR · {result.best_chromosome_id ?? '—'}</span><pre style={{ maxHeight: 320, overflow: 'auto', whiteSpace: 'pre-wrap' }}>{selectedIr ?? '[Selected IR was not returned]'}</pre></div>
          </div>
          <span className="tac-empty-desc">IR identity: original {result.original_ir_sha256 ?? '—'} · selected {result.optimized_ir_sha256 ?? '—'}</span>
        </div>

        <div className="ga-sequence-area">
          <span className="ga-sequence-title">Best valid GA candidate LLVM IR</span>
          <pre style={{ maxHeight: 320, overflow: 'auto', whiteSpace: 'pre-wrap' }}>{bestValidCandidate?.llvm_ir ?? '[No valid GA candidate IR was returned]'}</pre>
          {bestValidCandidate && <span className="tac-empty-desc">This is separate from the final selected IR. The final selected result may be the baseline.</span>}
        </div>

        <div className="ga-sequence-area"><span className="ga-sequence-title">Runtime validation</span><span className="tac-empty-desc">Selected median: {numberValue(result.optimized_execution_time_ms, 5)} ms ± {numberValue(result.optimized_runtime_spread_ms, 5)} ms · baseline median: {numberValue(result.original_execution_time_ms, 5)} ms ± {numberValue(result.baseline_runtime_spread_ms, 5)} ms · samples: {result.optimized_runtime_samples?.length ?? 0}</span><span className="tac-empty-desc">{selectedCandidate ? `The selected executable was compiled from the selected LLVM IR: ${result.selected_artifact?.compiled_from_ir ? 'yes' : 'no'}.` : 'Baseline selected: the reported executable and metrics are the original O0 baseline.'} · artifact {result.selected_artifact?.binary_sha256 ?? '—'}</span></div>

        <div className="ga-sequence-area"><span className="ga-sequence-title">Native pass activity · {changed.length} changed of {requested} requested{selectedCandidate ? ' on the selected candidate' : ' across evaluated GA candidates'}</span>{activityDiagnostics.length > 0 ? <ol className="ga-timeline">{activityDiagnostics.map((diagnostic, index) => <li key={`${diagnostic.candidate_id}-${diagnostic.pass_id}-${index}`}><span className="ga-timeline-line">{diagnostic.candidate_id} · {diagnostic.pass_id} · {diagnostic.executed ? (diagnostic.ir_changed ?? diagnostic.changed ? 'changed IR' : 'no IR change') : 'not executed'}</span><span>{diagnostic.instruction_count_before ?? '—'} → {diagnostic.instruction_count_after ?? '—'} instructions · IR verified: {diagnostic.ir_verified === false ? 'no' : 'yes'} · compiled: {diagnostic.compiled === false ? 'no' : diagnostic.compiled === true ? 'yes' : '—'} · equivalent: {diagnostic.equivalent === false ? 'no' : diagnostic.equivalent === true ? 'yes' : '—'} · objective improved: {diagnostic.objective_improved === true ? 'yes' : diagnostic.objective_improved === false ? 'no' : '—'} · {diagnostic.reason ?? ((diagnostic.ir_changed ?? diagnostic.changed) ? 'observable IR change' : 'pass executed without an observable change')}</span></li>)}</ol> : <span className="tac-empty-desc">No LLVM pass diagnostics were returned by the evaluator.</span>}</div>

        {result.initial_population && result.initial_population.length > 0 && <div className="ga-sequence-area"><span className="ga-sequence-title">Initial population · evaluated candidates</span><div style={{ overflowX: 'auto' }}><table className="metrics-table"><thead><tr><th>Candidate</th><th>LLVM pass sequence</th><th>Status</th><th>Runtime</th><th>Bytes</th><th>Fitness</th></tr></thead><tbody>{result.initial_population.map((candidate) => <tr key={candidate.candidate_id}><td>{candidate.candidate_id}</td><td>{candidate.pass_sequence.join(' → ')}</td><td>{candidate.status ?? '—'}</td><td>{numberValue(candidate.runtime_ms, 5)} ms</td><td>{candidate.binary_size ?? '—'}</td><td>{numberValue(candidate.fitness)}</td></tr>)}</tbody></table></div></div>}

        {rejected.length > 0 && <div className="ga-sequence-area"><span className="ga-sequence-title">Rejected candidates · {rejected.length}</span><ul className="ga-timeline ga-pass-evaluations">{rejected.map((candidate) => <li key={candidate.candidate_id}><span className="ga-timeline-line">{candidate.candidate_id}</span><span>{candidate.pass_sequence.join(' → ') || '(empty)'} · {candidate.error_message ?? 'failed equivalence or compilation'}</span></li>)}</ul></div>}
        {result.error_message && <div className="ga-sequence-area"><span className="tac-empty-desc" role="alert">{result.error_message}</span></div>}
        {!verified && <div className="ga-disclaimer"><AlertCircle size={13} /><span>Only successfully compiled and equivalent candidates are accepted.</span></div>}
      </div>
    </div>
  );
};

export default GADetails;
