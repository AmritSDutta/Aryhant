import React, { useState, useEffect } from 'react';
import { useAuth0 } from '@auth0/auth0-react';
import { AlertCircle } from 'lucide-react';
import { Message } from '../lib/types';
import { sendChatMessage, ApiError } from '../lib/api';
import { appConfig } from '../lib/config';
import { MessageList } from './MessageList';
import { MessageInput } from './MessageInput';

const SESSION_KEY = 'aryhant_session_id';

function getOrCreateSessionId(): string {
  let sId = sessionStorage.getItem(SESSION_KEY);
  if (!sId) {
    sId = 'web-' + Math.random().toString(36).substring(2, 11) + '-' + Date.now().toString(36);
    sessionStorage.setItem(SESSION_KEY, sId);
  }
  return sId;
}

export interface ChatBridge {
  getMessages: () => Array<{ sender: 'user' | 'assistant' | 'agent'; text: string; timestamp?: string | number }>;
  postMessage: (text: string) => void;
}

interface ChatPanelProps {
  onRegisterChatBridge?: (bridge: ChatBridge) => void;
}

export const ChatPanel: React.FC<ChatPanelProps> = ({ onRegisterChatBridge }) => {
  const [sessionId, setSessionId] = useState<string>(getOrCreateSessionId);
  const [messages, setMessages] = useState<Message[]>([]);
  const [loading, setLoading] = useState<boolean>(false);
  const [alertError, setAlertError] = useState<string | null>(null);

  const messagesRef = React.useRef<Message[]>(messages);
  messagesRef.current = messages;

  useEffect(() => {
    if (onRegisterChatBridge) {
      onRegisterChatBridge({
        getMessages: () => messagesRef.current,
        postMessage: (text: string) => {
          const assistantMessage: Message = {
            id: 'msg-' + Date.now(),
            sender: 'assistant',
            text,
            model: 'WebMCP Agent',
            timestamp: new Date().toLocaleTimeString([], { hour: '2-digit', minute: '2-digit' }),
          };
          setMessages((prev) => [...prev, assistantMessage]);
        },
      });
    }
  }, [onRegisterChatBridge]);

  const auth0 = appConfig.isAuthEnabled ? useAuth0() : null;

  useEffect(() => {
    sessionStorage.setItem(SESSION_KEY, sessionId);
  }, [sessionId]);

  const handleNewSession = () => {
    const newId = 'web-' + Math.random().toString(36).substring(2, 11) + '-' + Date.now().toString(36);
    sessionStorage.setItem(SESSION_KEY, newId);
    setSessionId(newId);
    setMessages([]);
    setAlertError(null);
  };

  const handleSendMessage = async (text: string) => {
    setAlertError(null);
    const nowStr = new Date().toLocaleTimeString([], { hour: '2-digit', minute: '2-digit' });
    const userMessage: Message = {
      id: 'msg-' + Date.now(),
      sender: 'user',
      text,
      timestamp: nowStr,
    };

    setMessages((prev) => [...prev, userMessage]);
    setLoading(true);

    try {
      let token: string | undefined = undefined;
      if (appConfig.isAuthEnabled && auth0?.isAuthenticated) {
        try {
          token = await auth0.getAccessTokenSilently({
            authorizationParams: {
              audience: appConfig.auth0Audience || undefined,
            },
          });
        } catch (e) {
          console.warn('Failed to retrieve silent Auth0 token:', e);
        }
      }

      const response = await sendChatMessage({
        message: text,
        sessionId,
        userId: auth0?.user?.sub || 'web-user',
        token,
      });

      const assistantMessage: Message = {
        id: 'msg-' + Date.now(),
        sender: 'assistant',
        text: response.reply,
        model: response.model,
        timestamp: new Date().toLocaleTimeString([], { hour: '2-digit', minute: '2-digit' }),
      };

      setMessages((prev) => [...prev, assistantMessage]);
    } catch (err: unknown) {
      const errorText = err instanceof ApiError ? err.detail : 'Failed to communicate with Aryhant assistant.';
      setAlertError(errorText);

      const errorMessage: Message = {
        id: 'msg-' + Date.now(),
        sender: 'assistant',
        text: `⚠️ ${errorText}`,
        timestamp: new Date().toLocaleTimeString([], { hour: '2-digit', minute: '2-digit' }),
        status: 'error',
      };
      setMessages((prev) => [...prev, errorMessage]);
    } finally {
      setLoading(false);
    }
  };

  return (
    <div className="chat-container">
      {alertError && (
        <div className="alert-banner">
          <div style={{ display: 'flex', alignItems: 'center', gap: '0.5rem' }}>
            <AlertCircle size={16} />
            <span>{alertError}</span>
          </div>
          <button
            onClick={() => setAlertError(null)}
            style={{ background: 'none', border: 'none', cursor: 'pointer', color: 'inherit', fontWeight: 'bold' }}
          >
            ×
          </button>
        </div>
      )}

      <MessageList
        messages={messages}
        onSelectSuggestion={(suggestion) => handleSendMessage(suggestion)}
      />

      <MessageInput
        onSendMessage={handleSendMessage}
        onNewSession={handleNewSession}
        disabled={loading}
      />
    </div>
  );
};
