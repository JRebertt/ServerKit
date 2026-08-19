import { Badge } from '@/components/ui/badge';
import { serviceStatusVariant } from '@/components/ds/status';

export function ServicesGrid({ children, className = '' }) {
    return <div className={`services-grid ${className}`.trim()}>{children}</div>;
}

export function ServiceCard({
    name,
    description,
    status,
    statusVariant,
    meta = [],
    actions,
    children,
}) {
    const variant = statusVariant ?? defaultStatusVariant(status);
    return (
        <div className="service-card">
            <div className="service-header">
                <div className="service-info">
                    <span className={`status-dot ${variant}`} />
                    <h4>{name}</h4>
                </div>
                <Badge variant={variant}>{status}</Badge>
            </div>

            {description && <p className="service-description">{description}</p>}

            {meta.length > 0 && (
                <div className="service-meta">
                    {meta.map((m, i) => (
                        <span key={i} className="meta-item">
                            <span className="meta-label">{m.label}:</span> {m.value}
                        </span>
                    ))}
                </div>
            )}

            {(actions || children) && (
                <div className="service-actions">
                    {actions ?? children}
                </div>
            )}
        </div>
    );
}

function defaultStatusVariant(status) {
    return serviceStatusVariant(status);
}

export default ServiceCard;
