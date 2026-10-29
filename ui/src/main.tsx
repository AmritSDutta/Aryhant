import React from 'react';
import ReactDOM from 'react-dom/client';
import { Auth0Provider } from '@auth0/auth0-react';
import App from './App';
import { appConfig } from './lib/config';
import './index.css';

// Disable right click (context menu) and developer inspection shortcuts (F12, Ctrl+Shift+I/J/C, Ctrl+U)
if (typeof window !== 'undefined') {
  window.addEventListener('contextmenu', (e: MouseEvent) => {
    e.preventDefault();
  });

  window.addEventListener('keydown', (e: KeyboardEvent) => {
    // F12
    if (e.key === 'F12' || e.keyCode === 123) {
      e.preventDefault();
      return;
    }
    // Ctrl+Shift+I / J / C (or Cmd+Opt+I / J / C on macOS)
    const isModifier = e.ctrlKey || e.metaKey;
    const isShiftOrAlt = e.shiftKey || e.altKey;
    const inspectKeys = ['i', 'j', 'c'];
    if (isModifier && isShiftOrAlt && inspectKeys.includes(e.key.toLowerCase())) {
      e.preventDefault();
      return;
    }
    // Ctrl+U (View Source)
    if (isModifier && e.key.toLowerCase() === 'u') {
      e.preventDefault();
      return;
    }
  });
}

const rootElement = document.getElementById('root');
if (!rootElement) {
  throw new Error('Root element not found');
}

const root = ReactDOM.createRoot(rootElement);

if (appConfig.isAuthEnabled) {
  root.render(
    <React.StrictMode>
      <Auth0Provider
        domain={appConfig.auth0Domain}
        clientId={appConfig.auth0ClientId}
        authorizationParams={{
          redirect_uri: window.location.origin,
          audience: appConfig.auth0Audience || undefined,
          scope: 'openid profile email',
        }}
        useRefreshTokens={true}
        cacheLocation="localstorage"
      >
        <App />
      </Auth0Provider>
    </React.StrictMode>
  );
} else {
  root.render(
    <React.StrictMode>
      <App />
    </React.StrictMode>
  );
}
