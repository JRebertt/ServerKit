import { useTranslation } from 'react-i18next';

import { api } from '../services/api';
import { useToast } from '../contexts/ToastContext';
import { useServerMutation, useServerQuery } from './useServerQuery';

// Data door for the Recipe catalog (serverkit-recipes registry). Pages render
// from this hook; raw api.* calls and query-layer error presentation stay here.

export function useRecipeCatalog() {
    const { t } = useTranslation();
    const toast = useToast();

    const registryQuery = useServerQuery(
        ['recipes', 'registry'],
        () => api.getRecipeRegistry(),
        {
            // The backend serves last-good/bundled when upstream is down, so
            // failures here are local (auth/network); surface once.
            staleTime: 60_000,
            onError: () => toast.error(
                t('app.recipes.loadFailed', 'Could not load the recipe catalog'),
            ),
        },
    );

    const serversQuery = useServerQuery(
        ['recipes', 'target-servers'],
        () => api.getServers(),
        { staleTime: 15_000 },
    );

    const startRun = useServerMutation(
        (body) => api.startRecipeRun(body),
    );

    return {
        recipes: registryQuery.data?.recipes ?? [],
        source: registryQuery.data?.source ?? null,
        isLoading: registryQuery.isLoading || serversQuery.isLoading,
        servers: serversQuery.data?.servers ?? [],
        startRun,
    };
}

// Start one recipe run. Returns the deployment job id; errors are toasted by
// the mutation wrapper so callers can just navigate on success.
export async function runRecipe({ startRun, toast, t }, body, { serverName }) {
    try {
        const result = await startRun.mutateAsync(body);
        toast.success(t('app.recipes.started', 'Recipe started on {{server}}.', {
            server: serverName,
        }));
        return result.job_id;
    } catch (err) {
        toast.error(err.message || t('app.recipes.startFailed', 'Could not start the recipe'));
        return null;
    }
}
