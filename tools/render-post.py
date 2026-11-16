#!/usr/bin/env python3
"""
Render a series post (markdown) into a PaperMod-styled page for the blog.

Reuses an existing published post as the HTML skeleton, so the header, theme
toggle, sidebar TOC, MathJax, and highlight.js setup stay identical across posts.

Supports: headings with unique anchors, paragraphs, bullet lists, tables,
fenced code, $$ display math (block and single-line), images with an italic
caption line (rendered as <figure>), blockquotes, inline code/bold/italic/links.

Usage:
  python tools/render-post.py \
      --md "/path/to/post.md" --slug 2026-08-20-architecture \
      --title "Architecture: Assembling a Modern Dense LLM" \
      --date 2026-08-20 --pretty-date "August 20, 2026" \
      --desc "..." --tw-desc "..." --ld-desc "..." --ld-body "..." \
      --keywords "architecture,transformer" \
      --prev-slug 2026-07-05-tokenizer --prev-title "Tokenizers: ..."
"""

from __future__ import annotations

import argparse
import re
import urllib.parse
from pathlib import Path

SITE = Path(__file__).resolve().parents[1]
SITE_URL = "https://backpropolis.github.io"
SKELETON = SITE / "posts" / "2026-07-05-tokenizer" / "index.html"

# Strings in the skeleton that identify the previous post's metadata.
SK = {
    "slug": "2026-07-05-tokenizer",
    "date": "2026-07-05",
    "title": "Tokenizers: From Characters to Byte-Level BPE",
    "short": "Tokenizers",
    "meta_line": "Date: July 5, 2026  |  Estimated Reading Time: 11 min",
    "keywords": "tokenizer, bpe, tokenization, subword, deep-learning, long-read",
    "ld_keywords": '    "tokenizer", "bpe", "tokenization", "subword", "deep-learning", "long-read"',
    "hashtags": "hashtags=tokenizer%2cbpe%2ctokenization%2csubword%2cdeep-learning%2clong-read",
}


# Repo folder (as it appears in markdown links) -> published slug on the site.
# Markdown keeps repo-relative ".md" links so they work on GitHub; the web build
# rewrites them to the corresponding post URL.
POST_LINKS = {
    "0.neural-net": "2026-03-23-neural-net",
    "1. self-attn": "2026-03-30-self-attn",
    "2. attn-variants": "2026-04-09-attn-variant",
    "3. positional_encoding": "2026-05-06-positional-encoding",
    "4. normalization": "2026-06-09-normalization",
    "5. activations": "2026-06-29-activations",
    "6. tokenizers": "2026-07-05-tokenizer",
    "7. architecture": "2026-08-20-architecture",
}


def resolve_link(url: str) -> str:
    """Rewrite ../<repo folder>/<file>.md into the published post URL."""
    m = re.match(r"^\.\./([^/]+)/[^/]+\.md$", url)
    if not m:
        return url
    folder = urllib.parse.unquote(m.group(1))
    slug = POST_LINKS.get(folder)
    if slug is None:
        raise SystemExit(f"unknown post folder in link: {folder!r} (add it to POST_LINKS)")
    return f"{SITE_URL}/posts/{slug}/"

# --------------------------------------------------------------------------- inline
def slugify(text: str) -> str:
    return "".join(c if (c.isalnum() and ord(c) < 128) else "-" if c in " -" else "" for c in text.lower())


def smart(t: str) -> str:
    t = re.sub(r"(\w)'(\w)", r"\1’\2", t)
    t = re.sub(r"(\w)'", r"\1’", t)
    out = []
    for i, ch in enumerate(t):
        if ch == '"':
            prev = t[i - 1] if i else " "
            out.append("“" if (i == 0 or prev in " \t([{>/") else "”")
        else:
            out.append(ch)
    return "".join(out)


def esc(s: str) -> str:
    return s.replace("&", "&amp;").replace("<", "&lt;").replace(">", "&gt;")


