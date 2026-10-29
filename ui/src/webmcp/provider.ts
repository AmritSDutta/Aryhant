import { WebMCPTool } from './types';
import { TOOL_DEFINITIONS, ToolContext, executeToolCall } from './tools';

export class WebMCPProvider {
  private context: ToolContext;
  private messageListener: ((event: MessageEvent) => void) | null = null;
  private registeredToolControllers: AbortController[] = [];

  constructor(context: ToolContext) {
    this.context = context;
  }

  public updateContext(context: ToolContext): void {
    this.context = context;
  }

  public listTools(): WebMCPTool[] {
    return [...TOOL_DEFINITIONS];
  }

  public async callTool(name: string, args?: Record<string, unknown>): Promise<unknown> {
    return await executeToolCall(name, args, this.context);
  }

  public register(): void {
    const globalWin = typeof window !== 'undefined' ? (window as unknown as Record<string, unknown>) : null;
    if (!globalWin) return;

    const tools = this.listTools();

    const formattedTools = tools.map((t) => ({
      name: t.name,
      description: t.description,
      inputSchema: t.inputSchema,
      readOnlyHint: t.readOnlyHint,
      execute: async (args: Record<string, unknown>) => {
        const res = await this.callTool(t.name, args);
        return {
          content: [
            {
              type: 'text',
              text: typeof res === 'string' ? res : JSON.stringify(res),
            },
          ],
        };
      },
    }));

    // =========================================================================
    // Tier 1: Imperative JavaScript API Surfaces
    // =========================================================================

    // 1a. Native/Official Chrome WebMCP API: document.modelContext
    if (typeof document !== 'undefined') {
      const doc = document as any;
      if (!doc.modelContext) {
        doc.modelContext = {
          tools: formattedTools,
          getTools: async () => formattedTools,
          listTools: async () => formattedTools,
          registerTool: (tool: any) => {
            formattedTools.push(tool);
            return { unregister: () => {} };
          },
          executeTool: async (name: string, args: Record<string, unknown>) => {
            return await this.callTool(name, args);
          },
        };
      } else if (typeof doc.modelContext.registerTool === 'function') {
        for (const tool of formattedTools) {
          try {
            const controller = new AbortController();
            this.registeredToolControllers.push(controller);
            const registration = doc.modelContext.registerTool(tool, { signal: controller.signal });
            if (registration && typeof registration.then === 'function') {
              Promise.resolve(registration).catch(() => {
                /* registration aborted during unregister — benign */
              });
            }
          } catch (e) {
            console.warn(`Could not natively register tool ${tool.name}:`, e);
          }
        }
      }
    }

    // 1b. Official testing / earlier draft API: navigator.modelContext & navigator.modelContextTesting
    if (typeof navigator !== 'undefined') {
      const nav = navigator as any;
      const modelContextObj = {
        tools: formattedTools,
        getTools: async () => formattedTools,
        listTools: async () => formattedTools,
        registerTool: (tool: any) => {
          formattedTools.push(tool);
        },
        executeTool: async (name: string, args: Record<string, unknown>) => {
          return await this.callTool(name, args);
        },
        callTool: (name: string, args?: Record<string, unknown>) => this.callTool(name, args),
      };

      try {
        if (!nav.modelContext) {
          Object.defineProperty(navigator, 'modelContext', {
            value: modelContextObj,
            configurable: true,
            writable: true,
          });
        }
      } catch {
        // Readonly fallback
      }

      try {
        if (!nav.modelContextTesting) {
          Object.defineProperty(navigator, 'modelContextTesting', {
            value: modelContextObj,
            configurable: true,
            writable: true,
          });
        }
      } catch {
        // Readonly fallback
      }
    }

    // 1c. window.webmcp and window.modelContext standard bridge
    globalWin.webmcp = {
      listTools: () => this.listTools(),
      getTools: () => formattedTools,
      callTool: (name: string, args?: Record<string, unknown>) => this.callTool(name, args),
      executeTool: (name: string, args?: Record<string, unknown>) => this.callTool(name, args),
      tools: formattedTools,
    };
    globalWin.modelContext = (typeof document !== 'undefined' && (document as any).modelContext) || globalWin.webmcp;

    // =========================================================================
    // Tier 2: Declarative DOM Representation for WebMCP Inspector Extensions
    // =========================================================================
    this.injectDeclarativeToolForms(tools);

    // =========================================================================
    // Tier 3: postMessage JSON-RPC 2.0 Event Bridge for Manifest V3 Isolated Worlds
    // =========================================================================
    this.messageListener = async (event: MessageEvent) => {
      const data = event.data as any;
      if (!data || typeof data !== 'object') return;

      if (
        data.type === 'WEBMCP_GET_TOOLS' ||
        data.type === 'MODEL_CONTEXT_GET_TOOLS' ||
        data.action === 'getTools' ||
        data.method === 'tools/list' ||
        data.method === 'listTools' ||
        data.method === 'getTools'
      ) {
        const response = {
          jsonrpc: '2.0',
          id: data.id ?? null,
          type: 'WEBMCP_TOOLS_RESPONSE',
          tools: formattedTools,
          result: { tools: formattedTools },
        };
        this.reply(event, response);
        return;
      }

      if (
        data.type === 'WEBMCP_EXECUTE_TOOL' ||
        data.type === 'MODEL_CONTEXT_CALL_TOOL' ||
        data.action === 'executeTool' ||
        data.method === 'tools/call' ||
        data.method === 'callTool' ||
        data.method === 'executeTool'
      ) {
        const toolName = (data.params?.name as string) || (data.params?.tool as string) || data.name || data.tool;
        const args = (data.params?.arguments as Record<string, unknown>) || data.params?.args || data.args || {};
        try {
          const result = await this.callTool(toolName, args);
          const response = {
            jsonrpc: '2.0',
            id: data.id ?? null,
            type: 'WEBMCP_TOOL_RESULT',
            result: {
              content: [
                {
                  type: 'text',
                  text: typeof result === 'string' ? result : JSON.stringify(result),
                },
              ],
              raw: result,
            },
          };
          this.reply(event, response);
        } catch (err: unknown) {
          const message = err instanceof Error ? err.message : String(err);
          const response = {
            jsonrpc: '2.0',
            id: data.id ?? null,
            type: 'WEBMCP_TOOL_ERROR',
            error: {
              code: -32603,
              message,
            },
          };
          this.reply(event, response);
        }
      }
    };

    window.addEventListener('message', this.messageListener);

    // Custom Events for extensions & DOM listeners
    window.dispatchEvent(
      new CustomEvent('webmcp:ready', {
        detail: { tools: formattedTools },
      })
    );
    window.dispatchEvent(
      new CustomEvent('modelcontext:ready', {
        detail: { tools: formattedTools },
      })
    );
  }

