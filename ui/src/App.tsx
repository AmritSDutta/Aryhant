import React, { useState, useEffect, useRef, useCallback } from 'react';
import { Header } from './components/Header';
import { ChatPanel, ChatBridge } from './components/ChatPanel';
import { FileUpload } from './components/FileUpload';
import { ReferenceUrls } from './components/ReferenceUrls';
import { useDocumentController } from './hooks/useDocumentController';
import { WebMCPProvider } from './webmcp/provider';
import { ToolContext } from './webmcp/tools';
import { searchWeb } from './lib/searchService';
import { calculateMath } from './lib/mathEvaluator';

const URLS_STORAGE_KEY = 'aryhant_reference_urls';

export const App: React.FC = () => {
  const [referenceUrls, setReferenceUrls] = useState<string[]>(() => {
    try {
      const stored = localStorage.getItem(URLS_STORAGE_KEY);
      return stored ? JSON.parse(stored) : [];
    } catch {
      return [];
    }
  });
  const referenceUrlsRef = useRef<string[]>(referenceUrls);
  referenceUrlsRef.current = referenceUrls;

  const chatBridgeRef = useRef<ChatBridge | null>(null);
  const webmcpRef = useRef<WebMCPProvider | null>(null);

  // Document controller
  const doc = useDocumentController({
    onError: (title, message) => {
      alert(`${title}: ${message}`);
    },
    onDocumentIndexed: () => {
      updateWebMCPContext();
    },
  });

  const docRef = useRef(doc);
  docRef.current = doc;

  const buildToolContext = useCallback((): ToolContext => {
    return {
      getMessages: () => {
        if (!chatBridgeRef.current) return [];
        return chatBridgeRef.current.getMessages();
      },
      postMessage: (text: string) => {
        chatBridgeRef.current?.postMessage(text);
      },
      searchDocument: async (query: string) => {
        return await docRef.current.handleSearchDocument(query);
      },
      cleanDocument: async () => {
        await docRef.current.handleCleanDocument();
      },
      searchWeb: async (query: string) => {
        return await searchWeb(query);
      },
      calculate: (expression: string) => {
        return calculateMath(expression);
      },
      getReferenceUrls: () => {
        return referenceUrlsRef.current;
      },
    };
  }, []);

  const updateWebMCPContext = useCallback((): void => {
    if (webmcpRef.current) {
      webmcpRef.current.updateContext(buildToolContext());
    }
  }, [buildToolContext]);

  // Initialize and register WebMCPProvider across all 3 compatibility surfaces once on mount
  useEffect(() => {
    const provider = new WebMCPProvider(buildToolContext());
    webmcpRef.current = provider;
    provider.register();

    return () => {
      provider.unregister();
      webmcpRef.current = null;
    };
  }, [buildToolContext]);

  const handleRegisterChatBridge = useCallback((bridge: ChatBridge) => {
    chatBridgeRef.current = bridge;
    updateWebMCPContext();
  }, [updateWebMCPContext]);

  const handleAddReferenceUrl = async (url: string): Promise<boolean> => {
    if (referenceUrls.includes(url) || referenceUrls.length >= 10) {
      return false;
    }
    const next = [...referenceUrls, url];
    setReferenceUrls(next);
    localStorage.setItem(URLS_STORAGE_KEY, JSON.stringify(next));
    updateWebMCPContext();
    return true;
  };

  const handleRemoveReferenceUrl = (url: string): void => {
    const next = referenceUrls.filter((u) => u !== url);
    setReferenceUrls(next);
    localStorage.setItem(URLS_STORAGE_KEY, JSON.stringify(next));
    updateWebMCPContext();
  };

  return (
    <div className="app-container">
      <Header />
      <div className="main-content-layout">
        <aside className="tool-sidebar">
          <FileUpload
            activeDoc={doc.activeDoc}
            onFileSelect={doc.handleFileSelect}
            onClearDocument={doc.handleCleanDocument}
          />
          <ReferenceUrls
            urls={referenceUrls}
            onAddUrl={handleAddReferenceUrl}
            onRemoveUrl={handleRemoveReferenceUrl}
          />
          <div className="webmcp-indicator">
            <span className="webmcp-dot"></span>
            <span>WebMCP: 9 Tools Active</span>
          </div>
        </aside>

        <main className="chat-main-area">
          <ChatPanel onRegisterChatBridge={handleRegisterChatBridge} />
        </main>
      </div>
    </div>
  );
};

export default App;
