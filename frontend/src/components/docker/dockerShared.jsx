// Every Docker tab now renders its rows through <DataTable>, whose action cells
// are plain .dx-row-action buttons around a lucide icon — so the IconAction /
// TrashIcon / DownloadIcon wrappers the hand-rolled tables shared are gone.
export const ContainerResourceBars = ({ stats, muted = false }) => (
    <div className={`dx-mini-resources ${muted || !stats.available ? 'is-muted' : ''}`}>
        <div className="dx-mini-resource">
            <span>CPU</span>
            <div className="dx-res-track">
                <div className="dx-res-fill cpu" style={{ width: `${stats.available ? Math.min(stats.cpu, 100) : 0}%` }} />
            </div>
            <strong>{stats.available ? `${stats.cpu.toFixed(1)}%` : '--'}</strong>
        </div>
        <div className="dx-mini-resource">
            <span>RAM</span>
            <div className="dx-res-track">
                <div className="dx-res-fill mem" style={{ width: `${stats.available ? Math.min(stats.memory, 100) : 0}%` }} />
            </div>
            <strong>{stats.available ? `${stats.memory.toFixed(1)}%` : '--'}</strong>
        </div>
    </div>
);
