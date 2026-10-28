# Aryhant Web UI

A modern, responsive React + TypeScript companion web interface for Aryhant (ICSE Grade 5 Pedagogical Companion), deployable as a static SPA to Cloudflare Pages.

---

## Highlights & Features

- **ICSE Grade 5 Companion**: Multi-turn dialogue with Aryhant for revision, syllabus help, plain-text math, and interactive practice questions.
- **Typography & Branding**:
  - **Font**: Set in elegant Google Font **Lora** across UI text and chat messages.
  - **Header Icon**: Branded with `Aryhant.jpg`.
  - **Tab Favicon**: Custom `icon.ico` tab icon.
- **Vite Dev Proxy**: Built-in dev proxy (`http://localhost:5173/api` &rarr; `http://127.0.0.1:8000`) for seamless, zero-config local development without CORS issues.
- **Pure Auth0 Universal Login / PKCE**:
  - Integrated via `@auth0/auth0-react`.
  - Configured with `useRefreshTokens={true}` and `cacheLocation="localstorage"` to completely avoid third-party cookie restrictions on `localhost`.
  - Seamless fallback with a 2-second timeout and notice tooltip if Auth0 tenant is unconfigured or slow.
- **Rate Limit & Safety Handling**:
  - Supports the backend's **20 requests/minute** rate limit with a clean cooldown alert banner.
  - Surfaces input validation rejections (`HTTP 400`) gracefully.
- **Session Continuity**:
  - Generates and persists a stable `session_id` in `sessionStorage` per tab.
  - "New Session" button allows students to start a fresh conversation at any time.

---

## Directory Structure

```text
ui/
├── public/                 # Static assets (Aryhant.jpg, icon.ico)
├── src/
│   ├── components/         # UI components
│   │   ├── ChatPanel.tsx   # Chat container, message flow, error banners
│   │   ├── Header.tsx      # App banner, status pill, Auth0 login/logout
│   │   ├── MessageInput.tsx# Multi-line textarea & session reset
│   │   ├── MessageItem.tsx # Message bubbles with timestamps & model tags
│   │   ├── MessageList.tsx # Chat stream & starter suggestion cards
│   │   └── StatusPill.tsx  # Live 30s polling backend health indicator
│   ├── lib/
│   │   ├── api.ts          # Fetch wrappers for /api/health and /api/chat
│   │   ├── config.ts       # Vite import.meta.env reader
│   │   └── types.ts        # TypeScript data contracts
│   ├── App.tsx             # Root app component
│   ├── index.css           # Modern CSS tokens & styling
│   ├── main.tsx            # Entry point with Auth0Provider
│   └── vite-env.d.ts       # Vite client and env typings
├── index.html              # HTML root with Lora font and favicon links
├── package.json            # Project manifest & scripts
├── tsconfig.json           # Strict TypeScript configuration
└── vite.config.ts          # Vite build & proxy settings
```

---

## Local Development

### 1. Install Dependencies
```powershell
cd ui
npm.cmd install    # On Windows (or 'npm install' on Linux/macOS)
```

### 2. Configure Environment Variables (Optional)
Auth0 and API Base URL can be configured using standard Vite environment variables:

| Variable | Description | Default |
| :--- | :--- | :--- |
| `VITE_AUTH0_DOMAIN` | Your Auth0 tenant domain (e.g. `your-tenant.us.auth0.com`) | `""` (runs unauthenticated) |
| `VITE_AUTH0_CLIENT_ID` | Your Auth0 Single Page App Client ID | `""` |
| `VITE_AUTH0_AUDIENCE` | API Audience identifier matching backend `AUTH0_AUDIENCE` | `""` |
| `VITE_API_BASE_URL` | Backend URL for production | `""` (uses relative `/api`) |

*Note*: If `VITE_AUTH0_DOMAIN` and `VITE_AUTH0_CLIENT_ID` are left empty, the application runs in open / demo mode.

### 3. Run Development Server
Ensure the FastAPI backend is running on `http://127.0.0.1:8000`:
```powershell
infisical run -- python -m uvicorn chat_agent.app:app --host 127.0.0.1 --port 8000
```

Start the Vite frontend on `http://localhost:5173`:
```powershell
infisical run -- npm run dev
# On Windows PowerShell:
infisical run -- npm.cmd run dev
```

---

## Production Build & Cloudflare Pages Deployment

### 1. Build Static Bundle
```powershell
npm.cmd run build
```
This performs TypeScript type-checking and builds the static assets in `ui/dist/`.

### 2. Cloudflare Pages Configuration
Connect your repository in the Cloudflare Pages dashboard:
- **Framework Preset**: `Vite`
- **Root Directory**: `ui`
- **Build Command**: `npm run build`
- **Build Output Directory**: `dist`
- **Environment Variables**: Add `VITE_AUTH0_DOMAIN`, `VITE_AUTH0_CLIENT_ID`, `VITE_AUTH0_AUDIENCE`, and `VITE_API_BASE_URL` (pointing to your deployed FastAPI backend URL, e.g. `https://experiments.amritai.org`).
