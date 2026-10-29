import { jsPDF } from 'jspdf';
import { SessionTurnRecord } from './idbStorage';
import { humanizeSymbolsForPdf } from './symbolHumanizer';

export interface ExportPdfResult {
  success: boolean;
  error?: string;
}

export interface ExportSessionPdfOptions {
  sessionId?: string;
  turns?: SessionTurnRecord[];
  messages?: Array<{ sender: 'user' | 'assistant' | 'agent'; text: string; timestamp?: string }>;
  docName?: string;
}

export function containsIndicScript(text: string): boolean {
  // \u0900-\u097F: Devanagari, \u0980-\u09FF: Bengali, \u0A00-\u0A7F: Gurmukhi, etc.
  return /[\u0900-\u0DFF]/.test(text);
}

export function stripInlineMarkdown(text: string): string {
  if (!text) return '';
  return humanizeSymbolsForPdf(text)
    .replace(/!\[([^\]]*)\]\([^)]+\)/g, (_m, alt) => (alt ? `[Image: ${alt}]` : '[Image]'))
    .replace(/\[([^\]]+)\]\([^)]+\)/g, '$1')
    .replace(/`([^`]+)`/g, "'$1'")
    .replace(/\*\*([^*]+)\*\*/g, '$1')
    .replace(/__([^_]+)__/g, '$1')
    .replace(/\*([^*]+)\*/g, '$1')
    .replace(/_([^_]+)_/g, '$1')
    .replace(/~~([^~]+)~~/g, '$1')
    .replace(/<br\s*\/?>/gi, '\n')
    .replace(/<\/?[^>]+(>|$)/g, '')
    .replace(/&nbsp;/g, ' ')
    .replace(/&amp;/g, '&')
    .replace(/&lt;/g, '<')
    .replace(/&gt;/g, '>')
    .replace(/&quot;/g, '"')
    .replace(/&#39;/g, "'")
    .replace(/\\([*_#`~[\]>+-])/g, '$1');
}

export function wrapIndicText(
  text: string,
  fontSizePt: number,
  maxWidthMm: number,
  isBold: boolean = false
): string[] {
  if (typeof document === 'undefined') return [text];
  try {
    const canvas = document.createElement('canvas');
    const ctx = canvas.getContext('2d');
    if (!ctx) return [text];

    const scale = 3;
    const fontStyle = isBold ? 'bold ' : '';
    ctx.font = `${fontStyle}${fontSizePt * scale}px "Noto Sans Devanagari", "Noto Sans Bengali", "Nirmala UI", sans-serif`;

    const maxWidthPx = (maxWidthMm / 0.352778) * scale;
    const words = text.split(/\s+/).filter(Boolean);
    if (words.length === 0) return [];

    const lines: string[] = [];
    let currentLine = words[0];

    for (let i = 1; i < words.length; i++) {
      const candidate = `${currentLine} ${words[i]}`;
      if (ctx.measureText(candidate).width <= maxWidthPx) {
        currentLine = candidate;
      } else {
        lines.push(currentLine);
        currentLine = words[i];
      }
    }
    lines.push(currentLine);
    return lines;
  } catch {
    return [text];
  }
}

export function renderIndicTextStrip(
  text: string,
  fontSizePt: number,
  textColorHex: string,
  isBold: boolean = false
): { dataUrl: string; widthMm: number; heightMm: number } | null {
  if (typeof document === 'undefined') return null;
  try {
    const canvas = document.createElement('canvas');
    const ctx = canvas.getContext('2d');
    if (!ctx) return null;

    const scale = 3;
    const fontStyle = isBold ? 'bold ' : '';
    const fontStack = `${fontStyle}${fontSizePt * scale}px "Noto Sans Devanagari", "Noto Sans Bengali", "Nirmala UI", sans-serif`;

    ctx.font = fontStack;
    const metrics = ctx.measureText(text);
    const widthPx = Math.ceil(metrics.width + 8 * scale);
    const heightPx = Math.ceil(fontSizePt * 1.5 * scale);

    canvas.width = widthPx;
    canvas.height = heightPx;

    ctx.font = fontStack;
    ctx.fillStyle = textColorHex;
    ctx.textBaseline = 'top';
    ctx.fillText(text, 2 * scale, 2 * scale);

    const widthMm = (canvas.width / scale) * 0.352778;
    const heightMm = (canvas.height / scale) * 0.352778;

    return {
      dataUrl: canvas.toDataURL('image/png'),
      widthMm,
      heightMm,
    };
  } catch {
    return null;
  }
}

