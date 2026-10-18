import React from 'react';
import { Plus, Trash2, CheckSquare } from 'lucide-react';
import type { TestCase } from '../types/compiler';

interface TestCasesProps {
  testCases: TestCase[];
  onChange: (updatedTestCases: TestCase[]) => void;
  disabled?: boolean;
}

export const TestCases: React.FC<TestCasesProps> = ({
  testCases,
  onChange,
  disabled = false,
}) => {
  const handleAddTestCase = () => {
    const newId = `test-${Date.now().toString().slice(-4)}`;
    const newCase: TestCase = {
      id: newId,
      input: '',
      expected_output: '',
    };
    onChange([...testCases, newCase]);
  };

  const handleRemoveTestCase = (id: string) => {
    if (testCases.length <= 1) {
      // Prevent deleting all test cases, or clear the one
      onChange([{ id: 'test-1', input: '', expected_output: '' }]);
      return;
    }
    onChange(testCases.filter((tc) => tc.id !== id));
  };

  const handleFieldChange = (
    id: string,
    field: 'input' | 'expected_output',
    value: string
  ) => {
    const updated = testCases.map((tc) => {
      if (tc.id === id) {
        return { ...tc, [field]: value };
      }
      return tc;
    });
    onChange(updated);
  };

  return (
    <div className="panel-card">
      <div className="panel-header">
        <div className="panel-title-area">
          <span className="panel-title">
            <CheckSquare size={15} />
            Test Cases
          </span>
          <span className="panel-badge">
            {testCases.length} {testCases.length === 1 ? 'case' : 'cases'}
          </span>
        </div>
        <div className="panel-actions">
          <button
            type="button"
            className="btn-add-tc"
            onClick={handleAddTestCase}
            disabled={disabled}
            title="Add a new test case"
          >
            <Plus size={13} />
            <span>Add Test Case</span>
          </button>
        </div>
      </div>

      <div className="testcases-body">
        {testCases.map((tc, index) => (
          <div key={tc.id} className="testcase-item">
            <div className="testcase-item-header">
              <span>Test Case #{index + 1}</span>
              <button
                type="button"
                className="btn-remove-tc"
                onClick={() => handleRemoveTestCase(tc.id)}
                disabled={disabled}
                title="Remove this test case"
              >
                <Trash2 size={13} />
              </button>
            </div>

            <div className="testcase-fields-grid">
              <div className="field-group">
                <label htmlFor={`tc-in-${tc.id}`} className="field-label">Standard Input (stdin)</label>
                <textarea
                  id={`tc-in-${tc.id}`}
                  className="field-textarea"
                  placeholder="Optional input passed to program..."
                  value={tc.input}
                  disabled={disabled}
                  rows={2}
                  onChange={(e) =>
                    handleFieldChange(tc.id, 'input', e.target.value)
                  }
                />
              </div>

              <div className="field-group">
                <label htmlFor={`tc-out-${tc.id}`} className="field-label">Expected Output (stdout)</label>
                <textarea
                  id={`tc-out-${tc.id}`}
                  className="field-textarea"
                  placeholder="Expected output to verify against..."
                  value={tc.expected_output}
                  disabled={disabled}
                  rows={2}
                  onChange={(e) =>
                    handleFieldChange(tc.id, 'expected_output', e.target.value)
                  }
                />
              </div>
            </div>
          </div>
        ))}
      </div>
    </div>
  );
};

export default TestCases;
