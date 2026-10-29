import React, { useState } from 'react';
import { useAuth0 } from '@auth0/auth0-react';
import { LogIn, LogOut, Flame, CheckCircle2, AlertCircle, Loader2 } from 'lucide-react';
import { StatusPill } from './StatusPill';
import { fetchHealth } from '../lib/api';
import { appConfig } from '../lib/config';

const UserAvatar: React.FC<{ user: { picture?: string; name?: string; email?: string } }> = ({ user }) => {
  const [imageError, setImageError] = React.useState(false);
  const initials = (user.name || user.email || 'U')[0].toUpperCase();

  if (user.picture && !imageError) {
    return (
      <img
        src={user.picture}
        alt={user.name || 'User'}
        className="user-avatar"
        referrerPolicy="no-referrer"
        crossOrigin="anonymous"
        onError={() => setImageError(true)}
      />
    );
  }

  return <div className="user-avatar-placeholder" title={user.name || user.email}>{initials}</div>;
};

export const Header: React.FC = () => {
  const auth0 = appConfig.isAuthEnabled ? useAuth0() : null;
  const [authTimeout, setAuthTimeout] = React.useState(false);
  const [isWarming, setIsWarming] = useState(false);
  const [warmStatus, setWarmStatus] = useState<'idle' | 'success' | 'error'>('idle');

  const handleWarmUpServer = async () => {
    if (isWarming) return;
    setIsWarming(true);
    setWarmStatus('idle');
    try {
      const res = await fetchHealth();
      if (res && res.ok) {
        setWarmStatus('success');
      } else {
        setWarmStatus('error');
      }
    } catch (err) {
      console.warn('Failed to warm up backend server:', err);
      setWarmStatus('error');
    } finally {
      setIsWarming(false);
      setTimeout(() => setWarmStatus('idle'), 3500);
    }
  };

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

        <button
          type="button"
          className="warmup-btn"
          onClick={handleWarmUpServer}
          disabled={isWarming}
          title="Ping /api/health to warm up cold Cloud Run instance"
        >
          {isWarming ? (
            <>
              <Loader2 size={13} className="spin" />
              <span>Warming Up...</span>
            </>
          ) : warmStatus === 'success' ? (
            <>
              <CheckCircle2 size={13} color="#2e7d32" />
              <span>Server Ready</span>
            </>
          ) : warmStatus === 'error' ? (
            <>
              <AlertCircle size={13} color="#c62828" />
              <span>Retry Warmup</span>
            </>
          ) : (
            <>
              <Flame size={13} />
              <span>Warm Up Server</span>
            </>
          )}
        </button>

        {appConfig.isAuthEnabled && auth0 && (
          <>
            {auth0.isLoading && !authTimeout ? (
              <span className="brand-subtitle">Loading auth...</span>
            ) : auth0.isAuthenticated && auth0.user ? (
              <div className="user-badge">
                <UserAvatar user={auth0.user} />
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
