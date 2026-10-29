import { useState, useEffect, useRef, useCallback } from 'react';
import { BM25Index, removeStopWords } from '../lib/bm25';
import { globalIDBStorage, StoredDocument, StoredChunk } from '../lib/idbStorage';
import { globalLiteParseService } from '../lib/liteparseService';

export interface ActiveDocumentInfo {
  name: string;
  size: number;
  pageCount: number;
  status: 'parsing' | 'indexed' | 'error';
}

const MAX_FILE_SIZE = 2 * 1024 * 1024; // 2MB strictly
const ALLOWED_EXTENSIONS = ['.pdf', '.doc', '.docx', '.txt', '.md'];

export interface UseDocumentControllerOptions {
  onError?: (title: string, message: string) => void;
  onDocumentIndexed?: () => void;
}

export interface DocumentSearchResult {
  pageNumber: number;
  text: string;
  score: number;
}

export interface UseDocumentControllerResult {
  activeDoc: ActiveDocumentInfo | null;
  setActiveDoc: React.Dispatch<React.SetStateAction<ActiveDocumentInfo | null>>;
  bm25Ref: React.MutableRefObject<BM25Index>;
  chunksRef: React.MutableRefObject<StoredChunk[]>;
  handleFileSelect: (file: File) => Promise<void>;
  handleSearchDocument: (query: string) => Promise<DocumentSearchResult[]>;
  handleCleanDocument: () => Promise<void>;
}

export function useDocumentController({
  onError,
  onDocumentIndexed,
}: UseDocumentControllerOptions = {}): UseDocumentControllerResult {
  const [activeDoc, setActiveDoc] = useState<ActiveDocumentInfo | null>(null);
  const bm25Ref = useRef<BM25Index>(new BM25Index());
  const chunksRef = useRef<StoredChunk[]>([]);

  // Restore stored document and index from IDB on mount
  useEffect(() => {
    (async (): Promise<void> => {
      try {
        const storedDoc = await globalIDBStorage.getActiveDocument();
        const storedIndex = await globalIDBStorage.getBM25Index();
        const storedChunks = await globalIDBStorage.getChunks();

        if (storedDoc && storedIndex) {
          bm25Ref.current.loadData(storedIndex);
          chunksRef.current = storedChunks;
          setActiveDoc({
            name: storedDoc.name,
            size: storedDoc.size,
            pageCount: storedDoc.pageCount,
            status: 'indexed',
          });
        }
      } catch (err) {
        console.warn('Could not restore stored document from IDB:', err);
      }
    })();
  }, []);

  const handleFileSelect = useCallback(
    async (file: File): Promise<void> => {
      if (file.size >= MAX_FILE_SIZE) {
        onError?.(
          'File Size Exceeded',
          `File "${file.name}" is ${(file.size / (1024 * 1024)).toFixed(2)} MB. Files must be strictly under 2MB for in-browser processing.`
        );
        return;
      }

      const lowerName = file.name.toLowerCase();
      const isAllowed = ALLOWED_EXTENSIONS.some((ext) => lowerName.endsWith(ext));
      if (!isAllowed) {
        onError?.(
          'Unsupported File Type',
          `File "${file.name}" is not supported. Please upload a PDF (.pdf), Word document (.doc, .docx), text (.txt), or Markdown file (.md).`
        );
        return;
      }

      setActiveDoc({
        name: file.name,
        size: file.size,
        pageCount: 1,
        status: 'parsing',
      });

      try {
        await globalLiteParseService.init();
        const parseResult = await globalLiteParseService.parseFile(file);

        const docId = `doc_${Date.now()}`;
        const chunks: StoredChunk[] = parseResult.pages.map((p, idx) => ({
          id: `${docId}_p${p.pageNumber}_${idx}`,
          docId,
          pageNumber: p.pageNumber,
          text: p.text,
        }));

        const newBM25 = new BM25Index();
        newBM25.buildIndex(chunks.map((c) => ({ id: c.id, text: c.text })));
        bm25Ref.current = newBM25;
        chunksRef.current = chunks;

        const storedDoc: StoredDocument = {
          id: docId,
          name: file.name,
          size: file.size,
          pageCount: parseResult.pages.length,
          createdAt: Date.now(),
        };

        await globalIDBStorage.saveDocument(storedDoc, chunks, newBM25.exportData());

        setActiveDoc({
          name: file.name,
          size: file.size,
          pageCount: parseResult.pages.length,
          status: 'indexed',
        });

        onDocumentIndexed?.();
      } catch (err: any) {
        console.error('File parsing failed:', err);
        setActiveDoc({
          name: file.name,
          size: file.size,
          pageCount: 0,
          status: 'error',
        });
        onError?.(
          'Parsing Failed',
          `Could not parse "${file.name}": ${err?.message || 'Unknown error'}`
        );
      }
    },
    [onError, onDocumentIndexed]
  );

  const handleSearchDocument = useCallback(
    async (query: string): Promise<DocumentSearchResult[]> => {
      if (chunksRef.current.length === 0) {
        try {
          const storedChunks = await globalIDBStorage.getChunks();
          const storedIndex = await globalIDBStorage.getBM25Index();
          if (storedChunks && storedChunks.length > 0) {
            chunksRef.current = storedChunks;
            if (storedIndex) {
              bm25Ref.current.loadData(storedIndex);
            } else {
              bm25Ref.current.buildIndex(storedChunks.map((c) => ({ id: c.id, text: c.text })));
            }
          }
        } catch (err) {
          console.warn('Error reading stored chunks from IDB:', err);
        }
      }

      if (chunksRef.current.length === 0) {
        return [];
      }

      const sanitizedQuery = removeStopWords(query) || query;
      const chunkMap = new Map(chunksRef.current.map((c) => [c.id, c]));
      const ranked = bm25Ref.current.search(sanitizedQuery, 3);

      if (ranked.length > 0) {
        return ranked.slice(0, 3).map((r) => {
          const chunk = chunkMap.get(r.chunkId);
          return {
            pageNumber: chunk?.pageNumber || 1,
            text: chunk?.text || '',
            score: Number(r.score.toFixed(4)),
          };
        });
      }

      return chunksRef.current.slice(0, 3).map((chunk) => ({
        pageNumber: chunk.pageNumber,
        text: chunk.text,
        score: 0.1,
      }));
    },
    []
  );

  const handleCleanDocument = useCallback(async (): Promise<void> => {
    try {
      await globalIDBStorage.clearDocuments();
      bm25Ref.current.clear();
      chunksRef.current = [];
      setActiveDoc(null);
    } catch (err) {
      console.warn('Error clearing document store:', err);
    }
  }, []);

  return {
    activeDoc,
    setActiveDoc,
    bm25Ref,
    chunksRef,
    handleFileSelect,
    handleSearchDocument,
    handleCleanDocument,
  };
}
