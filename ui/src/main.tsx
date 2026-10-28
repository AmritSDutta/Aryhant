import React from 'react';
import ReactDOM from 'react-dom/client';
import { Auth0Provider } from '@auth0/auth0-react';
import App from './App';
import { appConfig } from './lib/config';
import './index.css';

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
