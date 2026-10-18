import React from 'react';
import Editor from '@monaco-editor/react';
import { FileCode, Code2 } from 'lucide-react';

interface CodeEditorProps {
  code: string;
  onChange: (value: string) => void;
  disabled?: boolean;
}

export const CodeEditor: React.FC<CodeEditorProps> = ({
  code,
  onChange,
  disabled = false,
}) => {
  const lineCount = (code || '').split('\n').length;

  return (
    <div className="panel-card">
      <div className="panel-header">
        <div className="panel-title-area">
          <span className="panel-title">
            <FileCode size={15} />
            main.py
          </span>
          <span className="panel-badge">Python</span>
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
          language="python"
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
              <span className="tac-empty-title">Loading Python Editor...</span>
            </div>
          }
        />
      </div>

      <div className="editor-footer">
        <span>UTF-8</span>
        <span>Spaces: 4</span>
        <span>Python 3.10+</span>
      </div>
    </div>
  );
};

export default CodeEditor;
