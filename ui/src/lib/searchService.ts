import { appConfig } from './config';

export interface WebSearchResult {
  title: string;
  snippet: string;
  url: string;
  fetchedAt: string;
  source: string;
}

export interface SearchOutcome<T> {
  results: T[];
  fetchedAt: string;
  source: string;
  unavailable?: boolean;
  error?: string;
}

async function fetchWithTimeout(url: string, timeoutMs = 20000): Promise<Response> {
  const controller = new AbortController();
  const timer = setTimeout(() => controller.abort(), timeoutMs);
  try {
    return await fetch(url, { signal: controller.signal });
  } finally {
    clearTimeout(timer);
  }
}

export async function searchWeb(query: string): Promise<SearchOutcome<WebSearchResult>> {
  const fetchedAt = new Date().toISOString();
  const trimmed = (query || '').trim();
  if (!trimmed) {
    return { results: [], fetchedAt, source: 'tavily' };
  }

  try {
    const base = appConfig.apiBaseUrl ? appConfig.apiBaseUrl.replace(/\/+$/, '') : '';
    const endpoint = `${base}/api/websearch?query=${encodeURIComponent(trimmed)}`;
    const response = await fetchWithTimeout(endpoint);
    if (!response.ok) {
      throw new Error(`Search endpoint responded with status ${response.status}`);
    }
    const data = (await response.json()) as {
      results?: Array<{ title: string; snippet: string; url: string }>;
      source?: string;
    };
    const source = data.source || 'duckduckgo';
    const results = (data.results || []).map((r) => ({ ...r, fetchedAt, source }));
    return { results: results.slice(0, 5), fetchedAt, source };
  } catch (error: any) {
    console.warn('searchWeb error:', error);
    return {
      results: [],
      fetchedAt,
      source: 'duckduckgo',
      unavailable: true,
      error: String(error?.message || error),
    };
  }
}
