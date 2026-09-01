export type WalkthroughPermissionLevel = 'read' | 'write' | 'admin';
export type WalkthroughTone = 'cyan' | 'green' | 'amber' | 'blue' | 'violet' | 'neutral';

export interface WalkthroughPermission {
    feature: string;
    level: WalkthroughPermissionLevel;
}

export type WalkthroughCompletion =
    | { type: 'manual' }
    | { type: 'route'; path?: string }
    | { type: 'signal'; signal: string }
    | { type: 'check'; check: string }
    | { type: 'target' };

export interface WalkthroughStepDefinition {
    id: string;
    title: string;
    title_key?: string;
    description: string;
    description_key?: string;
    action?: string;
    action_key?: string;
    path?: string;
    /** Stable value from an element's data-walkthrough attribute, not a selector. */
    target?: string;
    completion?: WalkthroughCompletion;
}

export interface WalkthroughDefinition {
    id: string;
    title: string;
    title_key?: string;
    description: string;
    description_key?: string;
    duration?: string;
    duration_key?: string;
    icon?: string;
    tone?: WalkthroughTone | string;
    secondary?: boolean;
    permissions?: WalkthroughPermission[];
    steps: WalkthroughStepDefinition[];
}

export interface WalkthroughValidationIssue {
    path: string;
    message: string;
}

export interface NormalizedWalkthroughStep extends WalkthroughStepDefinition {
    target: string | null;
    completionType: WalkthroughCompletion['type'];
    route?: string;
    signal?: string;
    check?: string;
    completeWhenTargetVisible?: boolean;
}

export interface NormalizedWalkthrough extends Omit<WalkthroughDefinition, 'steps'> {
    definitionId: string;
    steps: NormalizedWalkthroughStep[];
    origin: { source: 'core' | 'extension' | 'custom'; plugin: string | null };
}

export declare const WALKTHROUGH_COMPLETION_TYPES: ReadonlyArray<{
    value: WalkthroughCompletion['type'];
    key: string;
    fallback: string;
}>;

export declare function validateWalkthroughDefinition(
    definition: unknown,
): WalkthroughValidationIssue[];

export declare function normalizeWalkthroughDefinition(
    definition: WalkthroughDefinition,
    options?: { plugin?: string | null; source?: 'extension' | 'custom'; t?: Function | null },
): NormalizedWalkthrough | null;

export declare function emitWalkthroughSignal(
    type: string,
    detail?: Record<string, unknown>,
): boolean;
