import { useTranslation } from 'react-i18next';
// Tiny dependency-free SVG sparkline for daily bandwidth series.
// Plain <polyline> — deliberately no chart library.

const BandwidthSparkline = ({ data, width = 96, height = 24, className = '' }) => {
    const { t } = useTranslation();
    if (!Array.isArray(data) || data.length === 0) return null;

    const max = Math.max(...data, 1);
    const stepX = data.length > 1 ? width / (data.length - 1) : width;
    const pad = 2; // keep the stroke inside the viewBox

    const points = data
        .map((value, i) => {
            const x = data.length > 1 ? i * stepX : width / 2;
            const y = pad + (1 - value / max) * (height - pad * 2);
            return `${x.toFixed(1)},${y.toFixed(1)}`;
        })
        .join(' ');

    return (
        <svg
            className={`bw-spark ${className}`.trim()}
            width={width}
            height={height}
            viewBox={`0 0 ${width} ${height}`}
            preserveAspectRatio="none"
            role="img"
            aria-label={t('app.bandwidthSparkline.dailyTransferSparkline', 'Daily transfer sparkline')}
        >
            <polyline
                points={points}
                fill="none"
                stroke="currentColor"
                strokeWidth="1.5"
                strokeLinejoin="round"
                strokeLinecap="round"
                vectorEffect="non-scaling-stroke"
            />
        </svg>
    );
};

export default BandwidthSparkline;
