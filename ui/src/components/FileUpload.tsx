import React, { useRef, useState } from 'react';
import { Upload, FileText, CheckCircle2, AlertCircle, Trash2 } from 'lucide-react';
import { ActiveDocumentInfo } from '../hooks/useDocumentController';

interface FileUploadProps {
  activeDoc: ActiveDocumentInfo | null;
  onFileSelect: (file: File) => void;
  onClearDocument?: () => void;
}

export const FileUpload: React.FC<FileUploadProps> = ({
  activeDoc,
  onFileSelect,
  onClearDocument,
}) => {
  const fileInputRef = useRef<HTMLInputElement>(null);
  const [dragOver, setDragOver] = useState(false);

  const handleFileChange = (e: React.ChangeEvent<HTMLInputElement>) => {
    const file = e.target.files?.[0];
    if (file) {
      onFileSelect(file);
    }
    if (fileInputRef.current) {
      fileInputRef.current.value = '';
    }
  };

  const handleDrop = (e: React.DragEvent<HTMLDivElement>) => {
    e.preventDefault();
    setDragOver(false);
    const file = e.dataTransfer.files?.[0];
    if (file) {
      onFileSelect(file);
    }
  };

  return (
    <div className="file-upload-container">
      <div className="upload-header">
        <span className="upload-title">Document Ingestion</span>
        <span className="upload-hint">&lt; 2MB (PDF/DOCX/MD/TXT)</span>
      </div>

      <div
        onDrop={handleDrop}
        onDragOver={(e) => {
          e.preventDefault();
          setDragOver(true);
        }}
        onDragLeave={() => setDragOver(false)}
        onClick={() => fileInputRef.current?.click()}
        className={`upload-dropzone ${dragOver ? 'drag-over' : ''}`}
      >
        <input
          ref={fileInputRef}
          type="file"
          accept=".pdf,.doc,.docx,.txt,.md"
          onChange={handleFileChange}
          style={{ display: 'none' }}
        />
        <Upload size={16} className="upload-icon" />
        <span className="dropzone-text">
          {dragOver ? 'Release to ingest file' : 'Drop document or click to browse'}
        </span>
      </div>

      {activeDoc && (
        <div className="active-doc-badge">
          <div className="doc-info-row">
            <FileText size={14} className="doc-icon" />
            <span className="doc-name" title={activeDoc.name}>
              {activeDoc.name}
            </span>
            {activeDoc.status === 'indexed' && (
              <span className="badge-status success">
                <CheckCircle2 size={11} /> Indexed
              </span>
            )}
            {activeDoc.status === 'parsing' && (
              <span className="badge-status parsing">Parsing...</span>
            )}
            {activeDoc.status === 'error' && (
              <span className="badge-status error">
                <AlertCircle size={11} /> Error
              </span>
            )}
          </div>

          <div className="doc-meta-row">
            <span>
              {activeDoc.pageCount} {activeDoc.pageCount === 1 ? 'page' : 'pages'}
            </span>
            <span>{(activeDoc.size / 1024).toFixed(1)} KB</span>
            {onClearDocument && (
              <button
                type="button"
                onClick={(e) => {
                  e.stopPropagation();
                  onClearDocument();
                }}
                className="btn-clear-doc"
                title="Clear document"
              >
                <Trash2 size={12} /> Clear
              </button>
            )}
          </div>
        </div>
      )}
    </div>
  );
};
