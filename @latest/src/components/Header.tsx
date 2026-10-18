import React from 'react';
import { Cpu, Terminal } from 'lucide-react';

interface HeaderProps {
  status: 'idle' | 'running' | 'optimizing';
}

export const Header: React.FC<HeaderProps> = ({ status }) => {
  const isProcessing = status !== 'idle';

  return (
    <header className="header-container">
      <div className="header-left">
        <div className="header-brand-icon" title="Genetic Compiler">
          <Cpu size={18} />
        </div>
        <div className="header-titles">
          <span className="header-title">Genetic Compiler</span>
          <span className="header-subtitle">Python Optimization Playground</span>
        </div>
      </div>

      <div className="header-right">
        <div className="header-lang-badge" title="Target Language: Python">
          <Terminal size={13} />
          <span>Python 3</span>
        </div>

        <div className="header-status-badge">
          <span
            className={`status-dot ${isProcessing ? 'processing' : 'ready'}`}
          />
          <span>
            {status === 'running'
              ? 'Running...'
              : status === 'optimizing'
              ? 'Optimizing (GA)...'
              : 'Ready'}
          </span>
        </div>
      </div>
    </header>
  );
};

export default Header;