  public unregister(): void {
    if (this.messageListener && typeof window !== 'undefined') {
      window.removeEventListener('message', this.messageListener);
      this.messageListener = null;
    }
    for (const controller of this.registeredToolControllers) {
      controller.abort('unregister');
    }
    this.registeredToolControllers = [];

    const container = document.getElementById('webmcp-declarative-container');
    if (container) {
      container.remove();
    }
  }

  private injectDeclarativeToolForms(tools: WebMCPTool[]): void {
    if (typeof document === 'undefined') return;

    let container = document.getElementById('webmcp-declarative-container');
    if (!container) {
      container = document.createElement('div');
      container.id = 'webmcp-declarative-container';
      container.style.display = 'none';
      container.setAttribute('aria-hidden', 'true');
      document.body.appendChild(container);
    }

    container.innerHTML = '';

    for (const tool of tools) {
      const form = document.createElement('form');
      form.setAttribute('toolname', tool.name);
      form.setAttribute('tool-name', tool.name);
      form.setAttribute('tooldescription', tool.description);
      form.setAttribute('tool-description', tool.description);

      const props = (tool.inputSchema as any)?.properties || {};
      for (const [propName, propDef] of Object.entries(props)) {
        const input = document.createElement('input');
        input.name = propName;
        input.setAttribute('toolparamdescription', (propDef as any).description || propName);
        input.setAttribute('tool-param-description', (propDef as any).description || propName);
        form.appendChild(input);
      }

      form.addEventListener('submit', async (e) => {
        e.preventDefault();
        const formData = new FormData(form);
        const args: Record<string, unknown> = {};
        formData.forEach((val, key) => {
          args[key] = val;
        });
        await this.callTool(tool.name, args);
      });

      container.appendChild(form);
    }
  }

  private reply(event: MessageEvent, response: unknown): void {
    if (event.source && typeof (event.source as Window).postMessage === 'function') {
      (event.source as Window).postMessage(response, '*');
    } else if (typeof window !== 'undefined') {
      window.postMessage(response, '*');
    }
  }
}
