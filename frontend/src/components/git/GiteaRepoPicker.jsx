import RepoPicker from './RepoPicker';
import { giteaProvider } from './repoProviders';

// Thin binding over the shared picker contract (plan 79 G1). The four
// provider pickers were near-identical copies; the shape they shared now
// lives in RepoPicker and the differences in repoProviders.
const GiteaRepoPicker = ({ onPick }) => (
    <RepoPicker provider={giteaProvider} onPick={onPick} />
);

export default GiteaRepoPicker;