interface PdfCursor {
  y: number;
}

function drawLineText(
  doc: jsPDF,
  lineText: string,
  x: number,
  y: number,
  fontSizePt: number,
  textColorHex: string,
  isBold: boolean = false
): void {
  if (containsIndicScript(lineText)) {
    const strip = renderIndicTextStrip(lineText, fontSizePt, textColorHex, isBold);
    if (strip) {
      try {
        doc.addImage(strip.dataUrl, 'PNG', x, y - 3.2, strip.widthMm, strip.heightMm);
        return;
      } catch (err) {
        console.warn('Could not draw Indic image text strip to PDF:', err);
      }
    }
  }
  doc.text(lineText, x, y);
}

export function renderHumanizedMarkdown(
  doc: jsPDF,
  markdown: string,
  margin: number,
  contentWidth: number,
  cursor: PdfCursor,
  ensureSpace: (needed: number) => void
): number {
  const rawLines = (markdown || '').split('\n');

  for (const rawLine of rawLines) {
    const trimmed = rawLine.trim();

    // 1. Empty lines
    if (!trimmed) {
      cursor.y += 2.5;
      continue;
    }

    // 2. Horizontal Rule
    if (/^(\*\*\*|---|___)$/.test(trimmed)) {
      ensureSpace(4);
      doc.setDrawColor(235, 220, 203); // #ebdccb
      doc.setLineWidth(0.3);
      doc.line(margin, cursor.y, margin + contentWidth, cursor.y);
      cursor.y += 4;
      continue;
    }

    // 3. Headings (# H1, ## H2, ### H3, #### H4)
    const headingMatch = /^(#{1,4})\s+(.+)$/.exec(trimmed);
    if (headingMatch) {
      const level = headingMatch[1].length;
      const headingText = stripInlineMarkdown(headingMatch[2]);
      const fontSize = level === 1 ? 12 : level === 2 ? 11 : 10;
      const fontHeight = fontSize * 0.45;

      ensureSpace(fontHeight + 4);
      doc.setFont('helvetica', 'bold');
      doc.setFontSize(fontSize);
      doc.setTextColor(59, 46, 37); // #3b2e25

      const hLines = containsIndicScript(headingText)
        ? wrapIndicText(headingText, fontSize, contentWidth - 4, true)
        : doc.splitTextToSize(headingText, contentWidth - 4);

      for (let i = 0; i < hLines.length; i++) {
        if (i > 0) ensureSpace(fontHeight);
        drawLineText(doc, hLines[i], margin + 2, cursor.y, fontSize, '#3b2e25', true);
        cursor.y += fontHeight;
      }
      cursor.y += 2;
      continue;
    }

    // 4. Bullet lists (- or * or •)
    const bulletMatch = /^(\s*)[*+-•]\s+(.*)$/.exec(rawLine);
    if (bulletMatch) {
      const indent = bulletMatch[1].length > 0 ? 8 : 4;
      const itemText = stripInlineMarkdown(bulletMatch[2]);
      const itemLines = containsIndicScript(itemText)
        ? wrapIndicText(itemText, 9.5, contentWidth - indent - 4, false)
        : doc.splitTextToSize(itemText, contentWidth - indent - 4);

      ensureSpace(4.5);
      doc.setFont('helvetica', 'bold');
      doc.setFontSize(9.5);
      doc.setTextColor(148, 99, 56); // #946338
      doc.text('\u2022', margin + indent - 1.5, cursor.y);

      doc.setFont('helvetica', 'normal');
      doc.setFontSize(9.5);
      doc.setTextColor(59, 46, 37);

      for (let i = 0; i < itemLines.length; i++) {
        if (i > 0) ensureSpace(4.5);
        drawLineText(doc, itemLines[i], margin + indent + 2.5, cursor.y, 9.5, '#3b2e25', false);
        cursor.y += 4.5;
      }
      continue;
    }

    // 5. Numbered List items (1. 2.)
    const numberedMatch = /^(\s*)(\d+\.)\s+(.*)$/.exec(rawLine);
    if (numberedMatch) {
      const numBadge = numberedMatch[2];
      const itemText = stripInlineMarkdown(numberedMatch[3]);
      const itemLines = containsIndicScript(itemText)
        ? wrapIndicText(itemText, 9.5, contentWidth - 12, false)
        : doc.splitTextToSize(itemText, contentWidth - 12);

      ensureSpace(4.5);
      doc.setFont('helvetica', 'bold');
      doc.setFontSize(9);
      doc.setTextColor(148, 99, 56);
      doc.text(numBadge, margin + 3, cursor.y);

      doc.setFont('helvetica', 'normal');
      doc.setFontSize(9.5);
      doc.setTextColor(59, 46, 37);

      for (let i = 0; i < itemLines.length; i++) {
        if (i > 0) ensureSpace(4.5);
        drawLineText(doc, itemLines[i], margin + 9.5, cursor.y, 9.5, '#3b2e25', false);
        cursor.y += 4.5;
      }
      continue;
    }

    // 6. Blockquote (> quote)
    if (trimmed.startsWith('>')) {
      const quoteText = stripInlineMarkdown(trimmed.replace(/^>\s?/, ''));
      const qLines = containsIndicScript(quoteText)
        ? wrapIndicText(quoteText, 9, contentWidth - 12, false)
        : doc.splitTextToSize(quoteText, contentWidth - 12);

      ensureSpace(qLines.length * 4.2 + 2);
      doc.setDrawColor(148, 99, 56);
      doc.setLineWidth(0.8);
      doc.line(margin + 2, cursor.y - 3, margin + 2, cursor.y + (qLines.length - 1) * 4.2 + 1);

      doc.setFont('helvetica', 'italic');
      doc.setFontSize(9);
      doc.setTextColor(120, 101, 85);

      for (const ql of qLines) {
        drawLineText(doc, ql, margin + 6, cursor.y, 9, '#786555', false);
        cursor.y += 4.2;
      }
      cursor.y += 1.5;
      continue;
    }

    // 7. Standard Paragraph Text
    const cleanParagraph = stripInlineMarkdown(rawLine);
    if (!cleanParagraph.trim()) {
      cursor.y += 2;
      continue;
    }

    doc.setFont('helvetica', 'normal');
    doc.setFontSize(9.5);
    doc.setTextColor(59, 46, 37);

    const paraLines = containsIndicScript(cleanParagraph)
      ? wrapIndicText(cleanParagraph, 9.5, contentWidth - 4, false)
      : doc.splitTextToSize(cleanParagraph, contentWidth - 4);

    for (const pLine of paraLines) {
      ensureSpace(4.5);
      drawLineText(doc, pLine, margin + 2, cursor.y, 9.5, '#3b2e25', false);
      cursor.y += 4.5;
    }
  }

  return cursor.y;
}

export function exportSessionPdf(options: ExportSessionPdfOptions): ExportPdfResult {
  const { sessionId, turns, messages, docName } = options;

  const hasSequentialTurns =
    Array.isArray(turns) &&
    turns.length > 0 &&
    turns.some(
      (t) =>
        (t.userPrompt && t.userPrompt.trim().length > 0) ||
        (t.agentMessage && t.agentMessage.trim().length > 0)
    );

  const hasDialogue = Array.isArray(messages) && messages.some((m) => m.text && m.text.trim().length > 0);

  if (!hasSequentialTurns && !hasDialogue) {
    return {
      success: false,
      error: 'Cannot export an empty session without dialogue messages.',
    };
  }

  const doc = new jsPDF({
    orientation: 'portrait',
    unit: 'mm',
    format: 'a4',
  });

  const pageWidth = 210;
  const pageHeight = 297;
  const margin = 16;
  const contentWidth = pageWidth - margin * 2;
  const cursor: PdfCursor = { y: margin };
  const bottomLimit = pageHeight - margin - 10;

  const ensureSpace = (needed: number): void => {
    if (cursor.y + needed > bottomLimit) {
      doc.addPage();
      cursor.y = margin;
    }
  };

  // 1. Header Banner
  doc.setFillColor(247, 239, 225); // #f7efe1 warm parchment
  doc.setDrawColor(235, 220, 203); // #ebdccb border
  doc.roundedRect(margin, cursor.y, contentWidth, 14, 2, 2, 'FD');

  doc.setFont('helvetica', 'bold');
  doc.setFontSize(13);
  doc.setTextColor(148, 99, 56); // #946338 bronze
  doc.text('Aryhant | Family AI Assistant', margin + 4, cursor.y + 6);

  doc.setFont('helvetica', 'normal');
  doc.setFontSize(8);
  doc.setTextColor(120, 101, 85); // #786555
  const dateStr = new Date().toLocaleString();
  let metaInfo = `Generated: ${dateStr}`;
  if (sessionId) metaInfo = `Session: ${sessionId} | ${metaInfo}`;
  if (docName) metaInfo = `${metaInfo} | Doc: ${docName}`;
  doc.text(metaInfo, margin + 4, cursor.y + 11);

  cursor.y += 18;

  // 2. Render Turns (from IDB records or reconstructed from messages)
  if (hasSequentialTurns && turns) {
    for (let i = 0; i < turns.length; i++) {
      const turn = turns[i];
      const turnNum = turn.turnNumber || i + 1;
      const timeStr = turn.timestamp
        ? new Date(turn.timestamp).toLocaleTimeString([], { hour: '2-digit', minute: '2-digit' })
        : '';

      ensureSpace(10);
      doc.setFillColor(253, 251, 247); // #fdfbf7
      doc.setDrawColor(235, 220, 203);
      doc.roundedRect(margin, cursor.y, contentWidth, 6, 1.5, 1.5, 'FD');
      doc.setFont('helvetica', 'bold');
      doc.setFontSize(8.5);
      doc.setTextColor(59, 46, 37);
      const turnLabel = timeStr ? `TURN ${turnNum}  [${timeStr}]` : `TURN ${turnNum}`;
      doc.text(turnLabel, margin + 3, cursor.y + 4.2);
      cursor.y += 8.5;

      if (turn.userPrompt && turn.userPrompt.trim()) {
        ensureSpace(8);
        doc.setFont('helvetica', 'bold');
        doc.setFontSize(8);
        doc.setTextColor(148, 99, 56);
        doc.text('USER', margin + 2, cursor.y);
        cursor.y += 4;

        renderHumanizedMarkdown(doc, turn.userPrompt, margin + 2, contentWidth - 4, cursor, ensureSpace);
        cursor.y += 3;
      }

      if (turn.agentMessage && turn.agentMessage.trim()) {
        ensureSpace(8);
        doc.setFont('helvetica', 'bold');
        doc.setFontSize(8);
        doc.setTextColor(93, 74, 59);
        doc.text('ASSISTANT', margin + 2, cursor.y);
        cursor.y += 4;

        renderHumanizedMarkdown(doc, turn.agentMessage, margin + 2, contentWidth - 4, cursor, ensureSpace);
        cursor.y += 5;
      }
    }
  } else if (messages && messages.length > 0) {
    // Fallback: render messages list directly
    for (const msg of messages) {
      if (!msg.text || !msg.text.trim()) continue;
      const isUser = msg.sender === 'user';

      ensureSpace(8);
      doc.setFont('helvetica', 'bold');
      doc.setFontSize(8);
      doc.setTextColor(isUser ? 148 : 93, isUser ? 99 : 74, isUser ? 56 : 59);
      doc.text(isUser ? 'USER' : 'ASSISTANT', margin + 2, cursor.y);
      cursor.y += 4;

      renderHumanizedMarkdown(doc, msg.text, margin + 2, contentWidth - 4, cursor, ensureSpace);
      cursor.y += 4;
    }
  }

  // 3. Stamp Page Footer
  const totalPages = doc.getNumberOfPages();
  for (let page = 1; page <= totalPages; page++) {
    doc.setPage(page);
    doc.setFont('helvetica', 'normal');
    doc.setFontSize(7.5);
    doc.setTextColor(148, 130, 115);
    doc.text(
      'Aryhant Family AI Assistant | AI generated content, use responsibly',
      pageWidth / 2,
      pageHeight - 8,
      { align: 'center' }
    );
    doc.text(
      `Page ${page} of ${totalPages}`,
      pageWidth - margin,
      pageHeight - 8,
      { align: 'right' }
    );
  }

  const filename = sessionId ? `Aryhant-Session-${sessionId}.pdf` : `Aryhant-Session-${Date.now()}.pdf`;
  doc.save(filename);

  return { success: true };
}
