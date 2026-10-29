import React from 'react';
import { humanizeSymbols } from '../lib/symbolHumanizer';

export interface HumanizedMessageProps {
  content: string;
}

export function parseInlineMarkdown(text: string): React.ReactNode[] {
  if (!text) return [];

  const humanized = humanizeSymbols(text);
  const tokenRegex = /(\[[^\]]+\]\([^)]+\)|\*\*[^*]+\*\*|__[^_]+__|`[^`]+`|\*[^*]+\*|_[^_]+_)/g;
  const parts = humanized.split(tokenRegex);

  return parts.filter(Boolean).map((part, index) => {
    // 1. Link: [label](url)
    const linkMatch = /^\[([^\]]+)\]\(([^)]+)\)$/.exec(part);
    if (linkMatch) {
      return (
        <a
          key={index}
          href={linkMatch[2]}
          target="_blank"
          rel="noopener noreferrer"
          className="msg-link"
        >
          {linkMatch[1]}
        </a>
      );
    }

    // 2. Bold: **text** or __text__
    if (
      (part.startsWith('**') && part.endsWith('**') && part.length >= 4) ||
      (part.startsWith('__') && part.endsWith('__') && part.length >= 4)
    ) {
      return (
        <strong key={index} className="msg-bold">
          {part.slice(2, -2)}
        </strong>
      );
    }

    // 3. Inline Code: `code`
    if (part.startsWith('`') && part.endsWith('`') && part.length >= 2) {
      return (
        <code key={index} className="msg-code">
          {part.slice(1, -1)}
        </code>
      );
    }

    // 4. Italic: *text* or _text_
    if (
      (part.startsWith('*') && part.endsWith('*') && part.length >= 2) ||
      (part.startsWith('_') && part.endsWith('_') && part.length >= 2)
    ) {
      return (
        <em key={index} className="msg-italic">
          {part.slice(1, -1)}
        </em>
      );
    }

    // 5. Normal text segment
    return <React.Fragment key={index}>{part}</React.Fragment>;
  });
}

export type MessageBlock =
  | { type: 'code'; lang?: string; code: string }
  | { type: 'h1'; text: string }
  | { type: 'h2'; text: string }
  | { type: 'h3'; text: string }
  | { type: 'h4'; text: string }
  | { type: 'bullet_list'; items: string[] }
  | { type: 'numbered_list'; items: { num: string; text: string }[] }
  | { type: 'quote'; lines: string[] }
  | { type: 'divider' }
  | { type: 'paragraph'; text: string };

export function parseMessageBlocks(content: string): MessageBlock[] {
  const lines = content.split('\n');
  const blocks: MessageBlock[] = [];
  let inCode = false;
  let codeLang = '';
  let codeLines: string[] = [];

  for (let i = 0; i < lines.length; i++) {
    const line = lines[i];
    const trimmed = line.trim();

    // 1. Fenced Code Block delimiter
    if (trimmed.startsWith('```')) {
      if (inCode) {
        blocks.push({ type: 'code', lang: codeLang, code: codeLines.join('\n') });
        inCode = false;
        codeLines = [];
        codeLang = '';
      } else {
        inCode = true;
        codeLang = trimmed.slice(3).trim();
        codeLines = [];
      }
      continue;
    }

    if (inCode) {
      codeLines.push(line);
      continue;
    }

    // 2. Empty line
    if (!trimmed) {
      continue;
    }

    // 3. Horizontal Rule
    if (/^(\*\*\*|---|___)$/.test(trimmed)) {
      blocks.push({ type: 'divider' });
      continue;
    }

    // 4. Headings
    if (trimmed.startsWith('# ') || trimmed.startsWith('## ') || trimmed.startsWith('### ') || trimmed.startsWith('#### ')) {
      const match = /^(#{1,4})\s+(.+)$/.exec(trimmed);
      if (match) {
        const level = match[1].length;
        const text = match[2].trim();
        if (level === 1) blocks.push({ type: 'h1', text });
        else if (level === 2) blocks.push({ type: 'h2', text });
        else if (level === 3) blocks.push({ type: 'h3', text });
        else blocks.push({ type: 'h4', text });
        continue;
      }
    }

    // 5. Blockquote
    if (trimmed.startsWith('>')) {
      const quoteLines: string[] = [];
      while (i < lines.length && lines[i].trim().startsWith('>')) {
        quoteLines.push(lines[i].trim().replace(/^>\s?/, ''));
        i++;
      }
      i--;
      blocks.push({ type: 'quote', lines: quoteLines });
      continue;
    }

    // 6. Bullet list (- or * or •)
    if (/^[-*•]\s+/.test(trimmed)) {
      const items: string[] = [];
      while (i < lines.length && /^[-*•]\s+/.test(lines[i].trim())) {
        items.push(lines[i].trim().replace(/^[-*•]\s+/, ''));
        i++;
      }
      i--;
      blocks.push({ type: 'bullet_list', items });
      continue;
    }

    // 7. Numbered list (1. 2.)
    if (/^\d+\.\s+/.test(trimmed)) {
      const items: { num: string; text: string }[] = [];
      while (i < lines.length && /^\d+\.\s+/.test(lines[i].trim())) {
        const itemMatch = /^(\d+)\.\s+(.*)$/.exec(lines[i].trim());
        if (itemMatch) {
          items.push({ num: itemMatch[1], text: itemMatch[2] });
        }
        i++;
      }
      i--;
      blocks.push({ type: 'numbered_list', items });
      continue;
    }

    // 8. Paragraph grouping
    const paraLines: string[] = [];
    while (
      i < lines.length &&
      lines[i].trim() &&
      !lines[i].trim().startsWith('```') &&
      !/^(\*\*\*|---|___)$/.test(lines[i].trim()) &&
      !/^#{1,4}\s+/.test(lines[i].trim()) &&
      !lines[i].trim().startsWith('>') &&
      !/^[-*•]\s+/.test(lines[i].trim()) &&
      !/^\d+\.\s+/.test(lines[i].trim())
    ) {
      paraLines.push(lines[i].trim());
      i++;
    }
    i--;
    blocks.push({ type: 'paragraph', text: paraLines.join(' ') });
  }

  if (inCode && codeLines.length > 0) {
    blocks.push({ type: 'code', lang: codeLang, code: codeLines.join('\n') });
  }

  return blocks;
}

