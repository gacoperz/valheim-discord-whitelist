"""The docs check must pass clean docs and fail each planted problem."""
import pytest

from check_docs import check, slug

CLEAN = {
    "README.md": "# Title\n\nSee [install](docs/INSTALL.md#2-create-the-app) and [below](#usage).\n\n## Usage\n"
                 "Set `SERVER_NAME` first.\n\n| a | b |\n|---|---|\n| " + "x" * 130 + " | y |\n",
    "docs/INSTALL.md": "# Install\n\n## 2. Create the app\nBack to [README](../README.md).\n",
    "config.env": "SERVER_NAME=x\n",
}


def tree(tmp_path, **changes):
    files = {**CLEAN, **changes}
    for name, text in files.items():
        path = tmp_path / name
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(text)
    return tmp_path


def test_clean_docs_pass(tmp_path):
    assert check(tree(tmp_path)) == []


@pytest.mark.parametrize("readme, expected", [
    (CLEAN["README.md"] + "w" * 121 + "\n", "README.md:11: 121 characters"),
    (CLEAN["README.md"] + "A robust and seamless bot.\n", "filler word 'robust'"),
    (CLEAN["README.md"] + "See [x](docs/MISSING.md).\n", "link to missing file docs/MISSING.md"),
    (CLEAN["README.md"] + "See [x](docs/INSTALL.md#nope).\n", "no heading for #nope in docs/INSTALL.md"),
    (CLEAN["README.md"] + "See [x](#nope).\n", "no heading for #nope in README.md"),
    (CLEAN["README.md"] + "Set `RENAMED_SETTING`.\n", "`RENAMED_SETTING` is not defined"),
])
def test_planted_problem_is_reported(tmp_path, readme, expected):
    problems = check(tree(tmp_path, **{"README.md": readme}))
    assert len(problems) == 1 and expected in problems[0]


def test_code_fences_skip_filler_and_settings_but_not_length(tmp_path):
    fenced = CLEAN["README.md"] + "```\nrobust `NOT_A_SETTING_X`\n" + "w" * 121 + "\n```\n"
    problems = check(tree(tmp_path, **{"README.md": fenced}))
    assert len(problems) == 1 and "121 characters" in problems[0]


def test_external_links_are_ignored(tmp_path):
    text = CLEAN["README.md"] + "See [x](https://example.org/a#b) and [m](mailto:a@b.c).\n"
    assert check(tree(tmp_path, **{"README.md": text})) == []


def test_slug_matches_github_anchors():
    assert slug("2. Create the Discord application") == "2-create-the-discord-application"
    assert slug("⚠️ Can't write `permittedlist.txt`") == "-cant-write-permittedlisttxt"
