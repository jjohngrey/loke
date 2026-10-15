type PendingBlock = { kind: "code" | "math"; start: number; marker?: string; length?: number };

/** Keep an unfinished fenced block stable while model text is still arriving. */
export function splitStreamingMarkdown(text: string) {
  let open: PendingBlock | null = null;
  let offset = 0;
  const lines = text.split("\n");

  for (let index = 0; index < lines.length; index += 1) {
    const line = lines[index];
    if (open?.kind === "code") {
      const closing = new RegExp(`^ {0,3}${open.marker}{${open.length},}\\s*$`);
      if (closing.test(line)) open = null;
    } else if (open?.kind === "math") {
      if ((line.split("$$").length - 1) % 2 === 1) open = null;
    } else {
      const fence = /^ {0,3}(`{3,}|~{3,})/.exec(line);
      if (fence) {
        open = { kind: "code", start: offset, marker: fence[1][0], length: fence[1].length };
      } else if (/^ {0,3}\$\$/.test(line) && line.split("$$").length % 2 === 0) {
        open = { kind: "math", start: offset };
      }
    }
    offset += line.length + (index < lines.length - 1 ? 1 : 0);
  }

  return open
    ? { markdown: text.slice(0, open.start), pending: text.slice(open.start), kind: open.kind }
    : { markdown: text, pending: "", kind: null };
}