export const HumanizedMessage: React.FC<HumanizedMessageProps> = ({ content }) => {
  const blocks = parseMessageBlocks(content || '');

  return (
    <div className="humanized-msg-body">
      {blocks.map((block, idx) => {
        switch (block.type) {
          case 'h1':
            return <h1 key={idx} className="msg-h1">{parseInlineMarkdown(block.text)}</h1>;
          case 'h2':
            return <h2 key={idx} className="msg-h2">{parseInlineMarkdown(block.text)}</h2>;
          case 'h3':
            return <h3 key={idx} className="msg-h3">{parseInlineMarkdown(block.text)}</h3>;
          case 'h4':
            return <h4 key={idx} className="msg-h4">{parseInlineMarkdown(block.text)}</h4>;
          case 'bullet_list':
            return (
              <ul key={idx} className="msg-bullet-list">
                {block.items.map((item, itemIdx) => (
                  <li key={itemIdx} className="msg-list-item">
                    {parseInlineMarkdown(item)}
                  </li>
                ))}
              </ul>
            );
          case 'numbered_list':
            return (
              <ol key={idx} className="msg-numbered-list">
                {block.items.map((item, itemIdx) => (
                  <li key={itemIdx} className="msg-list-item">
                    {parseInlineMarkdown(item.text)}
                  </li>
                ))}
              </ol>
            );
          case 'quote':
            return (
              <blockquote key={idx} className="msg-blockquote">
                {block.lines.map((l, lIdx) => (
                  <p key={lIdx}>{parseInlineMarkdown(l)}</p>
                ))}
              </blockquote>
            );
          case 'code':
            return (
              <div key={idx} className="msg-code-block">
                {block.lang && <div className="code-lang-label">{block.lang}</div>}
                <pre className="code-pre">
                  <code>{block.code}</code>
                </pre>
              </div>
            );
          case 'divider':
            return <hr key={idx} className="msg-divider" />;
          case 'paragraph':
          default:
            return (
              <p key={idx} className="msg-paragraph">
                {parseInlineMarkdown(block.text)}
              </p>
            );
        }
      })}
    </div>
  );
};
