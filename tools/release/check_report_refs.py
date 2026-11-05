#!/usr/bin/env python3
"""Reference check of the methods-and-results report (EN and RU).

Every file path, commit hash and issue number the report names must resolve:

* ``KEY:path`` (KEY is AGL, SC or SB) is looked up in that repository;
* a bare path with a slash and a known extension (``py/columns.py``) is looked up under a list of roots inside the three
  repositories, because the report gives such paths relative to the tool directory it is talking about;
* a hexadecimal token of 7 to 12 characters in backticks must be a commit of one of the three repositories;
* ``#N`` is an issue (or pull request) of ``deadline-squad/deadline-squadcalc``, ``SB#N`` one of
  ``deadline-squad/squad-ballistics``, ``deadline-squad/<repo>#N`` the named one; each is fetched with ``gh api``.

Usage: ``check_report_refs.py [--no-issues] [report.md ...]`` (default: both reports next to this repository's docs).
Environment: ``SQUADCALC_REPO``, ``SB_REPO``, ``AGL_REPO`` as in ``build_release.sh``. Exit status 0 when everything
resolves, 1 otherwise. Output: one line per distinct reference, ``ok`` or ``MISSING``, then a summary.
"""
import os
import re
import subprocess
import sys
from pathlib import Path

AGL = Path(os.environ.get("AGL_REPO") or Path(__file__).resolve().parents[2])
SC = Path(os.environ.get("SQUADCALC_REPO", Path.home() / "agl/SquadCalc"))
SB = Path(os.environ.get("SB_REPO", Path.home() / "dev/Squad-Ballistics"))
REPOS = {"AGL": AGL, "SC": SC, "SB": SB}
ISSUE_REPOS = {"SC": "deadline-squad/deadline-squadcalc", "SB": "deadline-squad/squad-ballistics"}

BARE_ROOTS = [
    AGL, AGL / "tools", AGL / "docs", AGL / "tools/volumetric", AGL / "tools/volumetric/py", AGL / "tools/volumetric/docs",
    AGL / "tools/heightmaps", AGL / "tools/heightmaps/py", AGL / "tools/game_ballistics", AGL / "tools/browser_check",
    SC, SC / "engine", SC / "engine/tools", SC / "engine/tools/js", SC / "engine/wgsl", SC / "src/js", SC / "tests",
    SB, SB / "docs", SB / "tests",
]
CHECKED_EXTENSIONS = {".py", ".mjs", ".md", ".sh", ".json", ".js", ".rs", ".tsv", ".awk", ".html", ".txt", ".toml"}
PATH_WORD = re.compile(r"^[\w.\-]+(?:/[\w.\-]+)+/?$")
KEYED = re.compile(r"^(AGL|SC|SB):([\w.\-]+(?:/[\w.\-]+)*/?)")
HASH = re.compile(r"^[0-9a-f]{7,12}$")
ISSUE = re.compile(r"(?<![\w/])(?:deadline-squad/([\w\-]+))?(SB)?#(\d+)\b")
MARKDOWN_LINK = re.compile(r"\]\(([\w.\-]+\.md)\)")


def commit_exists(commit: str) -> bool:
    return any(
        subprocess.run(["git", "-C", str(repo), "cat-file", "-e", f"{commit}^{{commit}}"], capture_output=True).returncode == 0
        for repo in REPOS.values()
    )


def issue_exists(repo: str, number: str) -> bool:
    result = subprocess.run(["gh", "api", f"repos/{repo}/issues/{number}", "--jq", ".number"], capture_output=True, text=True)
    return result.returncode == 0 and result.stdout.strip() == number


def code_spans(text: str):
    return re.findall(r"`([^`\n]+)`", text)


def collect(report: Path):
    """Returns (paths_keyed, paths_bare, commits, issues) as sets of strings / tuples."""
    text = report.read_text(encoding="utf-8")
    keyed, bare, commits, issues = set(), set(), set(), set()
    for span in code_spans(text):
        match = KEYED.match(span)
        if match:
            keyed.add((match.group(1), match.group(2)))
        if HASH.match(span) and re.search(r"[0-9]", span) and re.search(r"[a-f]", span):
            commits.add(span)
        for word in span.split():
            word = word.strip(",;:()")
            if KEYED.match(word) or word.startswith(("/", "~", "<", "http")) or "<" in word or "*" in word or "..." in word:
                continue
            if PATH_WORD.match(word) and Path(word.rstrip("/")).suffix in CHECKED_EXTENSIONS:
                bare.add(word)
    for link in MARKDOWN_LINK.findall(text):
        bare.add(str(Path("docs") / link))
    for explicit_repo, sb_marker, number in ISSUE.findall(text):
        repo = f"deadline-squad/{explicit_repo}" if explicit_repo else ISSUE_REPOS["SB" if sb_marker else "SC"]
        issues.add((repo, number))
    return keyed, bare, commits, issues


def main(argv):
    check_issues = "--no-issues" not in argv
    reports = [Path(a) for a in argv if not a.startswith("--")] or [
        AGL / "docs/thesis-methods-and-results.md", AGL / "docs/thesis-methods-and-results.ru.md"]
    keyed, bare, commits, issues = set(), set(), set(), set()
    for report in reports:
        k, b, c, i = collect(report)
        keyed |= k
        bare |= b
        commits |= c
        issues |= i
    missing = 0

    def show(kind, name, found):
        nonlocal missing
        missing += not found
        print(f"{'ok     ' if found else 'MISSING'} {kind:7} {name}")

    for key, path in sorted(keyed):
        show("path", f"{key}:{path}", (REPOS[key] / path).exists())
    for path in sorted(bare):
        show("path", path, any((root / path).exists() for root in BARE_ROOTS))
    for commit in sorted(commits):
        show("commit", commit, commit_exists(commit))
    if check_issues:
        for repo, number in sorted(issues, key=lambda item: (item[0], int(item[1]))):
            show("issue", f"{repo}#{number}", issue_exists(repo, number))
    print(f"checked {len(keyed)} keyed paths, {len(bare)} bare paths, {len(commits)} commits, "
          f"{len(issues) if check_issues else 0} issues; {missing} missing")
    return 1 if missing else 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
