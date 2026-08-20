import RepoPicker from './RepoPicker';
import { bitbucketProvider } from './repoProviders';

// Thin binding over the shared picker contract (plan 79 G1). The four
// provider pickers were near-identical copies; the shape they shared now
// lives in RepoPicker and the differences in repoProviders.
const BitbucketRepoPicker = ({ onPick }) => (
    <RepoPicker provider={bitbucketProvider} onPick={onPick} />
);

export default BitbucketRepoPicker;
