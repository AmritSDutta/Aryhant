export interface RawSearchResult {
  title: string;
  snippet: string;
  url: string;
}

const DDG_HTML_ENDPOINT = 'https://html.duckduckgo.com/html/';
const DDG_USER_AGENT =
  'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/124.0 Safari/537.36';

const DDG_AD_REDIRECT = /duckduckgo\.com\/y\.js/i;
const DDG_RESULT_BLOCK = /class="[^"]*\bresult\b[^"]*"/i;
const DDG_RESULT_ANCHOR = /<a\b([^>]*class="[^"]*result__a[^"]*"[^>]*)>([\s\S]*?)<\/a>/i;
const DDG_RESULT_SNIPPET = /<a\b[^>]*class="[^"]*result__snippet[^"]*"[^>]*>([\s\S]*?)<\/a>/i;
const HTTP_URL = /^https?:\/\//i;

function stripTags(input: string): string {
  return input.replace(/<[^>]+>/g, '');
}

function codePoint(value: number): string | null {
  if (!Number.isFinite(value) || value < 0 || value > 0x10ffff) return null;
  try {
    return String.fromCodePoint(value);
  } catch {
    return null;
  }
}

function decodeEntities(input: string): string {
  return input
    .replace(/&lt;/g, '<')
    .replace(/&gt;/g, '>')
    .replace(/&quot;/g, '"')
    .replace(/&#x27;/g, "'")
    .replace(/&#39;/g, "'")
    .replace(/&apos;/g, "'")
    .replace(/&nbsp;/g, ' ')
    .replace(/&hellip;/g, '…')
    .replace(/&mdash;/g, '—')
    .replace(/&ndash;/g, '–')
    .replace(/&#x([0-9a-f]+);/gi, (match, hex: string) => codePoint(parseInt(hex, 16)) ?? match)
    .replace(/&#(\d+);/g, (match, dec: string) => codePoint(parseInt(dec, 10)) ?? match)
    .replace(/&amp;/g, '&')
    .replace(/\s+/g, ' ')
    .trim();
}

function clean(input: string): string {
  return decodeEntities(stripTags(input));
}

function extractRealUrl(href: string): string {
  const uddg = href.match(/[?&]uddg=([^&]+)/);
  let candidate: string;
  if (uddg) {
    try {
      candidate = decodeURIComponent(uddg[1]);
    } catch {
      return '';
    }
  } else if (href.startsWith('//')) {
    candidate = `https:${href}`;
  } else {
    candidate = href;
  }
  return HTTP_URL.test(candidate) ? candidate : '';
}

export function parseDdgHtml(html: string, limit = 5): RawSearchResult[] {
  const results: RawSearchResult[] = [];
  if (!html || limit <= 0) return results;

  const blocks = html.split(DDG_RESULT_BLOCK).slice(1);

  for (const block of blocks) {
    if (results.length >= limit) break;

    const anchor = block.match(DDG_RESULT_ANCHOR);
    if (!anchor) continue;

    const href = anchor[1].match(/href="([^"]+)"/i);
    if (!href) continue;

    const rawHref = decodeEntities(href[1]);
    if (DDG_AD_REDIRECT.test(rawHref)) continue;

    const url = extractRealUrl(rawHref);
    if (!url) continue;

    const snippet = block.match(DDG_RESULT_SNIPPET);
    results.push({
      title: clean(anchor[2]) || url,
      snippet: snippet ? clean(snippet[1]) : '',
      url,
    });
  }

  return results;
}

function isChallengePage(html: string): boolean {
  if (!html.trim()) return true;
  if (DDG_RESULT_BLOCK.test(html)) return false;
  return /anomaly|unfortunately,?\s*bots|are you a robot|too many requests|challenge-platform|cf-challenge/i.test(
    html
  );
}

export async function searchDuckDuckGo(query: string, limit = 5): Promise<RawSearchResult[]> {
  const trimmed = query.trim();
  if (!trimmed) return [];

  const url = `${DDG_HTML_ENDPOINT}?q=${encodeURIComponent(trimmed)}`;
  const response = await fetch(url, {
    headers: {
      'User-Agent': DDG_USER_AGENT,
      Accept: 'text/html',
      Referer: 'https://html.duckduckgo.com/',
      'Accept-Language': 'en-US,en;q=0.9',
    },
  });

  if (!response.ok) {
    throw new Error(`DuckDuckGo responded with status ${response.status}`);
  }

  const html = await response.text();

  if (isChallengePage(html)) {
    throw new Error('DuckDuckGo returned a bot-challenge page');
  }

  return parseDdgHtml(html, limit);
}
