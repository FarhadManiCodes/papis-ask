"""Where a paper's embeddings sidecar lives."""

from pathlib import Path

from papis_ask.index_store import embeddings_json_path
from papis_ask.refinery import chunks_json_path


class TestEmbeddingsJsonPath:
    def test_appends_rather_than_replacing_the_suffix(self):
        assert (
            embeddings_json_path("/lib/kalman-1960/paper.pdf").name
            == "paper.pdf.embeddings.json"
        )

    def test_same_stem_different_types_do_not_collide(self):
        """A papis entry can hold both a .pdf and a .html of the same article.

        `with_suffix()` would map both to "paper.embeddings.json" and one would
        clobber the other -- which is exactly the bug that did bite the sibling
        chunks.json path.
        """
        pdf = embeddings_json_path("/lib/mastrone-2021/paper.pdf")
        html = embeddings_json_path("/lib/mastrone-2021/paper.html")
        assert pdf != html

    def test_the_two_sidecars_never_collide_with_each_other(self):
        """refinery owns <stem>.chunks.json, we own <file>.embeddings.json."""
        pdf = Path("/lib/x/paper.pdf")
        assert embeddings_json_path(pdf) != chunks_json_path(pdf)
