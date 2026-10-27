import React from 'react';

export interface GAConfiguration {
  population_size: number;
  generations: number;
  max_chromosome_length: number;
  mutation_probability: number;
  benchmark_runs: number;
  random_seed: number;
  objective: 'execution_time' | 'binary_size';
  tournament_size: number;
}

interface GAConfigPanelProps {
  configuration: GAConfiguration;
  disabled: boolean;
  onChange: (configuration: GAConfiguration) => void;
}

export const GAConfigPanel: React.FC<GAConfigPanelProps> = ({
  configuration,
  disabled,
  onChange,
}) => {
  const update = (key: keyof GAConfiguration, value: string) => {
    const numericKeys: Array<keyof GAConfiguration> = [
      'population_size', 'generations', 'max_chromosome_length',
      'mutation_probability', 'benchmark_runs', 'random_seed', 'tournament_size',
    ];
    onChange({
      ...configuration,
      [key]: numericKeys.includes(key) ? Number(value) : value,
    } as GAConfiguration);
  };

  return (
    <div className="panel-card">
      <div className="panel-header">
        <div className="panel-title-area">
          <span className="panel-title">LLVM GA configuration</span>
          <span className="panel-badge">Native opt passes</span>
        </div>
      </div>
      <div className="ga-body">
        <div className="ga-params-grid">
          {([
            ['population_size', 'Population'],
            ['generations', 'Generations'],
            ['max_chromosome_length', 'Max pass length'],
            ['mutation_probability', 'Mutation probability'],
            ['benchmark_runs', 'Benchmark runs'],
            ['random_seed', 'Random seed'],
            ['tournament_size', 'Tournament size'],
          ] as Array<[keyof GAConfiguration, string]>).map(([key, label]) => (
            <label className="ga-param-box" key={key}>
              <span className="ga-param-label">{label}</span>
              <input
                type="number"
                min={key === 'mutation_probability' ? 0 : key === 'population_size' ? 2 : 1}
                max={key === 'mutation_probability' ? 1 : undefined}
                step={key === 'mutation_probability' ? 0.05 : 1}
                value={configuration[key]}
                disabled={disabled}
                onChange={(event) => update(key, event.target.value)}
              />
            </label>
          ))}
          <label className="ga-param-box">
            <span className="ga-param-label">Fitness objective</span>
            <select
              value={configuration.objective}
              disabled={disabled}
              onChange={(event) => update('objective', event.target.value)}
            >
              <option value="execution_time">Execution time</option>
              <option value="binary_size">Binary size</option>
            </select>
          </label>
        </div>
        <span className="tac-empty-desc">
          Candidates are evaluated from the same O0 LLVM IR and verified before selection.
        </span>
      </div>
    </div>
  );
};

export default GAConfigPanel;
