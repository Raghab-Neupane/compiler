import React from 'react';
import Editor from '@monaco-editor/react';
import { FileCode, Code2 } from 'lucide-react';

interface CodeEditorProps {
  code: string;
  onChange: (value: string) => void;
  disabled?: boolean;
  language: 'python' | 'c';
}

export const CodeEditor: React.FC<CodeEditorProps> = ({
  code,
  onChange,
  disabled = false,
  language = 'python',
}) => {
  const lineCount = (code || '').split('\n').length;
  const fileName = language === 'c' ? 'main.c' : 'main.py';
  const langLabel = language === 'c' ? 'C' : 'Python';
  const monacoLang = language === 'c' ? 'c' : 'python';
  const compilerStandard = language === 'c' ? 'C11 (Clang)' : 'Python 3.10+';

  return (
    <div className="panel-card">
      <div className="panel-header">
        <div className="panel-title-area">
          <span className="panel-title">
            <FileCode size={15} />
            {fileName}
          </span>
          <span className="panel-badge">{langLabel}</span>
        </div>
        <div className="panel-actions">
          <span className="panel-badge" title="Line count">
            {lineCount} {lineCount === 1 ? 'line' : 'lines'}
          </span>
        </div>
      </div>

      <div className="editor-wrapper">
        <Editor
          height="100%"
          language={monacoLang}
          theme="vs"
          value={code}
          onChange={(val) => onChange(val || '')}
          options={{
            readOnly: disabled,
            minimap: { enabled: false },
            fontSize: 13,
            fontFamily: "'JetBrains Mono', 'Fira Code', 'SFMono-Regular', Menlo, Monaco, Consolas, monospace",
            lineNumbers: 'on',
            scrollBeyondLastLine: false,
            automaticLayout: true,
            tabSize: 4,
            insertSpaces: true,
            autoIndent: 'full',
            wordWrap: 'on',
            overviewRulerBorder: false,
            scrollbar: {
              verticalScrollbarSize: 6,
              horizontalScrollbarSize: 6,
            },
            padding: {
              top: 10,
              bottom: 10,
            },
          }}
          loading={
            <div className="tac-empty-state">
              <Code2 size={24} />
              <span className="tac-empty-title">Loading {langLabel} Editor...</span>
            </div>
          }
        />
      </div>

      <div className="editor-footer">
        <span>UTF-8</span>
        <span>Spaces: 4</span>
        <span>{compilerStandard}</span>
      </div>
    </div>
  );
};

export default CodeEditor;
