import { defineConfig } from 'vite';
import react from '@vitejs/plugin-react';
import { searchDuckDuckGo } from './src/lib/ddgSearch';
import { searchTavilyKeyless } from './src/lib/tavilySearch';

export default defineConfig({
  plugins: [
    react(),
    {
      name: 'dev-api-endpoints',
      configureServer(server) {
        server.middlewares.use(async (req, res, next) => {
          if (!req.url) return next();

          if (req.url.startsWith('/api/websearch')) {
            const requestUrl = new URL(req.url, 'http://localhost');
            const query = requestUrl.searchParams.get('query') || '';
            const send = (status: number, payload: unknown) => {
              res.statusCode = status;
              res.setHeader('Content-Type', 'application/json');
              res.end(JSON.stringify(payload));
            };

            // 1. Try Keyless Tavily Search first
            try {
              const tavilyResults = await searchTavilyKeyless(query);
              if (tavilyResults && tavilyResults.length > 0) {
                return send(200, {
                  results: tavilyResults,
                  fetchedAt: new Date().toISOString(),
                  source: 'tavily',
                });
              }
            } catch (tavilyErr) {
              console.warn('Tavily search failed or rate-limited in dev, falling back to DuckDuckGo:', tavilyErr);
            }

            // 2. Fallback to DuckDuckGo HTML scraper
            try {
              return send(200, {
                results: await searchDuckDuckGo(query),
                fetchedAt: new Date().toISOString(),
                source: 'duckduckgo',
              });
            } catch (error: any) {
              return send(502, { results: [], unavailable: true, error: String(error?.message || error) });
            }
          }

          next();
        });
      },
    },
  ],
  server: {
    port: 5173,
    proxy: {
      '/api': {
        target: 'http://127.0.0.1:8000',
        changeOrigin: true,
      },
    },
  },
});
