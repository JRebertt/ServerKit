// Capture the host's singleton vendor instances for runtime-loaded extension
// bundles BEFORE anything else runs (plan 25 Decision 2).
import './plugins/runtime/vendorShare'
import React from 'react'
import ReactDOM from 'react-dom/client'
import App from './App.jsx'
import ErrorBoundary from './components/ErrorBoundary.jsx'
import './styles/main.scss'

ReactDOM.createRoot(document.getElementById('root')).render(
    <React.StrictMode>
        <ErrorBoundary>
            <App />
        </ErrorBoundary>
    </React.StrictMode>,
)
