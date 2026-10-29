export interface TavilySearchResult {
  title: string;
  snippet: string;
  url: string;
  score?: number;
}

const TAVILY_ENDPOINT = 'https://api.tavily.com/search';

export async function searchTavilyKeyless(query: string, limit = 5): Promise<TavilySearchResult[]> {
  const trimmed = query.trim();
  if (!trimmed) return [];

  const response = await fetch(TAVILY_ENDPOINT, {
    method: 'POST',
    headers: {
      'Content-Type': 'application/json',
      'X-Tavily-Access-Mode': 'keyless',
    },
    body: JSON.stringify({
      query: trimmed,
      max_results: Math.max(1, Math.min(limit, 10)),
    }),
  });

  if (!response.ok) {
    throw new Error(`Tavily search responded with status ${response.status}`);
  }

  const data = (await response.json()) as { results?: Array<{ title?: string; content?: string; url: string; score?: number }> };
  if (!Array.isArray(data.results)) {
    return [];
  }

  return data.results.map((r) => ({
    title: (r.title || r.url || '').trim(),
    snippet: (r.content || '').trim(),
    url: r.url,
    score: r.score,
  }));
}
