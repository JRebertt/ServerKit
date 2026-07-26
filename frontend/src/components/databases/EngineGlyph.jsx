import { useState } from 'react';
import { EngineIcon, hasBrandIcon } from '../icons/DatabaseBrands';
import { engineMeta } from './engineHelpers';

// The engine icon, resolved in three steps: the brand glyph we ship, then the
// template's own `icon` URL, then a generic database glyph. Never an emoji —
// the design mock uses them, this panel does not.
//
// A remote icon that 404s falls through to the glyph rather than leaving a
// broken image in the catalog grid.
export function EngineGlyph({ entry, size = 16 }) {
    const [broken, setBroken] = useState(false);

    const id = entry?.id || entry?.template_id;
    if (hasBrandIcon(id)) return <EngineIcon engine={id} size={size} />;

    if (entry?.icon && !broken) {
        return (
            <img
                className="dbx-eng-img"
                src={entry.icon}
                alt=""
                width={size}
                height={size}
                onError={() => setBroken(true)}
            />
        );
    }

    const protocol = engineMeta(entry).protocol;
    return <EngineIcon engine={hasBrandIcon(protocol) ? protocol : 'database'} size={size} />;
}

export default EngineGlyph;
