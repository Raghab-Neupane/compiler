import type { RunPayload, RunResponse, OptimizePayload, OptimizeResponse } from '../types/compiler';

export declare function runCode(payload: RunPayload): Promise<RunResponse>;
export declare function optimizeCode(payload: OptimizePayload): Promise<OptimizeResponse>;
