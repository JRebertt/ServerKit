import { Component } from 'react';
import { AlertTriangle, RefreshCw } from 'lucide-react';
import api from '../services/api';
import { t } from '../i18n/t';

// Class-based Error Boundary for catching React errors
export class ErrorBoundary extends Component {
    constructor(props) {
        super(props);
        this.state = { hasError: false, error: null, errorInfo: null };
    }

    static getDerivedStateFromError(error) {
        return { hasError: true, error };
    }

    componentDidCatch(error, errorInfo) {
        this.setState({ errorInfo });
        console.error('ErrorBoundary caught an error:', error, errorInfo);
        // Fire-and-forget report to the backend error tracker. Wrapped so
        // reporting can NEVER throw inside the boundary — reportClientError
        // already swallows network failures; this guards payload assembly.
        try {
            api.reportClientError({
                message: error?.message || 'Unknown error',
                exception_type: error?.name,
                traceback: error?.stack,
                endpoint: window.location.pathname,
                context: {
                    componentStack: errorInfo?.componentStack?.slice(0, 2000),
                    userAgent: navigator.userAgent,
                },
            });
        } catch { /* reporting must never break the boundary */ }
    }

    handleRetry = () => {
        this.setState({ hasError: false, error: null, errorInfo: null });
        this.props.onRetry?.();
    };

    render() {
        if (this.state.hasError) {
            return (
                <div className="error-boundary">
                    <div className="error-boundary-icon">
                        <AlertTriangle size={32} />
                    </div>
                    <h3>{t('common.error.title', 'Something went wrong')}</h3>
                    <p className="error-boundary-message">
                        {this.state.error?.message || t('common.error.unexpected', 'An unexpected error occurred')}
                    </p>
                    <button type="button" className="btn btn-primary" onClick={this.handleRetry}>
                        <RefreshCw size={14} />
                        {t('common.actions.tryAgain', 'Try again')}
                    </button>
                </div>
            );
        }

        return this.props.children;
    }
}

// Functional component for displaying API/fetch errors
export function ErrorState({
    title = t('common.error.failedToLoad', 'Failed to load'),
    message,
    error,
    onRetry,
    compact = false
}) {
    const errorMessage = message || error?.message
        || t('common.error.loadingData', 'An error occurred while loading data');

    if (compact) {
        return (
            <div className="error-state-compact">
                <AlertTriangle size={16} />
                <span>{errorMessage}</span>
                {onRetry && (
                    <button type="button" className="btn btn-ghost btn-sm" onClick={onRetry}>
                        <RefreshCw size={14} /> {t('common.actions.retry', 'Retry')}
                    </button>
                )}
            </div>
        );
    }

    return (
        <div className="error-state">
            <div className="error-state-icon">
                <AlertTriangle size={32} />
            </div>
            <h3 className="error-state-title">{title}</h3>
            <p className="error-state-message">{errorMessage}</p>
            {onRetry && (
                <button type="button" className="btn btn-primary" onClick={onRetry}>
                    <RefreshCw size={14} />
                    {t('common.actions.tryAgain', 'Try again')}
                </button>
            )}
        </div>
    );
}

export default ErrorBoundary;
