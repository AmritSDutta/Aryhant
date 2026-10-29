import { WebMCPTool } from './types';
import { AGENT_TOOL_GUIDE } from './agentGuide';

export interface SearchToolOutcome<T> {
  results: T[];
  fetchedAt?: string;
  source?: string;
  unavailable?: boolean;
  error?: string;
}

export interface ToolContext {
  getMessages: () => Array<{ sender: 'user' | 'assistant' | 'agent'; text: string; timestamp?: string | number }>;
  postMessage: (text: string) => void;
  searchDocument?: (query: string) => Promise<Array<{ pageNumber: number; text: string; score: number }>>;
  cleanDocument?: () => Promise<void>;
  searchWeb?: (query: string) => Promise<SearchToolOutcome<{ title: string; snippet: string; url: string }>>;
  calculate?: (expression: string) => number;
  getReferenceUrls?: () => string[];
  exportPdf?: () => { success: boolean; error?: string } | void;
}

export const TOOL_DEFINITIONS: WebMCPTool[] = [
  {
    name: 'get_tool_usage_prompt',
    description:
      'Returns the official Aryhant agent operating guide: how to use every other tool correctly (document retrieval, chat, web search, reference URLs, and conventions). Call this FIRST before using any other tool.',
    readOnlyHint: true,
    inputSchema: {
      type: 'object',
      properties: {},
    },
  },
  {
    name: 'get_reference_url',
    description:
      'Returns a comma-separated list of reference and resource URLs stored in the browser session. Visiting LLMs use these URLs to fetch or cite external documentation and context.',
    readOnlyHint: true,
    inputSchema: {
      type: 'object',
      properties: {},
    },
  },
  {
    name: 'get_current_time',
    description:
      "Returns the user's current local date, weekday, time, time zone, and ISO timestamp. Useful for scheduling, planning, time-sensitive queries, and calendar context.",
    readOnlyHint: true,
    inputSchema: {
      type: 'object',
      properties: {},
    },
  },
  {
    name: 'chat_post',
    description: 'Posts a response, answer, or status message to the chat dialogue stream on behalf of the AI assistant.',
    inputSchema: {
      type: 'object',
      properties: {
        text: {
          type: 'string',
          description: 'The textual message or markdown content to display in the chat area.',
        },
      },
      required: ['text'],
    },
  },
  {
    name: 'get_chat_history',
    description: 'Returns the list of recent messages in the dialogue stream, with user prompts prefixed by "user:" and assistant messages by "agent:".',
    inputSchema: {
      type: 'object',
      properties: {},
    },
  },
  {
    name: 'search_document',
    description:
      'Searches uploaded document chunks in in-browser IndexedDB using a lexical BM25 index. Returns top 3 relevant pages. For best results, use targeted keywords or topic entities (e.g. "fractions", "geometry", "photosynthesis") rather than conversational questions.',
    inputSchema: {
      type: 'object',
      properties: {
        query: {
          type: 'string',
          description: 'The search keywords or topic terms to query. Provide specific keywords rather than conversational sentences.',
        },
      },
      required: ['query'],
    },
  },
  {
    name: 'clean_document',
    description: 'Deletes all stored document chunks and BM25 index from IndexedDB, resetting the file upload box.',
    inputSchema: {
      type: 'object',
      properties: {},
    },
  },
  {
    name: 'search_web',
    description:
      'Searches the web using Tavily AI keyless search (primary) with automatic DuckDuckGo fallback. Returns top ranked web results with title, snippet, URL, source, and fetchedAt timestamp.',
    inputSchema: {
      type: 'object',
      properties: {
        query: {
          type: 'string',
          description: 'The search query to look up on the web.',
        },
      },
      required: ['query'],
    },
  },
  {
    name: 'calculate',
    description: 'Evaluates decimal and scientific math expressions accurately.',
    inputSchema: {
      type: 'object',
      properties: {
        expression: {
          type: 'string',
          description: 'The decimal math expression to evaluate (e.g., "12.5 * 4.2 + 3.1", "sqrt(144)").',
        },
      },
      required: ['expression'],
    },
  },
  {
    name: 'export_pdf',
    description: 'Generates and downloads a publication-quality session PDF report containing the dialogue transcript and notes.',
    inputSchema: {
      type: 'object',
      properties: {},
    },
  },
];

export async function executeToolCall(
  name: string,
  args: Record<string, unknown> | undefined,
  context: ToolContext
): Promise<unknown> {
  switch (name) {
    case 'get_tool_usage_prompt': {
      return AGENT_TOOL_GUIDE;
    }

    case 'get_reference_url': {
      const urls = context.getReferenceUrls ? context.getReferenceUrls() : [];
      return urls.length > 0 ? urls.join(', ') : 'No reference URLs stored';
    }

    case 'get_current_time': {
      const now = new Date();
      const timeZone = Intl.DateTimeFormat().resolvedOptions().timeZone || 'UTC';
      const formatted = new Intl.DateTimeFormat('en-US', {
        dateStyle: 'full',
        timeStyle: 'long',
        timeZone,
      }).format(now);
      return {
        iso: now.toISOString(),
        formatted,
        timeZone,
        epochMs: now.getTime(),
      };
    }

    case 'get_chat_history': {
      const msgs = context.getMessages();
      return {
        messages: msgs.map((m) => ({
          formatted: `${m.sender === 'user' ? 'user:' : 'agent:'} ${m.text}`,
          sender: m.sender,
          text: m.text,
          timestamp: m.timestamp,
        })),
      };
    }

    case 'chat_post': {
      const text = String(args?.text || '');
      if (!text) throw new Error('Missing "text" argument');
      context.postMessage(text);
      return { success: true, message: 'Message posted to chat' };
    }

    case 'search_document': {
      const query = String(args?.query || '');
      if (!context.searchDocument) {
        return { results: [], message: 'Document search service not available yet' };
      }
      const results = await context.searchDocument(query);
      return { results };
    }

    case 'clean_document': {
      if (context.cleanDocument) {
        await context.cleanDocument();
      }
      return { success: true, message: 'Document storage cleaned' };
    }

    case 'search_web': {
      const query = String(args?.query || '');
      if (!context.searchWeb) {
        return { results: [], unavailable: true, error: 'Web search not available' };
      }
      return await context.searchWeb(query);
    }

    case 'calculate': {
      const expression = String(args?.expression || '');
      if (!context.calculate) {
        throw new Error('Calculator service not available');
      }
      const result = context.calculate(expression);
      return { expression, result };
    }

    case 'export_pdf': {
      if (context.exportPdf) {
        const res = context.exportPdf();
        if (res && !res.success) {
          throw new Error(res.error || 'Cannot export an empty session.');
        }
        return { success: true, message: 'PDF report generated and download initiated.' };
      }
      throw new Error('PDF export capability not available');
    }

    default:
      throw new Error(`Unknown tool: ${name}`);
  }
}

export const executeTool = executeToolCall;
