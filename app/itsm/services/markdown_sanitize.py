"""Conservative markdown → HTML with an allowlist sanitize pass (no external deps).

Supports a useful subset: headings, paragraphs, emphasis, lists, links (http/https
only), inline code, fenced code blocks, and hard line breaks. Anything outside
the allowlist is escaped / stripped to mitigate XSS.
"""

from __future__ import annotations

import html
import re
from typing import Iterable

BODY_FORMATS: tuple[str, ...] = ("plain", "markdown")

_ALLOWED_TAGS = frozenset(
    {
        "p",
        "br",
        "strong",
        "em",
        "code",
        "pre",
        "ul",
        "ol",
        "li",
        "h1",
        "h2",
        "h3",
        "h4",
        "a",
        "blockquote",
    }
)
_ALLOWED_ATTRS = {
    "a": frozenset({"href", "title", "rel", "target"}),
}

_LINK_RE = re.compile(
    r"\[([^\]]+)\]\((https?://[^)\s]+)(?:\s+\"([^\"]*)\")?\)"
)
_BOLD_RE = re.compile(r"\*\*(.+?)\*\*")
_ITALIC_RE = re.compile(r"(?<!\*)\*(?!\*)(.+?)(?<!\*)\*(?!\*)")
_CODE_RE = re.compile(r"`([^`]+)`")
_FENCE_RE = re.compile(r"```([\w+-]*)\n([\s\S]*?)```", re.MULTILINE)
_HEADING_RE = re.compile(r"^(#{1,4})\s+(.+)$")
_UL_RE = re.compile(r"^[-*+]\s+(.+)$")
_OL_RE = re.compile(r"^(\d+)\.\s+(.+)$")
_BQ_RE = re.compile(r"^>\s?(.*)$")
_TAG_RE = re.compile(r"</?([a-zA-Z0-9]+)(\s[^>]*)?>")
_ATTR_RE = re.compile(
    r"""([a-zA-Z_:][-a-zA-Z0-9_:]*)\s*=\s*("([^"]*)"|'([^']*)'|([^\s"'=<>`]+))"""
)
_DANGEROUS_SCHEME = re.compile(r"^\s*(javascript|data|vbscript)\s*:", re.I)


def render_plain(text: str) -> str:
    """Escape plain text and preserve newlines as <br/>."""
    escaped = html.escape(text or "", quote=True)
    return escaped.replace("\n", "<br/>\n")


def _inline(text: str) -> str:
    """Escape then apply inline markdown transforms."""
    # Protect code spans first via placeholders.
    codes: list[str] = []

    def _code_sub(m: re.Match[str]) -> str:
        codes.append(f"<code>{html.escape(m.group(1), quote=True)}</code>")
        return f"\x00CODE{len(codes) - 1}\x00"

    working = _CODE_RE.sub(_code_sub, text)
    working = html.escape(working, quote=True)

    def _link_sub(m: re.Match[str]) -> str:
        label = m.group(1)
        # label already escaped as part of working
        href = m.group(2)
        title = m.group(3)
        # Re-parse from original-ish: href was escaped; unescape for validation
        href_raw = html.unescape(href)
        if _DANGEROUS_SCHEME.search(href_raw) or not href_raw.lower().startswith(
            ("http://", "https://")
        ):
            return label
        title_attr = f' title="{html.escape(title or "", quote=True)}"' if title else ""
        return (
            f'<a href="{html.escape(href_raw, quote=True)}" rel="noopener noreferrer" '
            f'target="_blank"{title_attr}>{label}</a>'
        )

    # Links in escaped text: brackets/parens still present; URL chars mostly unchanged.
    working = re.sub(
        r"\[([^\]]+)\]\((https?://[^)\s]+)(?:\s+&quot;([^&]*)&quot;)?\)",
        _link_sub,
        working,
    )
    working = re.sub(r"\*\*(.+?)\*\*", r"<strong>\1</strong>", working)
    working = re.sub(r"(?<!\*)\*(?!\*)(.+?)(?<!\*)\*(?!\*)", r"<em>\1</em>", working)
    for i, code_html in enumerate(codes):
        working = working.replace(f"\x00CODE{i}\x00", code_html)
    return working


