/** Half-open UTF-16 offsets in rendered content, never Markdown offsets. */
export const SELECTION_VERSION = "loke-rendered-v1" as const;
const excluded = "[data-selection-exclude], .katex-mathml, annotation, script, style";
const blocks = /^(P|DIV|PRE|BLOCKQUOTE|UL|OL|LI|H[1-6]|TABLE|THEAD|TBODY|TFOOT|TR|HR)$/;
export type Segment = { start: number; end: number; value: string; node?: Text; atom?: Element };
export type TextIndex = { root: HTMLElement; text: string; segments: Segment[] };

export function isExcluded(node: Node, root: HTMLElement): boolean {
  const element = node.nodeType === Node.ELEMENT_NODE ? node as Element : node.parentElement;
  const match = element?.closest(excluded);
  return !!match && root.contains(match);
}

export function buildTextIndex(root: HTMLElement): TextIndex {
  const segments: Segment[] = [];
  let text = "";
  function append(value: string, node?: Text, atom?: Element) {
    if (!value) return;
    segments.push({ start: text.length, end: text.length + value.length, value, node, atom });
    text += value;
  }
  function walk(node: Node, inCode = false) {
    if (isExcluded(node, root)) return;
    if (node.nodeType === Node.TEXT_NODE) {
      const value = node.nodeValue || "";
      // React/Markdown formatting whitespace between block elements is not content.
      if (!inCode && !value.trim() && /^(DIV|UL|OL|TABLE|THEAD|TBODY|TFOOT|TR)$/.test(node.parentElement?.tagName || "")) return;
      append(value, node as Text);
      return;
    }
    if (!(node instanceof Element)) return;
    if (node.hasAttribute("data-selection-text")) {
      append(node.getAttribute("data-selection-text") || "", undefined, node);
      return;
    }
    if (node.tagName === "BR") { append("\n"); return; }
    let previous: Element | Text | null = null;
    for (const child of node.childNodes) {
      if (isExcluded(child, root)) continue;
      const before = text.length;
      const isCell = child instanceof Element && /^(TD|TH)$/.test(child.tagName);
      const prevCell = previous instanceof Element && /^(TD|TH)$/.test(previous.tagName);
      const block = child instanceof Element && blocks.test(child.tagName);
      const prevBlock = previous instanceof Element && blocks.test(previous.tagName);
      // Only emit separators for children that actually contribute content.
      const separator = previous ? (isCell && prevCell ? "\t" : block || prevBlock ? "\n" : "") : "";
      const savedLength = segments.length;
      walk(child, inCode || node.tagName === "PRE" || node.tagName === "CODE");
      if (text.length > before) {
        if (separator) {
          for (let i = savedLength; i < segments.length; i++) {
            segments[i].start += separator.length;
            segments[i].end += separator.length;
          }
          segments.splice(savedLength, 0, { start: before, end: before + separator.length, value: separator });
          text = text.slice(0, before) + separator + text.slice(before);
        }
        previous = child as Element | Text;
      }
    }
  }
  walk(root);
  return { root, text, segments };
}

function pointRange(node: Node, offset: number) {
  const range = node.ownerDocument!.createRange();
  range.setStart(node, offset);
  range.collapse(true);
  return range;
}

export function endpointOffset(index: TextIndex, node: Node, offset: number, edge: "start" | "end"): number | null {
  if (!index.root.contains(node) || isExcluded(node, index.root)) return null;
  const direct = index.segments.find((part) => part.node === node);
  if (direct) return direct.start + Math.min(offset, direct.value.length);
  const atomic = index.segments.find((part) => part.atom?.contains(node));
  if (atomic) return edge === "start" ? atomic.start : atomic.end;
  const point = pointRange(node, offset);
  let previous = 0;
  for (const part of index.segments) {
    if (!part.node && !part.atom) continue;
    const range = document.createRange();
    if (part.node) range.selectNodeContents(part.node);
    else range.selectNode(part.atom!);
    if (point.compareBoundaryPoints(Range.START_TO_START, range) <= 0) return part.start;
    if (point.compareBoundaryPoints(Range.START_TO_END, range) < 0)
      return edge === "start" ? part.start : part.end;
    previous = part.end;
  }
  return previous;
}

export function captureRange(root: HTMLElement, range: Range) {
  if (range.collapsed) return null;
  const index = buildTextIndex(root);
  let start = endpointOffset(index, range.startContainer, range.startOffset, "start");
  let end = endpointOffset(index, range.endContainer, range.endOffset, "end");
  if (start === null || end === null) return null;
  const raw = index.text.slice(start, end);
  start += raw.length - raw.trimStart().length;
  end -= raw.length - raw.trimEnd().length;
  // One-character math variables are useful sources in Loke.
  if (start >= end) return null;
  return { startOffset: start, endOffset: end, selectedText: index.text.slice(start, end), streamVersion: SELECTION_VERSION };
}

/** Per-leaf ranges preserve code tokens and KaTeX geometry without DOM mutation. */
export function restoreRanges(index: TextIndex, start: number, end: number): Range[] {
  if (start < 0 || end > index.text.length || start >= end) return [];
  return index.segments.flatMap((part) => {
    if (part.end <= start || part.start >= end || (!part.node && !part.atom)) return [];
    const range = document.createRange();
    if (part.node) {
      range.setStart(part.node, Math.max(0, start - part.start));
      range.setEnd(part.node, Math.min(part.value.length, end - part.start));
    } else range.selectNode(part.atom!);
    return [range];
  });
}

/** Clip hit targets/fallback paint to every independently scrolling ancestor. */
export function visibleRects(range: Range, root: HTMLElement): DOMRect[] {
  let left = 0, top = 0, right = window.innerWidth, bottom = window.innerHeight;
  let host = range.startContainer.parentElement;
  while (host) {
    const style = getComputedStyle(host);
    const rect = host.getBoundingClientRect();
    if (/(auto|scroll|hidden|clip)/.test(style.overflowX)) { left = Math.max(left, rect.left); right = Math.min(right, rect.right); }
    if (/(auto|scroll|hidden|clip)/.test(style.overflowY)) { top = Math.max(top, rect.top); bottom = Math.min(bottom, rect.bottom); }
    host = host.parentElement;
  }
  if (!root.isConnected) return [];
  return Array.from(range.getClientRects()).flatMap((rect) => {
    const x = Math.max(left, rect.left), y = Math.max(top, rect.top);
    const width = Math.min(right, rect.right) - x, height = Math.min(bottom, rect.bottom) - y;
    return width > .5 && height > .5 ? [new DOMRect(x, y, width, height)] : [];
  });
}
