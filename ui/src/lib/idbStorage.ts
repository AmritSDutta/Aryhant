import { BM25IndexData } from './bm25';

export interface StoredDocument {
  id: string;
  name: string;
  size: number;
  pageCount: number;
  createdAt: number;
}

export interface StoredChunk {
  id: string;
  docId: string;
  pageNumber: number;
  text: string;
  tokens?: string[];
}

export interface SessionTurnRecord {
  id: string;
  sessionId: string;
  turnNumber: number;
  userPrompt?: string;
  agentMessage?: string;
  timestamp: number;
}

export interface SessionSummary {
  sessionId: string;
  firstPrompt: string;
  turnCount: number;
  createdAt: number;
  latestCreatedAt: number;
}

const DB_NAME = 'AryhantDB';
const DB_VERSION = 2;

export class IDBStorage {
  private dbPromise: Promise<IDBDatabase> | null = null;

  private getDB(): Promise<IDBDatabase> {
    if (this.dbPromise) return this.dbPromise;

    this.dbPromise = new Promise((resolve, reject) => {
      if (typeof indexedDB === 'undefined') {
        reject(new Error('IndexedDB is not available'));
        return;
      }

      const request = indexedDB.open(DB_NAME, DB_VERSION);

      request.onupgradeneeded = (event) => {
        const db = (event.target as IDBOpenDBRequest).result;
        if (!db.objectStoreNames.contains('documents')) {
          db.createObjectStore('documents', { keyPath: 'id' });
        }
        if (!db.objectStoreNames.contains('chunks')) {
          const chunkStore = db.createObjectStore('chunks', { keyPath: 'id' });
          chunkStore.createIndex('docId', 'docId', { unique: false });
        }
        if (!db.objectStoreNames.contains('bm25_index')) {
          db.createObjectStore('bm25_index', { keyPath: 'id' });
        }
        if (!db.objectStoreNames.contains('session_turns')) {
          const turnStore = db.createObjectStore('session_turns', { keyPath: 'id' });
          turnStore.createIndex('sessionId', 'sessionId', { unique: false });
          turnStore.createIndex('timestamp', 'timestamp', { unique: false });
        }
        if (!db.objectStoreNames.contains('session_meta')) {
          db.createObjectStore('session_meta', { keyPath: 'key' });
        }
      };

      request.onsuccess = () => resolve(request.result);
      request.onerror = () => reject(request.error);
    });

    return this.dbPromise;
  }

  public async saveDocument(doc: StoredDocument, chunks: StoredChunk[], indexData: BM25IndexData): Promise<void> {
    const db = await this.getDB();
    return new Promise((resolve, reject) => {
      const tx = db.transaction(['documents', 'chunks', 'bm25_index'], 'readwrite');

      tx.oncomplete = () => resolve();
      tx.onerror = () => reject(tx.error);

      tx.objectStore('documents').clear();
      tx.objectStore('chunks').clear();
      tx.objectStore('bm25_index').clear();

      tx.objectStore('documents').put(doc);
      const chunkStore = tx.objectStore('chunks');
      for (const chunk of chunks) {
        chunkStore.put(chunk);
      }
      tx.objectStore('bm25_index').put(indexData);
    });
  }

  public async getChunks(): Promise<StoredChunk[]> {
    const db = await this.getDB();
    return new Promise((resolve, reject) => {
      const tx = db.transaction('chunks', 'readonly');
      const store = tx.objectStore('chunks');
      const req = store.getAll();

      req.onsuccess = () => resolve(req.result || []);
      req.onerror = () => reject(req.error);
    });
  }

  public async getActiveDocument(): Promise<StoredDocument | null> {
    const db = await this.getDB();
    return new Promise((resolve, reject) => {
      const tx = db.transaction('documents', 'readonly');
      const store = tx.objectStore('documents');
      const req = store.getAll();

      req.onsuccess = () => {
        const docs = req.result;
        if (docs && docs.length > 0) {
          resolve(docs[docs.length - 1]);
        } else {
          resolve(null);
        }
      };
      req.onerror = () => reject(req.error);
    });
  }

  public async getBM25Index(): Promise<BM25IndexData | null> {
    const db = await this.getDB();
    return new Promise((resolve, reject) => {
      const tx = db.transaction('bm25_index', 'readonly');
      const store = tx.objectStore('bm25_index');
      const req = store.get('default_index');

      req.onsuccess = () => resolve(req.result || null);
      req.onerror = () => reject(req.error);
    });
  }

  public async clearDocuments(): Promise<void> {
    const db = await this.getDB();
    return new Promise((resolve, reject) => {
      const tx = db.transaction(['documents', 'chunks', 'bm25_index'], 'readwrite');

      tx.oncomplete = () => resolve();
      tx.onerror = () => reject(tx.error);

      tx.objectStore('documents').clear();
      tx.objectStore('chunks').clear();
      tx.objectStore('bm25_index').clear();
    });
  }

  public async saveSessionTurn(record: SessionTurnRecord): Promise<void> {
    const db = await this.getDB();
    return new Promise((resolve, reject) => {
      const tx = db.transaction('session_turns', 'readwrite');
      const store = tx.objectStore('session_turns');
      const req = store.put(record);

      req.onsuccess = () => resolve();
      req.onerror = () => reject(req.error);
    });
  }

