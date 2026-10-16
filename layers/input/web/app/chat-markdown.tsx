"use client";

import { Children, isValidElement, useEffect, useState, type ReactNode } from "react";
import Markdown, { type Components } from "react-markdown";
import rehypeKatex from "rehype-katex";
import remarkGfm from "remark-gfm";
import remarkMath from "remark-math";
import { Highlight, type PrismTheme } from "prism-react-renderer";
import { splitStreamingMarkdown } from "./streaming-markdown";

const remarkPlugins = [remarkGfm, remarkMath];
const rehypePlugins = [rehypeKatex];

const codeTheme: PrismTheme = {
  plain: { color: "var(--color-text)", backgroundColor: "transparent" },
  styles: [
    { types: ["comment", "prolog", "doctype", "cdata"], style: { color: "var(--color-text-muted)" } },
    { types: ["punctuation"], style: { color: "var(--color-text-subtle)" } },
    { types: ["keyword", "selector", "important", "atrule"], style: { color: "var(--color-action)" } },
    { types: ["string", "attr-value"], style: { color: "var(--color-success)" } },
    { types: ["number", "boolean", "function", "class-name"], style: { color: "var(--color-warning)" } },
  ],
};

const languageAliases: Record<string, string> = {
  js: "javascript", ts: "typescript", py: "python", sh: "bash",
  shell: "bash", yml: "yaml", md: "markdown", "c++": "cpp",
};

function CodeBlock({ code, language }: { code: string; language: string }) {
  const [copyState, setCopyState] = useState<"ready" | "copied" | "error">("ready");

  useEffect(() => {
    if (copyState === "ready") return;
    const timer = window.setTimeout(() => setCopyState("ready"), 2000);
    return () => window.clearTimeout(timer);
  }, [copyState]);

  const name = languageAliases[language.toLowerCase()] || language.toLowerCase() || "text";

  async function copyCode() {
    try {
      await navigator.clipboard.writeText(code);
      setCopyState("copied");
    } catch {
      setCopyState("error");
    }
  }

  return (
    <div className="chat-code-block">
      <div className="chat-code-header">
        <span>{language || "Code"}</span>
        <button type="button" onClick={() => void copyCode()}>
          {copyState === "copied" ? "Copied" : copyState === "error" ? "Copy failed" : "Copy"}
        </button>
      </div>
      <Highlight code={code} language={name} theme={codeTheme}>
        {({ tokens, getLineProps, getTokenProps }) => (
          <pre className="chat-code-content">
            {tokens.map((line, index) => (
              <span key={index} {...getLineProps({ line, className: "chat-code-line" })}>
                {line.map((token, tokenIndex) => (
                  <span key={tokenIndex} {...getTokenProps({ token })} />
                ))}
              </span>
            ))}
          </pre>
        )}
      </Highlight>
    </div>
  );
}

function childText(value: ReactNode): string {
  if (typeof value === "string" || typeof value === "number") return String(value);
  if (Array.isArray(value)) return value.map(childText).join("");
  if (isValidElement<{ children?: ReactNode }>(value)) return childText(value.props.children);
  return "";
}

function CodePre({ children }: { children?: ReactNode }) {
  const codeElement = Children.toArray(children)[0];
  if (!isValidElement<{ className?: string; children?: ReactNode }>(codeElement)) {
    return <pre>{children}</pre>;
  }
  const className = codeElement.props.className || "";
  const language = /(?:^|\s)language-([^\s]+)/.exec(className)?.[1] || "";
  const code = childText(codeElement.props.children).replace(/\n$/, "");
  return <CodeBlock code={code} language={language} />;
}

const components: Components = {
  pre: CodePre,
  img: ({ alt }) => <span>{alt || ""}</span>,
};

export function ChatMarkdown({ text, streaming = false }: { text: string; streaming?: boolean }) {
  const parts = streaming
    ? splitStreamingMarkdown(text)
    : { markdown: text, pending: "", kind: null };

  return (
    <div className="chat-markdown">
      {parts.markdown && (
        <Markdown remarkPlugins={remarkPlugins} rehypePlugins={rehypePlugins} components={components}>
          {parts.markdown}
        </Markdown>
      )}
      {parts.pending && (
        <pre className={`chat-markdown-pending ${parts.kind === "math" ? "is-math" : ""}`}>
          {parts.pending}
        </pre>
      )}
    </div>
  );
}
