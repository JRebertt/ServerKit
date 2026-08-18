import SharedVariableGroups from '../components/shared/SharedVariableGroups';
import { useWorkspace } from '../contexts/WorkspaceContext';

/**
 * SharedVariables — workspace-scoped management of shared variable groups
 * (the polymorphic facade: groups of variables that attach to any resource).
 * Scoped to the active workspace context; falls back to 'default'.
 */
const SharedVariables = () => {
    const { activeWorkspaceId, isAllWorkspaces } = useWorkspace();
    const workspaceId = isAllWorkspaces ? 'default' : activeWorkspaceId;

    // No wrapper: SharedVariableGroups renders through ResourceListPage, which
    // supplies the `sk-tabgroup__inner` box itself. Nesting a second one padded
    // the table twice.
    return <SharedVariableGroups scopeType="workspace" scopeId={workspaceId} />;
};

export default SharedVariables;
