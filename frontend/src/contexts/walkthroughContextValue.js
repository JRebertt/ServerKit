import { createContext, useContext } from 'react';


export const WalkthroughContext = createContext(null);

export function useWalkthroughs() {
    const value = useContext(WalkthroughContext);
    if (!value) throw new Error('useWalkthroughs must be used inside WalkthroughProvider');
    return value;
}
