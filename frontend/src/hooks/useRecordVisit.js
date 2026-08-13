import { useEffect } from 'react';
import { recordVisit } from '@/utils/recents';

// Records a detail-page visit for the command palette's Recent section.
// Call once per detail page with the entity's stable identity:
//
//   useRecordVisit(service && { type: 'service', id: service.id, path: `/services/${service.id}`, label: service.name });
//
// Pass null while the entity is still loading — the visit is recorded once
// the label is known.
export function useRecordVisit(entry) {
    useEffect(() => {
        if (entry) recordVisit(entry);
        // eslint-disable-next-line react-hooks/exhaustive-deps
    }, [entry?.type, entry?.id, entry?.label]);
}

export default useRecordVisit;
