// Canonical "save this to the user's disk" helper.
//
//   downloadBlob(logText, 'app-logs.txt');
//   downloadBlob(JSON.stringify(theme, null, 2), 'theme.json', { type: 'application/json' });
//   downloadBlob(pngBlob, 'chart.png');
//
// The six-line anchor ritual this replaces was pasted into 14 components, and
// the copies had drifted apart in two ways that decide whether the download
// actually happens:
//
//   * only 3 of 14 appended the anchor to the document. Chrome dispatches a
//     click on a detached anchor; Firefox has not always done so, which makes
//     "download does nothing" a browser-specific bug that never reproduces for
//     whoever wrote it.
//   * most revoked the object URL on the very next line after click(). The
//     download is started asynchronously, so revoking immediately can cancel
//     it — again browser- and timing-dependent, so it shows up as a flaky
//     "sometimes the file is empty / never appears".
//
// Revoking is not optional either: an un-revoked object URL pins its blob in
// memory for the lifetime of the document, which on a long-lived panel page
// that exports repeatedly is a leak.
export function downloadBlob(content, filename, options = {}) {
    const { type = 'text/plain' } = options;

    if (typeof document === 'undefined') return false;

    const blob = content instanceof Blob ? content : new Blob([content ?? ''], { type });
    const url = URL.createObjectURL(blob);
    const anchor = document.createElement('a');
    anchor.href = url;
    anchor.download = filename;
    anchor.rel = 'noopener';
    anchor.style.display = 'none';

    // In the document, because a detached anchor is not reliably clickable.
    document.body.appendChild(anchor);
    anchor.click();
    document.body.removeChild(anchor);

    // On a later task, so the browser has actually picked the blob up. Revoking
    // synchronously after click() races the download it just started.
    setTimeout(() => URL.revokeObjectURL(url), 0);
    return true;
}

export default downloadBlob;
