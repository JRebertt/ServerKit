import Markdown from './Markdown';
import ToolCallCard from './ToolCallCard';
import AttachmentChip from './AttachmentChip';

const Message = ({ message }) => {
    if (message.role === 'user') {
        return (
            <div className="sk-ai-message sk-ai-message--user">
                {(message.attachments || []).length > 0 && (
                    <div className="sk-ai-message__attachments">
                        {message.attachments.map((attachment) => (
                            <AttachmentChip
                                key={`${attachment.type}:${attachment.runKind || ''}:${attachment.id}`}
                                attachment={attachment}
                            />
                        ))}
                    </div>
                )}
                <div className="sk-ai-message__bubble">{message.content}</div>
            </div>
        );
    }

    return (
        <div className="sk-ai-message sk-ai-message--assistant">
            {(message.toolCalls || []).map((tc) => (
                <ToolCallCard key={tc.id} call={tc} />
            ))}
            {message.content ? <Markdown text={message.content} /> : null}
            {message.status === 'error' ? (
                <div className="sk-ai-message__error">{message.error || 'Something went wrong.'}</div>
            ) : null}
        </div>
    );
};

export default Message;
