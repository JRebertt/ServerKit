// Disk reclaim (panel host): measure safe candidates, then run a curated,
// server-side-validated reclaim. The panel never picks what to delete on its
// own — every key is re-checked against a fresh scan by the backend.

export async function getDiskReclaimReport() {
    return this.request('/system/disk/reclaim/report');
}

export async function runDiskReclaim(keys, { wait = true } = {}) {
    return this.request(`/system/disk/reclaim${wait ? '' : '?wait=false'}`, {
        method: 'POST',
        body: { confirm: true, keys }
    });
}
