import { useState } from 'react';
import { Star } from 'lucide-react';
import { cn } from '@/lib/utils';
import { isFavorite, toggleFavorite } from '@/utils/recents';

// Pin/unpin an entity as a favorite (surfaced in the command palette's
// Favorites section). Sits in detail-page title areas.
//
//   <FavoriteStar type="service" id={service.id} path={`/services/${service.id}`} label={service.name} />
export function FavoriteStar({ type, id, path, label, className }) {
    const [fav, setFav] = useState(() => isFavorite(type, id));

    const toggle = () => {
        setFav(toggleFavorite({ type, id, path, label }));
    };

    return (
        <button
            type="button"
            className={cn('fav-star', fav && 'is-on', className)}
            onClick={toggle}
            title={fav ? 'Remove from favorites' : 'Add to favorites'}
            aria-label={fav ? 'Remove from favorites' : 'Add to favorites'}
            aria-pressed={fav}
        >
            <Star size={15} fill={fav ? 'currentColor' : 'none'} />
        </button>
    );
}

export default FavoriteStar;
