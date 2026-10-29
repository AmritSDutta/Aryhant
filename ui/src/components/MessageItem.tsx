import React from 'react';
import { Message } from '../lib/types';
import { HumanizedMessage } from './HumanizedMessage';

interface MessageItemProps {
  message: Message;
}

export const MessageItem: React.FC<MessageItemProps> = ({ message }) => {
  const isUser = message.sender === 'user';

  return (
    <div className={`message-row ${message.sender}`}>
      <div className="message-bubble">
        <HumanizedMessage content={message.text} />
        <div className="message-meta">
          <span>{message.timestamp}</span>
          {!isUser && message.model && (
            <span className="model-tag">{message.model}</span>
          )}
          {message.status === 'sending' && <span>(sending...)</span>}
        </div>
      </div>
    </div>
  );
};
