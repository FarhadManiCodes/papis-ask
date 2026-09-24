#!/usr/bin/env python3
"""Answer a fixed question set with two papis configurations and compare the runs.

Used to decide whether to change `[ask] llm` / `summary-llm`: both runs query the same
index, so the models are the only difference. Each answer is saved as JSON for reading
side by side, and a summary compares what can be counted:

  - evidence relevance scores (a summary model that scores nearly everything 10/10 is
    not ranking anything)
  - cited documents and pages, per question
  - answer length and wall time

Whether an answer is faithful still has to be judged by reading it against the cited
pages; the summary only points at where to look.

    contrib/eval_questions.py --config-b /tmp/papis-config-new --out /tmp/qa-eval

`--config-a` defaults to the live papis config. Make a candidate config by copying it
and changing only the model lines. Each run makes paid calls: about 11 LLM calls per
question (one summary per evidence chunk, one answer).
"""

import argparse
import json
import shlex
import subprocess
import time
from collections import defaultdict
from pathlib import Path

HERE = Path(__file__).resolve().parent
SECRETS = Path("~/.config/secrets/papis.env").expanduser()


def _ask(
    papis: list[str], config: Path | None, item: dict
) -> tuple[dict | None, float, str]:
    cmd = papis + (["--config", str(config)] if config else [])
    cmd += ["ask", "query", "-o", "json"]
    if item.get("scope"):
        cmd += ["-s", item["scope"]]
    cmd.append(item["question"])
    start = time.monotonic()
    # keys are sourced in a subshell, as `pask` does, so this process never reads them
    wrapped = ["bash", "-c", 'source "$1" 2>/dev/null; shift; exec "$@"', "_", str(SECRETS), *cmd]
    proc = subprocess.run(wrapped, capture_output=True, text=True)
    elapsed = time.monotonic() - start
    try:
        return json.loads(proc.stdout), elapsed, proc.stderr
    except json.JSONDecodeError:
        return None, elapsed, proc.stderr


def _refs_by_id() -> dict:
    out = subprocess.run(
        ["papis", "list", "--all", "--format", "{doc[papis_id]} {doc[ref]}", ""],
        capture_output=True,
        text=True,
    ).stdout
    pairs = (line.split(maxsplit=1) for line in out.splitlines())
    return {p[0]: p[1] for p in pairs if len(p) == 2}


def summarize(answer: dict, refs: dict) -> dict:
    cited = defaultdict(set)
    for r in answer.get("references", []):
        cited[refs.get(r["papis_id"], r["papis_id"])].add(str(r["pages"]))
    return {
        "words": len(answer.get("answer", "").split()),
        "scores": [c.get("score") for c in answer.get("contexts", [])],
        "cited": {k: sorted(v) for k, v in cited.items()},
    }


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    parser.add_argument("--config-a", type=Path, default=None, help="default: live config")
    parser.add_argument("--config-b", type=Path, required=True)
    parser.add_argument("--questions", type=Path, default=HERE / "eval_questions.json")
    parser.add_argument("--out", type=Path, required=True)
    parser.add_argument(
        "--papis-cmd",
        default="papis",
        help="command to run papis, e.g. '.venv/bin/python -m papis' from a worktree to test "
        "its code without touching the live install",
    )
    args = parser.parse_args()
    if not SECRETS.is_file():
        parser.error(f"{SECRETS} not found: every query would fail without the API keys")

    args.out.mkdir(parents=True, exist_ok=True)
    questions = json.loads(args.questions.read_text())
    refs = _refs_by_id()
    papis = shlex.split(args.papis_cmd)
    # interleaved per question, so an index that changes during the run affects both alike
    for n, item in enumerate(questions, 1):
        for label, config in (("a", args.config_a), ("b", args.config_b)):
            answer, elapsed, stderr = _ask(papis, config, item)
            if answer is None:
                print(f"{label} q{n}: FAILED after {elapsed:.0f}s\n{stderr[-600:]}")
                continue
            (args.out / f"{label}-q{n}.json").write_text(json.dumps(answer, indent=1))
            s = summarize(answer, refs)
            print(f"{label} q{n}: {elapsed:4.0f}s {s['words']:4} words  scores {s['scores']}")
            print(f"        cited {s['cited']}")
    print(f"\nanswers saved in {args.out}/ (a-qN.json, b-qN.json): read them side by side")


if __name__ == "__main__":
    main()
