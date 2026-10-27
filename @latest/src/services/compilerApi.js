/**
 * Compiler API Service
 * 
 * Connects the frontend code editor to the FastAPI backend at /execute.
 * Supports Python and C code execution.
 */

const BACKEND_URL =
  (typeof import.meta !== 'undefined' && import.meta.env && import.meta.env.VITE_API_URL)
    ? import.meta.env.VITE_API_URL
    : 'http://127.0.0.1:8000';

/**
 * Sends source code to the FastAPI backend at /execute.
 * 
 * @param {Object} payload 
 * @returns {Promise<Object>}
 */
export async function runCode(payload) {
  if (!payload) {
    throw new Error('Payload is required.');
  }

  const normalizedLang = (payload.language || '').toLowerCase().trim();
  if (normalizedLang !== 'python' && normalizedLang !== 'c') {
    throw new Error(`Unsupported language: '${payload.language}'. Only Python and C are supported.`);
  }

  const sourceCode = payload.source_code ?? '';

  if (sourceCode.trim() === '') {
    return {
      p_id: '',
      message: 'Source code cannot be empty.',
      status: 'failed',
      language: normalizedLang,
      stdout: '',
      output: '',
      stderr: 'Error: Source code cannot be empty.',
      exit_code: 1,
      execution_time_ms: 0,
      simulation: false,
      error_message: 'Source code cannot be empty.',
    };
  }

  try {
    const response = await fetch(`${BACKEND_URL}/execute`, {
      method: 'POST',
      headers: {
        'Content-Type': 'application/json',
      },
      body: JSON.stringify({
        language: normalizedLang,
        source_code: sourceCode,
      }),
    });

    if (!response.ok) {
      let errorDetail = `Backend HTTP Error: ${response.status} ${response.statusText}`;
      let pId = '';
      try {
        const errorData = await response.json();
        if (errorData.p_id) {
          pId = errorData.p_id;
        }
        if (errorData.detail) {
          if (Array.isArray(errorData.detail)) {
            errorDetail = errorData.detail.map((d) => d.msg || JSON.stringify(d)).join('; ');
          } else {
            errorDetail = String(errorData.detail);
          }
        }
      } catch {
        // Response was not JSON
      }

      return {
        p_id: pId,
        message: errorDetail,
        status: 'failed',
        language: normalizedLang,
        stdout: '',
        output: '',
        stderr: errorDetail,
        exit_code: response.status,
        execution_time_ms: 0,
        simulation: false,
        error_message: errorDetail,
      };
    }

    const data = await response.json();

    // Map backend response fields (backend returns `output`, `p_id`, `message`, `status`)
    const rawStdout = data.output ?? data.stdout ?? '';

    return {
      p_id: data.p_id || '',
      message: data.message || '',
      status: data.status || (data.exit_code === 0 ? 'completed' : 'failed'),
      language: data.language || normalizedLang,
      stdout: rawStdout,
      output: rawStdout,
      stderr: data.stderr || '',
      exit_code: typeof data.exit_code === 'number' ? data.exit_code : 0,
      execution_time_ms: typeof data.execution_time_ms === 'number' ? data.execution_time_ms : 0,
      simulation: false,
    };
  } catch (err) {
    const networkErrorMsg =
      err instanceof Error
        ? `Backend connection failed: ${err.message}. Ensure the FastAPI server is running at ${BACKEND_URL}.`
        : `Network error connecting to backend at ${BACKEND_URL}.`;

    return {
      p_id: '',
      message: networkErrorMsg,
      status: 'failed',
      language: normalizedLang,
      stdout: '',
      output: '',
      stderr: networkErrorMsg,
      exit_code: -1,
      execution_time_ms: 0,
      simulation: false,
      error_message: networkErrorMsg,
    };
  }
}

export async function getTac(pId) {
  if (!pId) {
    throw new Error('A compilation job ID is required to retrieve TAC.');
  }

  const response = await fetch(`${BACKEND_URL}/tac/${encodeURIComponent(pId)}`);
  if (!response.ok) {
    let detail = `Unable to retrieve TAC (${response.status}).`;
    try {
      const errorData = await response.json();
      if (errorData.detail) {
        detail = String(errorData.detail);
      }
    } catch {
      // Keep the HTTP status message when the error response is not JSON.
    }
    throw new Error(detail);
  }

  return response.json();
}

export async function optimizeCode(pId, configuration = {}) {
  if (!pId) {
    throw new Error('Run C code before requesting optimization.');
  }

  const response = await fetch(`${BACKEND_URL}/optimize`, {
    method: 'POST',
    headers: {
      'Content-Type': 'application/json',
    },
    body: JSON.stringify({ p_id: pId, ...configuration }),
  });

  if (!response.ok) {
    let detail = `Optimization failed (${response.status}).`;
    try {
      const errorData = await response.json();
      if (errorData.detail) {
        detail = String(errorData.detail);
      }
    } catch {
      // Keep the HTTP status message when the error response is not JSON.
    }
    throw new Error(detail);
  }

  return response.json();
}