def inline(text: str) -> str:
    """Inline markdown -> HTML. Code spans and links are protected from escaping."""
    codes: list[str] = []
    text = re.sub(
        r"`([^`]+)`",
        lambda m: codes.append("<code>" + esc(m.group(1)).replace('"', "&quot;") + "</code>")
        or f"\x00{len(codes)-1}\x00",
        text,
    )
    links: list[tuple[str, str]] = []
    text = re.sub(
        r"(?<!!)\[([^\]]+)\]\(([^)]+)\)",
        lambda m: links.append((m.group(1), m.group(2))) or f"\x01{len(links)-1}\x01",
        text,
    )
    text = esc(text)
    text = re.sub(r"\*\*([^*]+)\*\*", r"<strong>\1</strong>", text)
    text = re.sub(r"\*([^*]+)\*", r"<em>\1</em>", text)
    text = smart(text)
    for i, (label, url) in enumerate(links):
        href = resolve_link(url).replace("&", "&amp;")
        text = text.replace(f"\x01{i}\x01", f'<a href="{href}">{smart(esc(label))}</a>')
    for i, c in enumerate(codes):
        text = text.replace(f"\x00{i}\x00", c)
    return text


# --------------------------------------------------------------------------- blocks
def render_markdown(md: str) -> tuple[str, list[tuple[str, str]]]:
    lines = md.split("\n")
    html: list[str] = []
    toc: list[tuple[str, str]] = []
    seen: dict[str, int] = {}
    i = 0

    def heading(level: int, text: str) -> str:
        base = slugify(text)
        seen[base] = seen.get(base, 0) + 1
        anchor = base if seen[base] == 1 else f"{base}-{seen[base]-1}"
        html.append(
            f'<h{level} id="{anchor}">{inline(text)}'
            f'<a hidden class="anchor" aria-hidden="true" href="#{anchor}">#</a></h{level}>'
        )
        return anchor

    while i < len(lines):
        line = lines[i].rstrip()

        if not line or line == "---":
            i += 1
            continue

        # display math: a lone $$ opens a block, $$...$$ on one line is inline-block
        if line == "$$":
            buf, i = [], i + 1
            while i < len(lines) and lines[i].rstrip() != "$$":
                buf.append(lines[i])
                i += 1
            i += 1
            html.append("<p>\n$$\n" + "\n".join(buf) + "\n$$\n</p>")
            continue
        if line.startswith("$$") and line.endswith("$$") and len(line) > 4:
            html.append(f"<p>\n{line}\n</p>")
            i += 1
            continue

        # fenced code
        m = re.match(r"^```(\w*)\s*$", line)
        if m:
            lang, i = m.group(1), i + 1
            buf = []
            while i < len(lines) and not re.match(r"^```\s*$", lines[i]):
                buf.append(lines[i])
                i += 1
            i += 1
            cls = f' class="language-{lang}"' if lang else ""
            html.append(f'<pre tabindex="0"><code{cls}>' + esc("\n".join(buf)).replace('"', "&quot;") + "</code></pre>")
            continue

        # heading
        m = re.match(r"^(#{1,6})\s+(.*)$", line)
        if m:
            level, text = len(m.group(1)), m.group(2).strip()
            if level == 1:  # page title lives in <h1 class="post-title">
                i += 1
                continue
            anchor = heading(level, text)
            if level == 2:
                toc.append((anchor, text))
            i += 1
            continue

        # image (+ optional italic caption on the next line) -> figure
        m = re.match(r"^!\[([^\]]*)\]\(([^)]+)\)\s*$", line)
        if m:
            alt, src = m.group(1), m.group(2)
            cap = ""
            if i + 1 < len(lines):
                cm = re.match(r"^\*(.+)\*\s*$", lines[i + 1].rstrip())
                if cm:
                    cap, i = cm.group(1), i + 1
            fig = f'<figure>\n    <img src="{src}" alt="{esc(alt)}" />'
            if cap:
                fig += f"\n    <figcaption>{inline(cap)}</figcaption>"
            html.append(fig + "\n</figure>")
            i += 1
            continue

        # table
        if line.startswith("|") and i + 1 < len(lines) and re.match(r"^\|[\s:|-]+\|$", lines[i + 1].rstrip()):
            def cells(row: str) -> list[str]:
                return [c.strip() for c in row.strip().strip("|").split("|")]

            head = cells(line)
            i += 2
            body = []
            while i < len(lines) and lines[i].rstrip().startswith("|"):
                body.append(cells(lines[i].rstrip()))
                i += 1
            out = ["<table>", "<thead><tr>"]
            out += [f"<th>{inline(c)}</th>" for c in head]
            out.append("</tr></thead>")
            out.append("<tbody>")
            for row in body:
                out.append("<tr>" + "".join(f"<td>{inline(c)}</td>" for c in row) + "</tr>")
            out += ["</tbody>", "</table>"]
            html.append("\n".join(out))
            continue

        # blockquote
        if line.startswith(">"):
            buf = []
            while i < len(lines) and lines[i].lstrip().startswith(">"):
                buf.append(re.sub(r"^\s*>\s?", "", lines[i]))
                i += 1
            html.append("<blockquote><p>" + inline(" ".join(x.strip() for x in buf if x.strip())) + "</p></blockquote>")
            continue

        # bullet list
        if re.match(r"^-\s+", line):
            items = []
            while i < len(lines) and re.match(r"^-\s+", lines[i].rstrip()):
                items.append(re.sub(r"^-\s+", "", lines[i].rstrip()))
                i += 1
            html.append("<ul>")
            html += [f"<li>{inline(it)}</li>" for it in items]
            html.append("</ul>")
            continue

        # paragraph
        buf, i = [line], i + 1
        while i < len(lines):
            nxt = lines[i].rstrip()
            if not nxt or nxt in ("---", "$$") or re.match(r"^(#{1,6})\s|^```|^!\[|^-\s|^\|", nxt) or nxt.startswith(">"):
                break
            buf.append(nxt)
            i += 1
        html.append("<p>" + inline(" ".join(buf)) + "</p>")

    return "\n".join(html), toc


