import { appConfig } from './config';
import { ChatRequest, ChatResponse, HealthResponse } from './types';

function getApiUrl(path: string): string {
  const base = appConfig.apiBaseUrl ? appConfig.apiBaseUrl.replace(/\/+$/, '') : '';
  const cleanPath = path.startsWith('/') ? path : `/${path}`;
  return `${base}${cleanPath}`;
}

export async function fetchHealth(token?: string): Promise<HealthResponse> {
  const headers: Record<string, string> = {
    Accept: 'application/json',
  };

  if (token) {
    headers['Authorization'] = `Bearer ${token}`;
  }

  const res = await fetch(getApiUrl('/api/health'), {
    method: 'GET',
    headers,
  });

  if (!res.ok) {
    throw new Error(`Health check failed with HTTP ${res.status}`);
  }

  return res.json();
}

export interface SendMessageOptions {
  message: string;
  sessionId: string;
  userId?: string;
  token?: string;
}

export class ApiError extends Error {
  status: number;
  detail: string;

  constructor(status: number, detail: string) {
    super(detail);
    this.name = 'ApiError';
    this.status = status;
    this.detail = detail;
  }
}

export async function sendChatMessage(options: SendMessageOptions): Promise<ChatResponse> {
  const headers: Record<string, string> = {
    'Content-Type': 'application/json',
    Accept: 'application/json',
  };

  if (options.token) {
    headers['Authorization'] = `Bearer ${options.token}`;
  }

  const payload: ChatRequest = {
    message: options.message,
    session_id: options.sessionId,
    user_id: options.userId || 'web-user',
    channel: 'web',
  };

  const res = await fetch(getApiUrl('/api/chat'), {
    method: 'POST',
    headers,
    body: JSON.stringify(payload),
  });

  if (!res.ok) {
    let detail = `Request failed (${res.status})`;
    try {
      const errJson = await res.json();
      if (errJson && errJson.detail) {
        detail = typeof errJson.detail === 'string' ? errJson.detail : JSON.stringify(errJson.detail);
      }
    } catch {
      // Non-JSON response
    }

    if (res.status === 429) {
      detail = 'Rate limit exceeded (20 requests/minute). Please wait a moment before sending another message.';
    } else if (res.status === 401) {
      detail = 'Authentication required or invalid session token. Please log in.';
    } else if (res.status === 403) {
      detail = 'Access denied. Your email account is not authorized to access Aryhant.';
    }

    throw new ApiError(res.status, detail);
  }

  return res.json();
}
