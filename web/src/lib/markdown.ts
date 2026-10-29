import DOMPurify from "dompurify";
import { marked } from "marked";

const ALLOWED_TAGS = [
  "p", "br", "b", "strong", "i", "em", "u", "s", "del",
  "code", "pre", "blockquote", "a", "ul", "ol", "li", "h1", "h2", "h3", "hr", "span",
];

const ALLOWED_ATTR = ["href", "title", "class"];

const MENTION_RE = /(^|[\s([{"'])@([a-zA-Z0-9_.-]{2,64})/g;

export interface RenderOptions {
  myUsername?: string;
  highlightMentions?: boolean;
}

export function renderMessageHtml(body: string, options: RenderOptions = {}): string {
  if (!body) return "";
  const raw = marked.parse(body, { async: false, gfm: true, breaks: true }) as string;
  const clean = DOMPurify.sanitize(raw, {
    ALLOWED_TAGS,
    ALLOWED_ATTR,
    ALLOWED_URI_REGEXP: /^(?:https?:|mailto:)/i,
    FORBID_ATTR: ["style"],
  });
  if (!options.highlightMentions) return clean;

  const tpl = document.createElement("template");
  tpl.innerHTML = clean;
  wrapMentions(tpl.content, options.myUsername || "");
  return tpl.innerHTML;
}

function wrapMentions(root: ParentNode, myUsername: string) {
  const walker = document.createTreeWalker(root, NodeFilter.SHOW_TEXT);
  const targets: Text[] = [];
  let node = walker.nextNode();
  while (node) {
    if (node.nodeValue && node.nodeValue.includes("@")) targets.push(node as Text);
    node = walker.nextNode();
  }
  for (const textNode of targets) {
    const value = textNode.nodeValue || "";
    const fragment = document.createDocumentFragment();
    let lastIndex = 0;
    let match: RegExpExecArray | null;
    MENTION_RE.lastIndex = 0;
    let found = false;
    while ((match = MENTION_RE.exec(value)) !== null) {
      found = true;
      const prefix = match[1];
      const username = match[2];
      const start = match.index + prefix.length;
      fragment.append(value.slice(lastIndex, start));
      const span = document.createElement("span");
      span.className =
        "mention" + (username === myUsername || username === "all" ? " me" : "");
      span.textContent = "@" + username;
      fragment.append(span);
      lastIndex = start + 1 + username.length;
    }
    if (!found) continue;
    fragment.append(value.slice(lastIndex));
    textNode.replaceWith(fragment);
  }
}

export function plainPreview(body: string): string {
  const clean = body
    .replace(/```[\s\S]*?```/g, "[код]")
    .replace(/`([^`]+)`/g, "$1")
    .replace(/!\[([^\]]*)]\(([^)]+)\)/g, "[изображение]")
    .replace(/\[([^\]]+)]\(([^)]+)\)/g, "$1")
    .replace(/[*_~#>]+/g, "");
  return clean.trim();
}
