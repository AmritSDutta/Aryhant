import React, { useState, useEffect, useRef, useCallback } from 'react';
import { RotateCcw, Download, Trash2 } from 'lucide-react';
import { Header } from './components/Header';
import { ConfirmationModal } from './components/ConfirmationModal';
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
      setConfirmModal({
        isOpen: true,
        title,
        message,
        confirmLabel: 'OK',
        variant: 'warning',
        onConfirm: () => setConfirmModal((prev) => ({ ...prev, isOpen: false })),
      });
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
      exportPdf: () => {
        return chatBridgeRef.current?.exportPdf?.();
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

  const [confirmModal, setConfirmModal] = useState<{
    isOpen: boolean;
    title: string;
    message: string;
    confirmLabel?: string;
    variant?: 'danger' | 'warning' | 'primary';
    onConfirm: () => void;
  }>({
    isOpen: false,
    title: '',
    message: '',
    onConfirm: () => {},
  });

  const handleNewSession = async () => {
    const hasMessages = (chatBridgeRef.current?.getMessages() || []).length > 0;
    if (hasMessages) {
      setConfirmModal({
        isOpen: true,
        title: 'Start New Session',
        message: 'Starting a new session will clear the current dialogue and prior session data from browser storage. Proceed?',
        confirmLabel: 'Start New Session',
        variant: 'primary',
        onConfirm: async () => {
          setConfirmModal((prev) => ({ ...prev, isOpen: false }));
          await chatBridgeRef.current?.newSession?.();
        },
      });
    } else {
      await chatBridgeRef.current?.newSession?.();
    }
  };

  const handleExportPdf = () => {
    const res = chatBridgeRef.current?.exportPdf?.();
    if (res && !res.success && res.error) {
      setConfirmModal({
        isOpen: true,
        title: 'Export PDF Notice',
        message: res.error,
        confirmLabel: 'OK',
        variant: 'warning',
        onConfirm: () => setConfirmModal((prev) => ({ ...prev, isOpen: false })),
      });
    }
  };

  const handleClearHistory = () => {
    setConfirmModal({
      isOpen: true,
      title: 'Clear Chat History',
      message: 'Are you sure you want to clear all conversation history from browser storage (IndexedDB)? This action cannot be undone.',
      confirmLabel: 'Clear History',
      variant: 'danger',
      onConfirm: async () => {
        setConfirmModal((prev) => ({ ...prev, isOpen: false }));
        await chatBridgeRef.current?.clearHistory?.();
      },
    });
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
          <div className="sidebar-session-controls">
            <button
              type="button"
              className="sidebar-ctrl-btn primary"
              onClick={handleNewSession}
              title="Start a new session (implicitly clears prior session data from browser storage)"
            >
              <RotateCcw size={14} />
              <span>New Session</span>
            </button>
            <button
              type="button"
              className="sidebar-ctrl-btn"
              onClick={handleExportPdf}
              title="Export current session as PDF"
            >
              <Download size={14} />
              <span>Export PDF</span>
            </button>
            <button
              type="button"
              className="sidebar-ctrl-btn danger"
              onClick={handleClearHistory}
              title="Clear all stored chat history from IndexedDB"
            >
              <Trash2 size={14} />
              <span>Clear History</span>
            </button>
          </div>
          <div className="webmcp-indicator">
            <span className="webmcp-dot"></span>
            <span>WebMCP: 10 Tools Active</span>
          </div>
        </aside>

        <main className="chat-main-area">
          <ChatPanel
            activeDocName={doc.activeDoc?.name}
            onRegisterChatBridge={handleRegisterChatBridge}
          />
        </main>
      </div>

      <ConfirmationModal
        isOpen={confirmModal.isOpen}
        title={confirmModal.title}
        message={confirmModal.message}
        confirmLabel={confirmModal.confirmLabel}
        variant={confirmModal.variant}
        onConfirm={confirmModal.onConfirm}
        onCancel={() => setConfirmModal((prev) => ({ ...prev, isOpen: false }))}
      />
    </div>
  );
};

export default App;
