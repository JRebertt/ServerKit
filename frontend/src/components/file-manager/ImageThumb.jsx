import { useEffect, useState } from 'react';
import { api } from '../../services/api';

// Auth-fetches a file via the download endpoint, converts to a blob URL, and
// renders it as an <img>. Falls back to whatever JSX is passed in `fallback`.
export default function ImageThumb({ path, fallback, className = 'thumb-image', alt = '', isS3 = false }) {
    const [src, setSrc] = useState(null);
    const [errored, setErrored] = useState(false);

    useEffect(() => {
        let blobUrl = null;
        let cancelled = false;
        (async () => {
            try {
                // S3 objects load straight from a short-lived presigned URL — no
                // auth header or blob needed.
                if (isS3) {
                    const res = await api.getS3DownloadUrl(path);
                    if (!res || !res.url) throw new Error('no presigned url');
                    if (!cancelled) setSrc(res.url);
                    return;
                }
                const blob = await api.getFileBlob(path);
                blobUrl = URL.createObjectURL(blob);
                if (!cancelled) setSrc(blobUrl);
            } catch {
                if (!cancelled) setErrored(true);
            }
        })();
        return () => {
            cancelled = true;
            if (blobUrl) URL.revokeObjectURL(blobUrl);
        };
    }, [path, isS3]);

    if (errored || !src) return fallback;
    return <img src={src} alt={alt} className={className} loading="lazy" />;
}
