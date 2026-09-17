"""Conservative removal of explicitly marked website chrome before chunking."""

from html.parser import HTMLParser


class _ChromeFilter(HTMLParser):
    # Do not guess from CSS classes, link density or words such as 'references'.
    # Article headers, footnotes, tables and scientific sidebars stay intact.
    void_tags = {
        "area",
        "base",
        "br",
        "col",
        "embed",
        "hr",
        "img",
        "input",
        "link",
        "meta",
        "param",
        "source",
        "track",
        "wbr",
    }

    def __init__(self):
        super().__init__(convert_charrefs=False)
        self.stack = []
        self.output = []

    @property
    def hidden(self):
        return bool(self.stack and self.stack[-1][1])

    def handle_starttag(self, tag, attrs):
        role = dict(attrs).get("role", "") or ""
        in_article = any(t == "article" for t, _ in self.stack)
        hidden = (
            self.hidden
            or tag in {"nav", "form"}
            or (
                not in_article
                and bool(
                    set(role.lower().split())
                    & {"navigation", "banner", "search", "contentinfo"}
                )
            )
        )
        if not hidden:
            self.output.append(self.get_starttag_text())
        if tag not in self.void_tags:
            self.stack.append((tag, hidden))

    def handle_endtag(self, tag):
        if not self.hidden:
            self.output.append(f"</{tag}>")
        for i in range(len(self.stack) - 1, -1, -1):
            if self.stack[i][0] == tag:
                del self.stack[i:]
                break

    def handle_startendtag(self, tag, attrs):
        self.handle_starttag(tag, attrs)
        if tag not in self.void_tags:
            self.handle_endtag(tag)

    def handle_data(self, data):
        if not self.hidden:
            self.output.append(data)

    def handle_entityref(self, name):
        self.handle_data(f"&{name};")

    def handle_charref(self, name):
        self.handle_data(f"&#{name};")


def clean_html(source: str) -> str:
    parser = _ChromeFilter()
    parser.feed(source)
    parser.close()
    # A malformed, unclosed navigation element may contain the article. Do not
    # silently discard its remainder: fall back to the original HTML.
    if parser.hidden:
        return source
    return "".join(parser.output)


def parse_html(path):
    from html2text import html2text
    from paperqa.readers import parse_text

    parsed = parse_text(path)
    content = html2text(clean_html(parsed.content))
    return parsed.model_copy(
        update={
            "content": content,
            "metadata": parsed.metadata.model_copy(
                update={
                    "name": "html-semantic-clean-v1",
                    "total_parsed_text_length": len(content),
                    "parsing_libraries": ["html.parser", "html2text"],
                }
            ),
        }
    )
