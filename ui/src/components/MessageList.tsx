import React, { useEffect, useRef } from 'react';
import { Sparkles } from 'lucide-react';
import { Message } from '../lib/types';
import { MessageItem } from './MessageItem';

interface MessageListProps {
  messages: Message[];
  onSelectSuggestion: (text: string) => void;
}

const SAMPLE_SUGGESTIONS = [
  'Help me understand plant reproduction for ICSE Grade 5 science.',
  'Give me 5 practice questions on fractions with answer keys.',
  'What is the difference between solids, liquids, and gases?',
  'Calculate: 15 * 24 + 180 / 6',
];

export const MessageList: React.FC<MessageListProps> = ({ messages, onSelectSuggestion }) => {
  const bottomRef = useRef<HTMLDivElement>(null);

  useEffect(() => {
    bottomRef.current?.scrollIntoView({ behavior: 'smooth' });
  }, [messages]);

  if (messages.length === 0) {
    return (
      <div className="empty-state">
        <div className="empty-state-icon">
          <Sparkles size={24} />
        </div>
        <h3>Welcome to Aryhant</h3>
        <p>
          Your personal ICSE Grade 5 companion. Ask questions, explore science topics,
          practice math exercises, or request structured quiz drills.
        </p>
        <div className="suggestions">
          {SAMPLE_SUGGESTIONS.map((suggestion, idx) => (
            <button
              key={idx}
              className="suggestion-pill"
              onClick={() => onSelectSuggestion(suggestion)}
            >
              {suggestion}
            </button>
          ))}
        </div>
      </div>
    );
  }

  return (
    <div className="message-stream">
      {messages.map((msg) => (
        <MessageItem key={msg.id} message={msg} />
      ))}
      <div ref={bottomRef} />
    </div>
  );
};
