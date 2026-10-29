import React, { useState } from 'react';
import { Globe, Plus, Trash2, X, ExternalLink } from 'lucide-react';

export interface ReferenceUrlsProps {
  urls: string[];
  onAddUrl: (url: string) => Promise<boolean>;
  onRemoveUrl: (url: string) => void;
}

export function validateUrlSyntax(raw: string): { valid: boolean; formatted: string; error?: string } {
  let target = raw.trim();
  if (!target) {
    return { valid: false, formatted: '', error: 'Please enter a URL.' };
  }
  if (!/^https?:\/\//i.test(target) && !target.startsWith('//')) {
    target = `https://${target}`;
  }
  try {
    const parsed = new URL(target);
    if (!['http:', 'https:'].includes(parsed.protocol)) {
      return { valid: false, formatted: target, error: 'Only http:// and https:// URLs are supported.' };
    }
    if (!parsed.hostname || (!parsed.hostname.includes('.') && parsed.hostname !== 'localhost')) {
      return { valid: false, formatted: target, error: 'Invalid URL: domain name is missing or incomplete.' };
    }
    return { valid: true, formatted: target };
  } catch {
    return { valid: false, formatted: target, error: 'Invalid URL format.' };
  }
}

export async function verifyUrlReachability(
  _url: string,
  _timeoutMs: number = 5000
): Promise<{ reachable: boolean; error?: string }> {
  // Pure syntax and client-safe reachability stub; network probes are omitted to conform to strict CSP
  return { reachable: true };
}

export const ReferenceUrls: React.FC<ReferenceUrlsProps> = ({ urls, onAddUrl, onRemoveUrl }) => {
  const [isModalOpen, setIsModalOpen] = useState(false);
  const [inputUrl, setInputUrl] = useState('');
  const [errorMessage, setErrorMessage] = useState<string | null>(null);
  const [pendingUrl, setPendingUrl] = useState<string | null>(null);

  const isFull = urls.length >= 10;

  const commitAddUrl = async (target: string): Promise<void> => {
    if (urls.includes(target)) {
      setErrorMessage('This URL has already been added.');
      return;
    }
    if (urls.length >= 10) {
      setErrorMessage('Maximum 10 reference URLs reached.');
      return;
    }
    const added = await onAddUrl(target);
    if (added) {
      setInputUrl('');
      setErrorMessage(null);
      setPendingUrl(null);
    } else {
      setErrorMessage('Failed to add URL.');
    }
  };

  const handleSubmit = async (e: React.FormEvent) => {
    e.preventDefault();

    const raw = inputUrl.trim();
    if (!raw) {
      setErrorMessage('Please enter a URL.');
      setPendingUrl(null);
      return;
    }

    const check = validateUrlSyntax(raw);
    if (!check.valid) {
      setErrorMessage(check.error || 'Invalid URL format.');
      setPendingUrl(check.formatted || raw);
      return;
    }

    await commitAddUrl(check.formatted);
  };

  const handleAddAnyway = async () => {
    if (pendingUrl) {
      await commitAddUrl(pendingUrl);
    }
  };

  return (
    <div className="reference-urls-container">
      <div className="urls-header">
        <span className="urls-title">
          <Globe size={14} /> Reference URLs ({urls.length}/10)
        </span>
        <button
          type="button"
          onClick={() => setIsModalOpen(true)}
          className="btn-add-url-trigger"
          title="Add Reference URL"
        >
          <Plus size={14} /> Manage
        </button>
      </div>

      {urls.length > 0 && (
        <div className="urls-chips">
          {urls.map((url) => {
            let domain = url;
            try {
              domain = new URL(url).hostname;
            } catch {
              // ignore
            }
            return (
              <span key={url} className="url-chip" title={url}>
                <span className="chip-text">{domain}</span>
                <button
                  type="button"
                  onClick={() => onRemoveUrl(url)}
                  className="chip-remove"
                  title={`Remove ${url}`}
                >
                  <X size={10} />
                </button>
              </span>
            );
          })}
        </div>
      )}

      {isModalOpen && (
        <div className="modal-backdrop" onClick={() => setIsModalOpen(false)}>
          <div className="modal-content" onClick={(e) => e.stopPropagation()}>
            <div className="modal-header">
              <h3>Manage Reference URLs</h3>
              <button
                type="button"
                onClick={() => setIsModalOpen(false)}
                className="modal-close"
              >
                <X size={18} />
              </button>
            </div>

            <p className="modal-description">
              Stored URLs are exposed to visiting WebMCP agents via <code>get_reference_url</code> to cite documentation and syllabus sources.
            </p>

            <form onSubmit={handleSubmit} className="url-form">
              <div className="input-group">
                <input
                  type="text"
                  placeholder="https://example.com/syllabus"
                  value={inputUrl}
                  onChange={(e) => {
                    setInputUrl(e.target.value);
                    if (errorMessage) setErrorMessage(null);
                    if (pendingUrl) setPendingUrl(null);
                  }}
                  disabled={isFull}
                  className="url-input"
                />
                <button
                  type="submit"
                  disabled={isFull}
                  className="btn-submit-url"
                >
                  <Plus size={14} /> Add
                </button>
              </div>
              {errorMessage && (
                <div className="url-error-container" style={{ display: 'flex', alignItems: 'center', gap: '8px', marginTop: '6px' }}>
                  <p className="url-error" style={{ margin: 0 }}>{errorMessage}</p>
                  {pendingUrl && (
                    <button
                      type="button"
                      onClick={handleAddAnyway}
                      className="btn-add-anyway"
                      style={{
                        background: 'transparent',
                        border: '1px solid currentColor',
                        borderRadius: '4px',
                        padding: '2px 8px',
                        fontSize: '11px',
                        cursor: 'pointer',
                        color: 'inherit',
                      }}
                    >
                      Add Anyway
                    </button>
                  )}
                </div>
              )}
            </form>

            <div className="url-list">
              {urls.length === 0 ? (
                <p className="empty-urls">No reference URLs saved yet.</p>
              ) : (
                urls.map((u) => (
                  <div key={u} className="url-item">
                    <a href={u} target="_blank" rel="noopener noreferrer" className="url-link">
                      <ExternalLink size={12} /> {u}
                    </a>
                    <button
                      type="button"
                      onClick={() => onRemoveUrl(u)}
                      className="btn-delete-url"
                      title="Remove"
                    >
                      <Trash2 size={13} />
                    </button>
                  </div>
                ))
              )}
            </div>
          </div>
        </div>
      )}
    </div>
  );
};
