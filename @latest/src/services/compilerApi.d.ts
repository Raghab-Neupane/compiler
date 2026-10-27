import type { GAConfiguration } from '../components/GAConfigPanel';
import type { RunPayload, RunResponse, OptimizeResponse, TacResponse } from '../types/compiler';

export declare function runCode(payload: RunPayload): Promise<RunResponse>;
export declare function optimizeCode(pId: string, configuration?: Partial<GAConfiguration>): Promise<OptimizeResponse>;
export declare function getTac(pId: string): Promise<TacResponse>;
