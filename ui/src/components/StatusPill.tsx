import React, { useEffect, useState } from 'react';
import { fetchHealth } from '../lib/api';
import { HealthResponse } from '../lib/types';

export const StatusPill: React.FC = () => {
  const [health, setHealth] = useState<HealthResponse | null>(null);
  const [loading, setLoading] = useState<boolean>(true);
  const [error, setError] = useState<boolean>(false);

  const checkHealth = async () => {
    try {
      const res = await fetchHealth();
      setHealth(res);
      setError(!res.ok);
    } catch {
      setError(true);
    } finally {
      setLoading(false);
    }
  };

  useEffect(() => {
    checkHealth();
    const interval = setInterval(checkHealth, 30000);
    return () => clearInterval(interval);
  }, []);

  let statusClass = 'healthy';
  let label = 'Online';

  if (loading) {
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
