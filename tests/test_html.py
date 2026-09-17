from papis_ask.html import clean_html, parse_html
import pytest


def test_removes_explicit_site_chrome_not_article_structure():
    source = """<div role="banner">Advertisement</div><nav>Menu<input></nav>
    <form>Log in</form><article><header><h1>Research</h1></header>
    <p>Equation $x^2$ &amp; science.</p><aside>Scientific sidebar</aside>
    <table><tr><td>Results</td></tr></table><footer>References</footer></article>"""
    result = clean_html(source)
    for chrome in ("Advertisement", "Menu", "Log in"):
        assert chrome not in result
    for content in (
        "Research",
        "$x^2$",
        "&amp;",
        "Scientific sidebar",
        "Results",
        "References",
    ):
        assert content in result


def test_unmarked_html_is_not_guessed_away():
    source = '<div class="menu">A paper about menu design</div>'
    assert clean_html(source) == source


def test_unclosed_navigation_falls_back_to_avoid_losing_article():
    source = "<nav>Menu<p>Article following malformed navigation"
    assert clean_html(source) == source


def test_entities_and_void_elements_do_not_corrupt_filter_state():
    assert (
        clean_html('<nav><img src="x"/>Menu</nav><p>&#945; &amp;</p>')
        == "<p>&#945; &amp;</p>"
    )


def test_parsed_html_keeps_math_and_does_not_modify_source(tmp_path):
    path = tmp_path / "paper.html"
    source = "<nav>Log in</nav><article><h1>Paper</h1><p>Math $x^2$.</p></article>"
    path.write_text(source)
    result = parse_html(path)
    assert "Log in" not in result.content
    assert "$x^2$" in result.content
    assert result.metadata.total_parsed_text_length == len(result.content)
    assert path.read_text() == source


@pytest.mark.asyncio
async def test_html_ingestion_embeds_filtered_text_and_stamps_source(
    tmp_path, monkeypatch
):
    from types import SimpleNamespace
    from unittest.mock import AsyncMock
    from paperqa import Settings
    from papis_ask import main, config

    path = tmp_path / "paper.html"
    path.write_text("<nav>Login</nav><article>Evidence $x^2$.</article>")
    index = SimpleNamespace(aadd_texts=AsyncMock(return_value=True))
    metadata = AsyncMock(return_value="Paper")
    monkeypatch.setattr(main, "update_index_metadata", metadata)
    monkeypatch.setattr(main, "_embeddings_to_float32", lambda docs: None)
    monkeypatch.setattr(config, "get_chunk_params", lambda: (5000, 250))
    monkeypatch.setattr(config, "get_embedding_model", lambda: "test")
    result = await main.add_file_to_index(
        path, {"papis_id": "abc", "ref": "Paper"}, index, None, Settings()
    )
    assert result == "Paper"
    chunks = index.aadd_texts.call_args.args[0]
    assert all("Login" not in t.text for t in chunks)
    assert any("$x^2$" in t.text for t in chunks)
    assert metadata.call_args.kwargs["chunk_source"] == "html"