# --------------------------------------------------------------------------- page
def build(args) -> Path:
    md = Path(args.md).read_text(encoding="utf-8")
    content, toc = render_markdown(md)

    words = len(re.sub(r"`[^`]*`", "", md).split())
    reading = f"{max(1, round(words / 220))} min"

    toc_html = ['<div class="inner"><ul>']
    for anchor, text in toc:
        aria = re.sub(r"<[^>]+>", "", smart(esc(text)))
        toc_html.append("                <li>")
        toc_html.append(f'                    <a href="#{anchor}" aria-label="{aria}">{inline(text)}</a></li>')
    toc_html.append("            </ul>\n        </div>")
    toc_html = "\n".join(toc_html)

    tpl = SKELETON.read_text(encoding="utf-8")
    short = args.title.split(":")[0]

    tpl = tpl.replace(SK["slug"], args.slug)
    tpl = tpl.replace(f'{SK["date"]}T00:00:00', f"{args.date}T00:00:00")
    tpl = tpl.replace(f'"datePublished": "{SK["date"]}', f'"datePublished": "{args.date}')
    tpl = tpl.replace(f'"dateModified": "{SK["date"]}', f'"dateModified": "{args.date}')
    tpl = tpl.replace(SK["meta_line"], f"Date: {args.pretty_date}  |  Estimated Reading Time: {reading}")

    tpl = tpl.replace(urllib.parse.quote(SK["title"]), urllib.parse.quote(args.title))
    tpl = tpl.replace(SK["title"], args.title)
    tpl = tpl.replace(f'share {SK["short"]} on', f"share {short} on")
    tpl = tpl.replace(f'&amp;summary={SK["short"]}', f"&amp;summary={short}")

    kw = ", ".join(k.strip() for k in args.keywords.split(","))
    tpl = tpl.replace(SK["keywords"], kw)
    tpl = tpl.replace(SK["ld_keywords"], "    " + ", ".join(f'"{k.strip()}"' for k in args.keywords.split(",")))
    tpl = tpl.replace(SK["hashtags"], "hashtags=" + "%2c".join(k.strip() for k in args.keywords.split(",")))

    tpl = re.sub(r'(<meta name="description" content=")[^"]*(")', lambda m: m.group(1) + args.desc + m.group(2), tpl)
    tpl = re.sub(r'(<meta property="og:description" content=")[^"]*(")', lambda m: m.group(1) + args.desc + m.group(2), tpl)
    tpl = re.sub(r'(<meta name="twitter:description" content=")[^"]*(")', lambda m: m.group(1) + args.tw_desc + m.group(2), tpl)
    tpl = re.sub(r'("description": ")[^"]*(",)', lambda m: m.group(1) + args.ld_desc + m.group(2), tpl, count=1)
    tpl = re.sub(r'("articleBody": ")[^"]*(",)', lambda m: m.group(1) + args.ld_body + m.group(2), tpl, count=1)
    tpl = re.sub(r'("wordCount" : ")\d+(")', lambda m: m.group(1) + str(words) + m.group(2), tpl)

    a = tpl.index('<div class="inner"><ul>')
    b = tpl.index("</ul>\n        </div>", a) + len("</ul>\n        </div>")
    tpl = tpl[:a] + toc_html + tpl[b:]

    start = '<div class="post-content">'
    a = tpl.index(start) + len(start)
    end = '\n\n\n  </div>\n\n  <footer class="post-footer">'
    b = tpl.index(end)
    tpl = tpl[:a] + content + end + tpl[b + len(end):]

    tags = "\n".join(
        f'      <li><a href="../../tags/?tag={t.strip()}">{t.strip().capitalize()}</a></li>'
        for t in args.tags.split(",")
    )
    tpl = re.sub(
        r'    <ul class="post-tags">\n.*?\n    </ul>',
        '    <ul class="post-tags">\n' + tags + "\n    </ul>",
        tpl,
        flags=re.S,
    )
    tpl = re.sub(
        r'(<a class="prev" href="\.\./\.\./posts/)[^/]+(/">.*?<span>)[^<]*(</span>)',
        lambda m: m.group(1) + args.prev_slug + m.group(2) + args.prev_title + m.group(3),
        tpl,
        flags=re.S,
    )

    # Tall figures (a full architecture diagram) would otherwise fill several
    # screens at full column width, so cap figure height and centre what is left.
    tpl = tpl.replace(
        ".post-content pre code{white-space:pre;text-wrap:nowrap;word-break:normal;overflow-wrap:normal}",
        ".post-content pre code{white-space:pre;text-wrap:nowrap;word-break:normal;overflow-wrap:normal}\n"
        ".post-content figure img{max-height:80vh;width:auto;max-width:100%;display:block;margin:0 auto}",
    )

    out_dir = SITE / "posts" / args.slug
    (out_dir / "asset").mkdir(parents=True, exist_ok=True)
    out = out_dir / "index.html"
    out.write_text(tpl, encoding="utf-8")
    print(f"words={words} reading={reading} sections={len(toc)} -> {out}")
    return out


if __name__ == "__main__":
    p = argparse.ArgumentParser()
    for flag in ("md", "slug", "title", "date", "pretty-date", "desc", "tw-desc",
                 "ld-desc", "ld-body", "keywords", "tags", "prev-slug", "prev-title"):
        p.add_argument("--" + flag, required=True)
    build(p.parse_args())
