// DataGrid — the list surface for pages that need real table work: per-column
// menus (sort · group · filter · move · hide), saved views, a filter drawer,
// bulk selection, grouping, density and export.
//
// It does NOT replace ds/DataTable. DataTable stays the right answer for the
// ~50 short, read-only tables in the app; DataGrid is for the handful of pages
// where the table IS the page. Column descriptors are a superset of
// DataTable's, so moving one up is additive (add `type` and `width`).
export { DataGrid } from './DataGrid';
export { ColumnMenu } from './ColumnMenu';
export { GridViewPicker } from './GridViewPicker';
export { GridChips } from './GridChips';
export { GridBulkBar } from './GridBulkBar';
export { GridFooter } from './GridFooter';
export { GridToolsMenu } from './GridToolsMenu';
export { GridFilterDrawer } from './GridFilterDrawer';
export { GridFilterButton } from './GridFilterButton';
export { useGridConfig, makeGridConfig, GRID_DEFAULTS } from './useGridConfig';
export { useGridRows } from './useGridRows';
export { useTableChrome } from './useTableChrome';
export { useViewLink } from './useViewLink';
export {
    encodeState, decodeState, readViewParams, resolveView, copyableLink,
    handleFor, slugify as slugifyViewName, VIEW_PARAM, STATE_PARAM,
} from './viewLinks';
export {
    OPS, FIELD_TYPES, opLabel, ruleId, columnLabel, fieldValue,
    applyFilters, applySort, groupRows, ruleText, exportRows,
    isFilterable, isGroupable, isSortable, isHideable, optionsFor, valueCounts,
    inferColumnType, withInferredTypes, isDecorative,
} from './fields';
