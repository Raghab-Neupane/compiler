import React from 'react';
import { Terminal } from 'lucide-react';

interface HeaderProps {
  status: 'idle' | 'running' | 'optimizing';
  language: 'python' | 'c';
}

export const Header: React.FC<HeaderProps> = ({ status, language }) => {
  const isProcessing = status !== 'idle';

  return (
    <>
      <header className="header-container">
        <div className="header-left">
          <div className="header-titles">
            <span className="header-title">Genetic Algorithm Compiler Optimizer</span>
          </div>
        </div>

        <div className="header-right">
          <div
            className={`header-lang-badge ${language === 'c' ? 'c-badge' : 'python-badge'}`}
            title={`Target Language: ${language === 'c' ? 'C (Clang)' : 'Python 3'}`}
          >
            <Terminal size={13} />
            <span>{language === 'c' ? 'C (Clang)' : 'Python 3'}</span>
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

      {status === 'optimizing' && (
        <div
          className="optimization-loader-screen"
          role="status"
          aria-live="polite"
          aria-label="Optimizing code"
        >
          <div className="optimization-loader" aria-hidden="true">
            <span className="optimization-loader-ring optimization-loader-ring-outer" />
            <span className="optimization-loader-ring optimization-loader-ring-middle" />
            <span className="optimization-loader-ring optimization-loader-ring-inner" />
          </div>
          <span className="optimization-loader-title">Optimizing your code</span>
          <span className="optimization-loader-caption">
            Evaluating and verifying optimization candidates…
          </span>
        </div>
      )}
    </>
  );
};

export default Header;
