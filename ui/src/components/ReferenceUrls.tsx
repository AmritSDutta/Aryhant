import React, { useState } from 'react';
import { Globe, Plus, Trash2, X, ExternalLink, Loader2 } from 'lucide-react';

export interface ReferenceUrlsProps {
  urls: string[];
  onAddUrl: (url: string) => Promise<boolean>;
  onRemoveUrl: (url: string) => void;
}

export async function verifyUrlReachability(
  url: string,
  timeoutMs: number = 5000
): Promise<{ reachable: boolean; error?: string }> {
  try {
    const controller = new AbortController();
    const timer = setTimeout(() => controller.abort(), timeoutMs);
    await fetch(url, { method: 'GET', mode: 'no-cors', signal: controller.signal });
    clearTimeout(timer);
    return { reachable: true };
  } catch (err: unknown) {
    const errorObj = err as { name?: string; message?: string };
    if (errorObj?.name === 'AbortError') {
      return { reachable: false, error: 'Connection timed out (5s limit).' };
    }
    return { reachable: false, error: 'URL is unreachable or network failed.' };
  }
}

export const ReferenceUrls: React.FC<ReferenceUrlsProps> = ({ urls, onAddUrl, onRemoveUrl }) => {
  const [isModalOpen, setIsModalOpen] = useState(false);
  const [inputUrl, setInputUrl] = useState('');
  const [isVerifying, setIsVerifying] = useState(false);
  const [errorMessage, setErrorMessage] = useState<string | null>(null);

  const isFull = urls.length >= 10;

  const handleSubmit = async (e: React.FormEvent) => {
    e.preventDefault();
    if (isVerifying) return;

    let target = inputUrl.trim();
    if (!target) {
      setErrorMessage('Please enter a URL.');
      return;
    }

    if (!/^https?:\/\//i.test(target)) {
      target = `https://${target}`;
    }

    try {
      const parsed = new URL(target);
      if (!['http:', 'https:'].includes(parsed.protocol)) {
        setErrorMessage('Only http:// and https:// URLs are supported.');
        return;
      }
    } catch {
      setErrorMessage('Invalid URL format.');
      return;
    }

    if (urls.includes(target)) {
      setErrorMessage('This URL has already been added.');
      return;
    }

    if (urls.length >= 10) {
      setErrorMessage('Maximum 10 reference URLs reached.');
      return;
    }

    setIsVerifying(true);
    setErrorMessage(null);

    const check = await verifyUrlReachability(target);
    setIsVerifying(false);

    if (!check.reachable) {
      setErrorMessage(check.error || 'URL is unreachable.');
      return;
    }

    const added = await onAddUrl(target);
    if (added) {
      setInputUrl('');
      setErrorMessage(null);
    } else {
      setErrorMessage('Failed to add URL.');
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
        <div className="modal-backdrop" onClick={() => !isVerifying && setIsModalOpen(false)}>
          <div className="modal-content" onClick={(e) => e.stopPropagation()}>
            <div className="modal-header">
              <h3>Manage Reference URLs</h3>
              <button
                type="button"
                onClick={() => !isVerifying && setIsModalOpen(false)}
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
                  onChange={(e) => setInputUrl(e.target.value)}
                  disabled={isVerifying || isFull}
                  className="url-input"
                />
                <button
                  type="submit"
                  disabled={isVerifying || isFull}
                  className="btn-submit-url"
                >
                  {isVerifying ? <Loader2 size={14} className="spin" /> : <Plus size={14} />} Add
                </button>
              </div>
              {errorMessage && <p className="url-error">{errorMessage}</p>}
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
