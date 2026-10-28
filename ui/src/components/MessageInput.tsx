import React, { useState, KeyboardEvent } from 'react';
import { Send, RotateCcw } from 'lucide-react';

interface MessageInputProps {
  onSendMessage: (text: string) => void;
  onNewSession: () => void;
  disabled?: boolean;
}

export const MessageInput: React.FC<MessageInputProps> = ({
  onSendMessage,
  onNewSession,
  disabled = false,
}) => {
  const [text, setText] = useState('');

  const handleSend = () => {
    const trimmed = text.trim();
    if (!trimmed || disabled) return;
    onSendMessage(trimmed);
    setText('');
  };

  const handleKeyDown = (e: KeyboardEvent<HTMLTextAreaElement>) => {
    if (e.key === 'Enter' && !e.shiftKey) {
      e.preventDefault();
      handleSend();
    }
  };

  return (
    <div className="input-container">
      <div className="input-row">
        <textarea
          className="chat-input"
          placeholder="Ask a question or request practice problems... (Press Enter to send)"
          rows={1}
          value={text}
          onChange={(e) => setText(e.target.value)}
          onKeyDown={handleKeyDown}
          disabled={disabled}
        />
        <button
          className="send-btn"
          onClick={handleSend}
          disabled={!text.trim() || disabled}
          title="Send message"
        >
          <Send size={18} />
        </button>
      </div>

      <div className="input-footer">
        <button className="new-chat-btn" onClick={onNewSession} type="button">
          <RotateCcw size={12} />
          <span>New Session</span>
        </button>
        <span>Enter to send, Shift+Enter for new line</span>
      </div>
    </div>
  );
};
