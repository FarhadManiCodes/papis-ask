"""contrib/eval_questions.py: the question set and the offline summary helper."""

import importlib.util
import json
from pathlib import Path

_PATH = Path(__file__).parents[1] / "contrib" / "eval_questions.py"
_SPEC = importlib.util.spec_from_file_location("eval_questions", _PATH)
eq = importlib.util.module_from_spec(_SPEC)
_SPEC.loader.exec_module(eq)


def test_question_set_is_well_formed():
    questions = json.loads((_PATH.parent / "eval_questions.json").read_text())
    assert len(questions) == 6
    assert all(q["question"] and ("scope" in q) for q in questions)


def test_summarize_groups_cited_pages_by_ref():
    answer = {
        "answer": "one two three",
        "references": [
            {"papis_id": "a1", "pages": "56"},
            {"papis_id": "a1", "pages": "57"},
            {"papis_id": "b2", "pages": "3"},
        ],
        "contexts": [{"score": 9}, {"score": 2}],
    }
    s = eq.summarize(answer, {"a1": "Nocedal_2006"})
    assert s == {"words": 3, "scores": [9, 2], "cited": {"Nocedal_2006": ["56", "57"], "b2": ["3"]}}
