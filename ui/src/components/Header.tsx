import React from 'react';
import { useAuth0 } from '@auth0/auth0-react';
import { LogIn, LogOut } from 'lucide-react';
import { StatusPill } from './StatusPill';
import { appConfig } from '../lib/config';

export const Header: React.FC = () => {
  const auth0 = appConfig.isAuthEnabled ? useAuth0() : null;
  const [authTimeout, setAuthTimeout] = React.useState(false);

  React.useEffect(() => {
    if (appConfig.isAuthEnabled && auth0?.isLoading) {
      const timer = setTimeout(() => setAuthTimeout(true), 2000);
      return () => clearTimeout(timer);
    }
  }, [auth0?.isLoading]);

  React.useEffect(() => {
    if (auth0?.error) {
      console.warn('Auth0 initialization error:', auth0.error);
    }
  }, [auth0?.error]);

  return (
    <header className="app-header">
      <div className="brand-section">
        <img
          src="/Aryhant.jpg"
          alt="Aryhant Icon"
          className="brand-icon-img"
        />
        <div>
          <h1 className="brand-title">Aryhant</h1>
          <p className="brand-subtitle">Family AI Assistant</p>
        </div>
      </div>

      <div className="header-actions">
        <StatusPill />

        {appConfig.isAuthEnabled && auth0 && (
          <>
            {auth0.isLoading && !authTimeout ? (
              <span className="brand-subtitle">Loading auth...</span>
            ) : auth0.isAuthenticated && auth0.user ? (
              <div className="user-badge">
                {auth0.user.picture && (
                  <img
                    src={auth0.user.picture}
                    alt={auth0.user.name || 'User'}
                    className="user-avatar"
                  />
                )}
                <span>{auth0.user.email || auth0.user.name}</span>
                <button
                  className="auth-btn"
                  onClick={() => auth0.logout({ logoutParams: { returnTo: window.location.origin } })}
                  title="Log Out"
                >
                  <LogOut size={14} />
                  <span>Logout</span>
                </button>
              </div>
            ) : (
              <button
                className="auth-btn primary"
                onClick={() => auth0.loginWithRedirect()}
                title={auth0.error ? `Auth0 notice: ${auth0.error.message}` : undefined}
              >
                <LogIn size={14} />
                <span>Log In</span>
              </button>
            )}
          </>
        )}
      </div>
    </header>
  );
};
