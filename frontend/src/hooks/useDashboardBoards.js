/**
 * Dashboard boards — load, edit and persist a user's widget layouts (plan 62).
 *
 * Supersedes `useDashboardLayout`, which kept a visibility list in
 * localStorage. Boards live server-side (`/api/v1/dashboards`) so a layout
 * follows the user to another browser, and they carry real geometry
 * (x/y/w/h/cfg per widget) rather than just an on/off flag.
 *
 * Editing is deliberately local-until-saved: `setWidgets` mutates in memory
 * only, `saveActive` writes. That is what lets the page offer Discard — the
 * snapshot taken when edit mode opens is restored verbatim, with nothing
 * having reached the server in between.
 */
import { useCallback, useEffect, useRef, useState } from 'react';
import api from '../services/api';

export default function useDashboardBoards() {
    const [boards, setBoards] = useState([]);
    const [activeBoardId, setActiveBoardId] = useState(null);
    const [loading, setLoading] = useState(true);
    const [error, setError] = useState(null);
    const snapshotRef = useRef(null);

    useEffect(() => {
        let cancelled = false;
        api.getDashboards()
            .then((data) => {
                if (cancelled) return;
                const list = Array.isArray(data?.boards) ? data.boards : [];
                setBoards(list);
                setActiveBoardId((current) => (
                    current && list.some((b) => b.id === current) ? current : (list[0]?.id ?? null)
                ));
            })
            .catch((err) => {
                if (!cancelled) setError(err?.message || 'Could not load dashboards');
            })
            .finally(() => {
                if (!cancelled) setLoading(false);
            });
        return () => { cancelled = true; };
    }, []);

    const activeBoard = boards.find((b) => b.id === activeBoardId) || boards[0] || null;

    // Local-only widget edit on the active board.
    const setWidgets = useCallback((next) => {
        setBoards((list) => list.map((b) => (
            b.id !== (activeBoard?.id) ? b : {
                ...b,
                widgets: typeof next === 'function' ? next(b.widgets || []) : next,
            }
        )));
    }, [activeBoard?.id]);

    const takeSnapshot = useCallback(() => {
        snapshotRef.current = JSON.parse(JSON.stringify(boards));
    }, [boards]);

    const restoreSnapshot = useCallback(() => {
        if (snapshotRef.current) setBoards(snapshotRef.current);
        snapshotRef.current = null;
    }, []);

    const dropSnapshot = useCallback(() => { snapshotRef.current = null; }, []);

    const saveActive = useCallback(async () => {
        if (!activeBoard) return;
        setError(null);
        try {
            await api.updateDashboard(activeBoard.id, { widgets: activeBoard.widgets || [] });
            snapshotRef.current = null;
        } catch (err) {
            // Keep the edited state on screen — losing someone's layout to a
            // failed request would be worse than showing a stale error.
            setError(err?.message || 'Could not save this dashboard');
            throw err;
        }
    }, [activeBoard]);

    const createBoard = useCallback(async (name = 'New dashboard') => {
        const board = await api.createDashboard({ name, icon: 'grid', widgets: [] });
        setBoards((list) => [...list, board]);
        setActiveBoardId(board.id);
        return board;
    }, []);

    const renameBoard = useCallback(async (id, name) => {
        setBoards((list) => list.map((b) => (b.id === id ? { ...b, name } : b)));
        try {
            await api.updateDashboard(id, { name });
        } catch (err) {
            setError(err?.message || 'Could not rename this dashboard');
        }
    }, []);

    const removeBoard = useCallback(async (id) => {
        const remaining = boards.filter((b) => b.id !== id);
        if (!remaining.length) return;           // never leave the user with none
        setBoards(remaining);
        setActiveBoardId((current) => (current === id ? remaining[0].id : current));
        try {
            await api.deleteDashboard(id);
        } catch (err) {
            setError(err?.message || 'Could not delete this dashboard');
        }
    }, [boards]);

    const resetActiveBoard = useCallback(async () => {
        if (!activeBoard) return;
        const board = await api.resetDashboard(activeBoard.id);
        setBoards((list) => list.map((b) => (b.id === board.id ? board : b)));
        return board;
    }, [activeBoard]);

    return {
        boards,
        activeBoard,
        activeBoardId: activeBoard?.id ?? null,
        setActiveBoardId,
        loading,
        error,
        setWidgets,
        saveActive,
        createBoard,
        renameBoard,
        removeBoard,
        resetActiveBoard,
        takeSnapshot,
        restoreSnapshot,
        dropSnapshot,
    };
}
