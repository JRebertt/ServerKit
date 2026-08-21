import { useTranslation } from 'react-i18next';
const TypingIndicator = ({ label }) => {
    const { t } = useTranslation();
    return (
        <div className="sk-ai-typing" role="status" aria-label={t('app.typingIndicator.assistantIsThinking', 'Assistant is thinking')}>
            {label ? <span className="sk-ai-typing__label">{label}</span> : null}
            <span className="sk-ai-typing__dots" aria-hidden="true">
                <i /><i /><i />
            </span>
        </div>
    );
};

export default TypingIndicator;
