export interface BM25Doc {
  id: string;
  tokens: string[];
}

export interface BM25Posting {
  chunkId: string;
  tf: number;
}

export interface BM25IndexData {
  id: string;
  docCount: number;
  avgDocLength: number;
  docLengths: Record<string, number>;
  invertedIndex: Record<string, BM25Posting[]>;
}

export const STOP_WORDS = new Set([
  'a', 'about', 'above', 'after', 'again', 'against', 'all', 'am', 'an', 'and',
  'any', 'are', 'as', 'at', 'be', 'because', 'been', 'before', 'being', 'below',
  'between', 'both', 'but', 'by', 'can', 'did', 'do', 'does', 'doing', 'down',
  'during', 'each', 'few', 'for', 'from', 'further', 'had', 'has', 'have',
  'having', 'he', 'her', 'here', 'hers', 'herself', 'him', 'himself', 'his',
  'how', 'i', 'if', 'in', 'into', 'is', 'it', 'its', 'itself', 'just', 'me',
  'more', 'most', 'my', 'myself', 'no', 'nor', 'not', 'now', 'of', 'off', 'on',
  'once', 'only', 'or', 'other', 'our', 'ours', 'ourselves', 'out', 'over', 'own',
  'same', 'she', 'should', 'so', 'some', 'such', 'than', 'that', 'the', 'their',
  'theirs', 'them', 'themselves', 'then', 'there', 'these', 'they', 'this',
  'those', 'through', 'to', 'too', 'under', 'until', 'up', 'very', 'was', 'we',
  'were', 'what', 'when', 'where', 'which', 'while', 'who', 'whom', 'why',
  'will', 'with', 'you', 'your', 'yours', 'yourself', 'yourselves',
  // Domain conversational stopwords
  'document', 'documents', 'uploaded', 'file', 'files', 'tell', 'show', 'find',
  'give', 'list', 'please', 'content', 'search',
]);

export function tokenize(text: string): string[] {
  return text
    .toLowerCase()
    .replace(/[^\p{L}\p{N}\s]/gu, ' ')
    .split(/\s+/)
    .filter((t) => t.length > 1);
}

export function removeStopWords(query: string): string {
  const tokens = tokenize(query);
  const filtered = tokens.filter((t) => !STOP_WORDS.has(t));
  return filtered.join(' ');
}

export class BM25Index {
  private k1: number;
  private b: number;
  private docCount: number = 0;
  private avgDocLength: number = 0;
  private docLengths: Map<string, number> = new Map();
  private invertedIndex: Map<string, BM25Posting[]> = new Map();

  constructor(k1: number = 1.5, b: number = 0.75) {
    this.k1 = k1;
    this.b = b;
  }

  public getDocCount(): number {
    return this.docCount;
  }

  public buildIndex(docs: Array<{ id: string; text: string }>): void {
    this.clear();
    this.docCount = docs.length;
    if (this.docCount === 0) return;

    let totalLength = 0;

    for (const doc of docs) {
      const tokens = tokenize(doc.text);
      const docLen = tokens.length;
      this.docLengths.set(doc.id, docLen);
      totalLength += docLen;

      const termCounts = new Map<string, number>();
      for (const token of tokens) {
        termCounts.set(token, (termCounts.get(token) || 0) + 1);
      }

      for (const [term, count] of termCounts.entries()) {
        const postings = this.invertedIndex.get(term) || [];
        postings.push({ chunkId: doc.id, tf: count });
        this.invertedIndex.set(term, postings);
      }
    }

    this.avgDocLength = totalLength / this.docCount;
  }

  public search(query: string, topK: number = 3): Array<{ chunkId: string; score: number }> {
    if (this.docCount === 0) return [];

    const allQueryTokens = tokenize(query);
    if (allQueryTokens.length === 0) return [];

    // Prioritize non-stop words; if all were stop words, fallback to all tokens
    const filteredTokens = allQueryTokens.filter((t) => !STOP_WORDS.has(t));
    const searchTokens = filteredTokens.length > 0 ? filteredTokens : allQueryTokens;

    const scores = new Map<string, number>();

    for (const token of searchTokens) {
      const postings = this.invertedIndex.get(token);
      if (!postings || postings.length === 0) continue;

      const df = postings.length;
      // Standard Robertson-Spärck Jones IDF with floor to ensure positive scores
      const idf = Math.max(0.1, Math.log(1 + (this.docCount - df + 0.5) / (df + 0.5)));

      for (const posting of postings) {
        const docLen = this.docLengths.get(posting.chunkId) || this.avgDocLength;
        const normLen = 1 - this.b + this.b * (docLen / (this.avgDocLength || 1));
        const score = (idf * (posting.tf * (this.k1 + 1))) / (posting.tf + this.k1 * normLen);

        scores.set(posting.chunkId, (scores.get(posting.chunkId) || 0) + score);
      }
    }

    // Substring / broad match fallback if exact tokens didn't hit inverted index
    if (scores.size === 0) {
      for (const token of searchTokens) {
        for (const [indexedTerm, postings] of this.invertedIndex.entries()) {
          if (indexedTerm.includes(token) || token.includes(indexedTerm)) {
            for (const posting of postings) {
              scores.set(posting.chunkId, (scores.get(posting.chunkId) || 0) + 0.5 * posting.tf);
            }
          }
        }
      }
    }

    return Array.from(scores.entries())
      .map(([chunkId, score]) => ({ chunkId, score }))
      .sort((a, b) => b.score - a.score)
      .slice(0, topK);
  }

  public exportData(): BM25IndexData {
    const docLengthsObj: Record<string, number> = {};
    for (const [k, v] of this.docLengths.entries()) {
      docLengthsObj[k] = v;
    }

    const invertedIndexObj: Record<string, BM25Posting[]> = {};
    for (const [k, v] of this.invertedIndex.entries()) {
      invertedIndexObj[k] = v;
    }

    return {
      id: 'default_index',
      docCount: this.docCount,
      avgDocLength: this.avgDocLength,
      docLengths: docLengthsObj,
      invertedIndex: invertedIndexObj,
    };
  }

  public loadData(data: BM25IndexData): void {
    this.docCount = data.docCount;
    this.avgDocLength = data.avgDocLength;
    this.docLengths = new Map(Object.entries(data.docLengths));
    this.invertedIndex = new Map(Object.entries(data.invertedIndex));
  }

  public clear(): void {
    this.docCount = 0;
    this.avgDocLength = 0;
    this.docLengths.clear();
    this.invertedIndex.clear();
  }
}
