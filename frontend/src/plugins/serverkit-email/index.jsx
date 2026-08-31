// Email Server, contributed through the extension system. Both halves live in
// this extension: the mail-server backend (Postfix/Dovecot/DKIM/SpamAssassin/
// Roundcube orchestration + the /api/v1/email blueprint) under backend/, and
// the full page here (pages/Email.jsx + styles/email.scss + its own API
// client in services/email.js). Imports go through 'serverkit-sdk' so the
// same source works baked in-tree (the panel's build-time glob) and as a
// runtime-ESM bundle once the extension leaves the tree (plan 52 Phase 2).
//
// The SCSS side-effect import compiles the page styles through this
// extension's own module graph — the host's main.scss no longer carries an
// _email partial.
import './styles/email.scss';

import Email from './pages/Email';

export function EmailPage() {
    return <Email />;
}
