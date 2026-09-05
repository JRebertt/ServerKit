import { createRoot } from 'react-dom/client';
import { MemoryRouter } from 'react-router-dom';
import { AuthProvider } from '../../src/contexts/AuthContext';
import { LocaleProvider } from '../../src/contexts/LocaleContext';
import { ToastProvider } from '../../src/contexts/ToastContext';
import { ConfirmProvider } from '../../src/contexts/ConfirmContext';
import UsersTab from '../../src/components/settings/UsersTab';
import '../../src/styles/main.scss';

// Vite-only fixture: real components/providers and the complete SCSS cascade.
// Network responses are synthetic and intercepted by the browser regression.
createRoot(document.getElementById('root')).render(
    <MemoryRouter initialEntries={['/settings/users']}>
        <LocaleProvider><AuthProvider><ToastProvider><ConfirmProvider>
            <main className="settings-content"><UsersTab /></main>
        </ConfirmProvider></ToastProvider></AuthProvider></LocaleProvider>
    </MemoryRouter>,
);