def _sanitize_fragment(fragment: str) -> str:
    """Strip disallowed tags/attrs from a small HTML fragment we produced."""

    def _repl(match: re.Match[str]) -> str:
        full = match.group(0)
        tag = match.group(1).lower()
        closing = full.startswith("</")
        if tag not in _ALLOWED_TAGS:
            return ""
        if closing:
            return f"</{tag}>"
        attrs_raw = match.group(2) or ""
        allowed = _ALLOWED_ATTRS.get(tag, frozenset())
        kept: list[str] = []
        for am in _ATTR_RE.finditer(attrs_raw):
            name = am.group(1).lower()
            if name not in allowed:
                continue
            val = am.group(3) if am.group(3) is not None else (
                am.group(4) if am.group(4) is not None else am.group(5) or ""
            )
            if name == "href" and (
                _DANGEROUS_SCHEME.search(val)
                or not val.lower().startswith(("http://", "https://"))
            ):
                continue
            kept.append(f'{name}="{html.escape(val, quote=True)}"')
        if tag == "a" and "rel=" not in " ".join(kept):
            kept.append('rel="noopener noreferrer"')
        attr_str = (" " + " ".join(kept)) if kept else ""
        return f"<{tag}{attr_str}>"

    return _TAG_RE.sub(_repl, fragment)


def render_markdown(text: str) -> str:
    """Convert markdown subset to sanitized HTML."""
    raw = (text or "").replace("\r\n", "\n").replace("\r", "\n")
    # Extract fenced code blocks.
    fences: list[str] = []

    def _fence_sub(m: re.Match[str]) -> str:
        code = html.escape(m.group(2).rstrip("\n"), quote=True)
        fences.append(f"<pre><code>{code}</code></pre>")
        return f"\x00FENCE{len(fences) - 1}\x00"

    raw = _FENCE_RE.sub(_fence_sub, raw)
    lines = raw.split("\n")
    out: list[str] = []
    i = 0
    while i < len(lines):
        line = lines[i]
        if line.startswith("\x00FENCE") and line.endswith("\x00"):
            idx = int(line[6:-1])
            out.append(fences[idx])
            i += 1
            continue
        hm = _HEADING_RE.match(line)
        if hm:
            level = len(hm.group(1))
            out.append(f"<h{level}>{_inline(hm.group(2).strip())}</h{level}>")
            i += 1
            continue
        bq = _BQ_RE.match(line)
        if bq:
            chunks = [bq.group(1)]
            i += 1
            while i < len(lines):
                bm = _BQ_RE.match(lines[i])
                if not bm:
                    break
                chunks.append(bm.group(1))
                i += 1
            inner = "<br/>".join(_inline(c) for c in chunks)
            out.append(f"<blockquote><p>{inner}</p></blockquote>")
            continue
        if _UL_RE.match(line):
            items: list[str] = []
            while i < len(lines):
                um = _UL_RE.match(lines[i])
                if not um:
                    break
                items.append(f"<li>{_inline(um.group(1))}</li>")
                i += 1
            out.append("<ul>" + "".join(items) + "</ul>")
            continue
        if _OL_RE.match(line):
            items = []
            while i < len(lines):
                om = _OL_RE.match(lines[i])
                if not om:
                    break
                items.append(f"<li>{_inline(om.group(2))}</li>")
                i += 1
            out.append("<ol>" + "".join(items) + "</ol>")
            continue
        if not line.strip():
            i += 1
            continue
        # Paragraph: gather until blank.
        para: list[str] = [line]
        i += 1
        while i < len(lines) and lines[i].strip() and not _HEADING_RE.match(lines[i]) and not _UL_RE.match(lines[i]) and not _OL_RE.match(lines[i]) and not _BQ_RE.match(lines[i]) and not lines[i].startswith("\x00FENCE"):
            para.append(lines[i])
            i += 1
        out.append("<p>" + "<br/>".join(_inline(p) for p in para) + "</p>")
    html_out = "\n".join(out)
    return _sanitize_fragment(html_out)


def render_body(body: str, *, body_format: str = "plain") -> str:
    fmt = (body_format or "plain").strip().lower()
    if fmt == "markdown":
        return render_markdown(body)
    return render_plain(body)


def attach_rendered_html(doc: dict | None) -> dict | None:
    """Add ``body_html`` to a serialized knowledge article document."""
    if not doc:
        return doc
    fmt = str(doc.get("body_format") or "plain")
    doc["body_html"] = render_body(str(doc.get("body") or ""), body_format=fmt)
    return doc


def attach_rendered_html_many(items: Iterable[dict]) -> list[dict]:
    return [attach_rendered_html(dict(item)) or item for item in items]
