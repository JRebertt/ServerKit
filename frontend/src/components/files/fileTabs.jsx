import { FolderOpen } from 'lucide-react';

// Shared sub-nav for the Files page group. Rendered in each page's
// <PageTopbar tabs={FILE_TABS}> — the demo's top-bar layout replaces the
// old sidebar sub-menu (see docs/REDESIGN_MAP.md §6 decision 3).
// The FTP Server tab is contributed by the serverkit-ftp builtin extension
// (tab-group contribution, #43) and merged in by TabGroupLayout groupId="files".
export const FILE_TABS = [
    { to: '/files', labelKey: 'app.fileTabs.files', label: 'Files', end: true, icon: <FolderOpen size={15} /> },
];