  public async getActiveSessionTurns(sessionId: string): Promise<SessionTurnRecord[]> {
    const db = await this.getDB();
    return new Promise((resolve, reject) => {
      const tx = db.transaction('session_turns', 'readonly');
      const store = tx.objectStore('session_turns');
      const index = store.index('sessionId');
      const req = index.getAll(sessionId);

      req.onsuccess = () => {
        const turns: SessionTurnRecord[] = req.result || [];
        turns.sort((a, b) => a.timestamp - b.timestamp || a.turnNumber - b.turnNumber);
        resolve(turns);
      };
      req.onerror = () => reject(req.error);
    });
  }

  public async clearSessionTurns(sessionId: string): Promise<void> {
    const db = await this.getDB();
    const turns = await this.getActiveSessionTurns(sessionId);
    return new Promise((resolve, reject) => {
      const tx = db.transaction('session_turns', 'readwrite');
      const store = tx.objectStore('session_turns');
      for (const turn of turns) {
        store.delete(turn.id);
      }
      tx.oncomplete = () => resolve();
      tx.onerror = () => reject(tx.error);
    });
  }

  public async clearAllChatHistory(): Promise<void> {
    const db = await this.getDB();
    return new Promise((resolve, reject) => {
      const tx = db.transaction(['session_turns', 'session_meta'], 'readwrite');
      tx.oncomplete = () => resolve();
      tx.onerror = () => reject(tx.error);
      tx.objectStore('session_turns').clear();
      tx.objectStore('session_meta').clear();
    });
  }

  public async getAllSessionsSummary(): Promise<SessionSummary[]> {
    const db = await this.getDB();
    return new Promise((resolve, reject) => {
      const tx = db.transaction('session_turns', 'readonly');
      const store = tx.objectStore('session_turns');
      const req = store.getAll();

      req.onsuccess = () => {
        const turns: SessionTurnRecord[] = req.result || [];
        const sessionMap = new Map<
          string,
          { firstPrompt: string; turnCount: number; createdAt: number; latestCreatedAt: number }
        >();

        for (const turn of turns) {
          const sid = turn.sessionId;
          const prompt =
            turn.userPrompt && turn.userPrompt.trim().length > 0
              ? turn.userPrompt.trim()
              : turn.agentMessage && turn.agentMessage.trim().length > 0
              ? turn.agentMessage.trim().slice(0, 80)
              : 'Untitled Session';

          const existing = sessionMap.get(sid);
          if (!existing) {
            sessionMap.set(sid, {
              firstPrompt: prompt,
              turnCount: 1,
              createdAt: turn.timestamp,
              latestCreatedAt: turn.timestamp,
            });
          } else {
            existing.turnCount += 1;
            if (turn.timestamp < existing.createdAt) {
              existing.createdAt = turn.timestamp;
              if (turn.userPrompt && turn.userPrompt.trim().length > 0) {
                existing.firstPrompt = turn.userPrompt.trim();
              }
            }
            if (turn.timestamp > existing.latestCreatedAt) {
              existing.latestCreatedAt = turn.timestamp;
            }
          }
        }

        const summaries: SessionSummary[] = Array.from(sessionMap.entries()).map(([sessionId, val]) => ({
          sessionId,
          firstPrompt: val.firstPrompt,
          turnCount: val.turnCount,
          createdAt: val.createdAt,
          latestCreatedAt: val.latestCreatedAt,
        }));

        summaries.sort((a, b) => b.latestCreatedAt - a.latestCreatedAt);
        resolve(summaries);
      };
      req.onerror = () => reject(req.error);
    });
  }

  public async deleteSession(sessionId: string): Promise<void> {
    await this.clearSessionTurns(sessionId);
    const active = await this.getActiveSessionId();
    if (active === sessionId) {
      const db = await this.getDB();
      await new Promise<void>((resolve, reject) => {
        const tx = db.transaction('session_meta', 'readwrite');
        const store = tx.objectStore('session_meta');
        store.delete('active_session_id');
        tx.oncomplete = () => resolve();
        tx.onerror = () => reject(tx.error);
      });
    }
  }

  public async getActiveSessionId(): Promise<string | null> {
    const db = await this.getDB();
    return new Promise((resolve, reject) => {
      const tx = db.transaction('session_meta', 'readonly');
      const store = tx.objectStore('session_meta');
      const req = store.get('active_session_id');

      req.onsuccess = () => {
        const res = req.result;
        resolve(res ? res.value : null);
      };
      req.onerror = () => reject(req.error);
    });
  }

  public async setActiveSessionId(sessionId: string): Promise<void> {
    const db = await this.getDB();
    return new Promise((resolve, reject) => {
      const tx = db.transaction('session_meta', 'readwrite');
      const store = tx.objectStore('session_meta');
      const req = store.put({ key: 'active_session_id', value: sessionId });

      req.onsuccess = () => resolve();
      req.onerror = () => reject(req.error);
    });
  }
}

export const globalIDBStorage = new IDBStorage();
