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

const DB_NAME = 'AryhantDB';
const DB_VERSION = 1;

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
}

export const globalIDBStorage = new IDBStorage();
