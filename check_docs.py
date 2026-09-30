"""Checks the Markdown docs for things that drift or read like filler. Run from the repo root: python check_docs.py

- lines longer than 120 characters (table rows excepted: they can't be wrapped);
- filler words (see FILLER): say what it does, in numbers or names, instead;
- relative links whose file or #heading doesn't exist;
- `SETTING_NAMES` in backticks that appear nowhere outside the docs (a setting that was renamed or never existed).
"""
import re
import sys
from pathlib import Path

MAX_LINE = 120
FILLER_WORDS = [
    "robust(ly|ness)?", "seamless(ly)?", "leverag(e|es|ed|ing)", "comprehensive(ly)?", "cutting[- ]edge",
    "state[- ]of[- ]the[- ]art", "blazing", "effortless(ly)?", "streamlin(e|es|ed|ing)", "enterprise[- ]grade",
    "best[- ]in[- ]class", "hassle[- ]free", "delve", "game[- ]chang(er|ing)", "out[- ]of[- ]the[- ]box",
    "rich set", "battle[- ]tested", "world[- ]class",
]
FILLER = re.compile(r"\b(" + "|".join(FILLER_WORDS) + r")\b", re.IGNORECASE)
# Names that belong to other software (the game image, Docker, Discord) and so appear nowhere in this repo.
EXTERNAL_NAMES: set[str] = set()
SETTING = re.compile(r"`([A-Z][A-Z0-9_]{3,})`")
LINK = re.compile(r"(?<!!)\[[^\]]*\]\(([^)\s]+)\)")
SKIP_DIRS = {".git", "node_modules", "data"}


def docs(root: Path) -> list[Path]:
    return sorted(p for p in root.rglob("*.md") if not SKIP_DIRS & set(p.relative_to(root).parts))


def slug(heading: str) -> str:
    """GitHub's anchor for a heading: lower case, punctuation and emoji dropped, spaces to hyphens."""
    text = re.sub(r"[`*_]", "", heading.strip().lower())
    return re.sub(r"[^\w\- ]", "", text).replace(" ", "-")


def anchors(path: Path) -> set[str]:
    found, in_fence = set(), False
    for line in path.read_text().splitlines():
        if line.startswith("```"):
            in_fence = not in_fence
        elif not in_fence and (m := re.match(r"#{1,6}\s+(.*)", line)):
            found.add(slug(m.group(1)))
    return found


def outside_docs_text(root: Path, docs_found: list[Path]) -> str:
    """All text files that aren't docs: where every documented setting must be defined or used."""
    skip = set(docs_found)
    parts = []
    for path in root.rglob("*"):
        if path in skip or SKIP_DIRS & set(path.relative_to(root).parts) or not path.is_file():
            continue
        try:
            parts.append(path.read_text())
        except (UnicodeDecodeError, OSError):
            continue
    return "\n".join(parts)


def check(root: Path) -> list[str]:
    problems = []
    md_files = docs(root)
    code_text = outside_docs_text(root, md_files)
    for path in md_files:
        rel = path.relative_to(root)
        in_fence = False
        for number, line in enumerate(path.read_text().splitlines(), 1):
            if line.startswith("```"):
                in_fence = not in_fence
            where = f"{rel}:{number}"
            if len(line) > MAX_LINE and not line.startswith("|"):
                problems.append(f"{where}: {len(line)} characters (limit {MAX_LINE})")
            if not in_fence and (m := FILLER.search(line)):
                problems.append(f"{where}: filler word '{m.group(0)}'; say what it does instead")
            if in_fence:
                continue
            for name in SETTING.findall(line):
                if name not in EXTERNAL_NAMES and name not in code_text:
                    problems.append(f"{where}: `{name}` is not defined or used anywhere outside the docs")
            for target in LINK.findall(line):
                if re.match(r"[a-z]+:", target):  # https:, mailto:
                    continue
                file_part, _, fragment = target.partition("#")
                linked = (path.parent / file_part) if file_part else path
                if not linked.exists():
                    problems.append(f"{where}: link to missing file {file_part}")
                elif fragment and linked.suffix == ".md" and fragment not in anchors(linked):
                    problems.append(f"{where}: no heading for #{fragment} in {linked.relative_to(root)}")
    return problems


def main() -> int:
    problems = check(Path.cwd())
    for problem in problems:
        print(problem)
    print(f"docs check: {len(problems)} problem(s)")
    return 1 if problems else 0


if __name__ == "__main__":
    sys.exit(main())
