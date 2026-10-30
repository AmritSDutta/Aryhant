import React, { useEffect, useState } from 'react';
import { useAuth0 } from '@auth0/auth0-react';
import { fetchHealth } from '../lib/api';
import { appConfig } from '../lib/config';
import { HealthResponse } from '../lib/types';

interface StatusPillProps {
  isAuthenticated?: boolean;
}

export const StatusPill: React.FC<StatusPillProps> = ({ isAuthenticated: propIsAuth }) => {
  const auth0 = appConfig.isAuthEnabled ? useAuth0() : null;
  const isAuth =
    propIsAuth !== undefined
      ? propIsAuth
      : !appConfig.isAuthEnabled || Boolean(auth0?.isAuthenticated);

  const [health, setHealth] = useState<HealthResponse | null>(null);
  const [loading, setLoading] = useState<boolean>(false);
  const [error, setError] = useState<boolean>(false);

  useEffect(() => {
    // Strictly connect to backend server ONLY post-login!
    if (!isAuth) {
      setLoading(false);
      setHealth(null);
      setError(false);
      return;
    }

    let isCancelled = false;

    const checkHealth = async () => {
      setLoading(true);
      try {
        let token: string | undefined = undefined;
        if (appConfig.isAuthEnabled && auth0?.isAuthenticated) {
          try {
            token = await auth0.getAccessTokenSilently({
              authorizationParams: {
                audience: appConfig.auth0Audience || undefined,
              },
            });
          } catch {
            // Optional token for health check
          }
        }
        const res = await fetchHealth(token);
        if (!isCancelled) {
          setHealth(res);
          setError(!res.ok);
        }
      } catch {
        if (!isCancelled) {
          setError(true);
        }
      } finally {
        if (!isCancelled) {
          setLoading(false);
        }
      }
    };

    checkHealth();
    const interval = setInterval(checkHealth, 30000);
    return () => {
      isCancelled = true;
      clearInterval(interval);
    };
  }, [isAuth, auth0?.isAuthenticated]);

  if (!isAuth) {
    return null;
  }

  let statusClass = 'healthy';
  let label = 'Online';

  if (loading && !health) {
    statusClass = 'loading';
    label = 'Connecting...';
  } else if (error || !health) {
    statusClass = 'error';
    label = 'Offline';
  }

  return (
    <div className="status-pill" title={health ? `API v${health.version}` : 'Backend unreachable'}>
      <span className={`status-dot ${statusClass}`} />
      <span>{label}</span>
    </div>
  );
};
