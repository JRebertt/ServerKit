import { Puzzle, PackageCheck, Download, ChefHat } from 'lucide-react';

// Shared sub-nav for the Extensions page group (Extensions / Installed /
// Recipes / Downloads). Rendered in each page's <PageTopbar tabs={MARKET_TABS}> �?" the
// top-bar layout replaces the old sidebar sub-menu (see docs/REDESIGN_MAP.md
// A6 dec. 3). Installed is a real route (/extensions/installed) so it deep-links.
export const MARKET_TABS = [
    { to: '/extensions', labelKey: 'common.labels.extensions', label: 'Extensions', end: true, icon: <Puzzle size={15} /> },
    { to: '/extensions/installed', labelKey: 'app.marketTabs.installed', label: 'Installed', icon: <PackageCheck size={15} /> },
    { to: '/extensions/recipes', labelKey: 'app.marketTabs.recipes', label: 'Recipes', icon: <ChefHat size={15} /> },
    { to: '/downloads', labelKey: 'app.marketTabs.downloads', label: 'Downloads', icon: <Download size={15} /> },
];
