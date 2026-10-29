export interface WebMCPToolParameter {
  type: string;
  description?: string;
  enum?: string[];
  properties?: Record<string, unknown>;
  required?: string[];
  items?: unknown;
}

export interface WebMCPTool {
  name: string;
  description: string;
  readOnlyHint?: boolean;
  inputSchema: {
    type: 'object';
    properties: Record<string, WebMCPToolParameter>;
    required?: string[];
  };
}

export interface JsonRpcRequest {
  jsonrpc: '2.0';
  id?: string | number | null;
  method: string;
  params?: Record<string, unknown>;
}

export interface JsonRpcResponse {
  jsonrpc: '2.0';
  id?: string | number | null;
  result?: unknown;
  error?: {
    code: number;
    message: string;
    data?: unknown;
  };
}
