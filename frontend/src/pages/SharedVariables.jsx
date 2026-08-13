import SharedVariableGroups from '../components/shared/SharedVariableGroups';

/**
 * SharedVariables — workspace-scoped management of shared variable groups
 * (the polymorphic facade: groups of variables that attach to any resource).
 * Scoped to the active workspace from localStorage; falls back to 'default'.
 */
const SharedVariables = () => {
    const workspaceId = localStorage.getItem('active_workspace_id') || 'default';

    // No wrapper: SharedVariableGroups renders through ResourceListPage, which
    // supplies the `sk-tabgroup__inner` box itself. Nesting a second one padded
    // the table twice.
    return <SharedVariableGroups scopeType="workspace" scopeId={workspaceId} />;
};

export default SharedVariables;
