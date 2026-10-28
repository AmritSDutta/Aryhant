export interface ChatRequest {
  message: string;
  user_id?: string;
  session_id?: string;
  channel?: string;
}

export interface ChatResponse {
  reply: string;
  model: string;
  channel: string;
}

export interface HealthResponse {
  status: string;
  version: string;
  ok: boolean;
}

export interface Message {
  id: string;
  sender: 'user' | 'assistant';
  text: string;
  model?: string;
  timestamp: string;
  status?: 'sending' | 'sent' | 'error';
  errorMessage?: string;
}
