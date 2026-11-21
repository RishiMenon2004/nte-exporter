"""Build GitHub Wiki pages from README.md and docs/*.md."""

from __future__ import annotations

import argparse
import re
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
DOCS_DIR = ROOT / "docs"
README_PATH = ROOT / "README.md"

# Maps docs/<filename> -> GitHub Wiki page slug (filename without .md).
DOC_PAGES: dict[str, str] = {
    "gui.md": "Desktop-GUI",
    "cli.md": "Command-Line-Usage",
    "export-format.md": "Export-Format",
    "direct-import.md": "Direct-Import",
    "packaging.md": "Packaging",
    "mapping-updates.md": "Mapping-Updates",
    "capture-diagnostics.md": "Capture-Diagnostics",
    "packet-format.md": "Packet-Format",
    "limitations.md": "Limitations",
}

SIDEBAR = """### NTE History Exporter

- [Home](Home)

#### Usage
- [Desktop GUI](Desktop-GUI)
- [Command-Line Usage](Command-Line-Usage)
- [Limitations](Limitations)

#### Trackers & Exports
- [Export Format](Export-Format)
- [Direct Import](Direct-Import)

#### Developers
- [Packaging](Packaging)
- [Mapping Updates](Mapping-Updates)
- [Capture Diagnostics](Capture-Diagnostics)
- [Packet Format](Packet-Format)
"""

LINK_RE = re.compile(r"(!?\[[^\]]*\]\()([^)]+)(\))")
IMG_SRC_RE = re.compile(r'(<img\b[^>]*\bsrc=")([^"]+)(")')


def rewrite_target(target: str, *, from_docs: bool, repo: str, branch: str) -> str:
    if target.startswith(("http://", "https://", "mailto:", "#")):
        return target

    path_part, sep, fragment = target.partition("#")
    suffix = f"#{fragment}" if sep else ""

    # Normalize relative paths from docs/ or repo root.
    if from_docs:
        if path_part in DOC_PAGES:
            return f"{DOC_PAGES[path_part]}{suffix}"
        if path_part == "../README.md":
            return f"Home{suffix}"
        if path_part.startswith("images/"):
            return f"https://raw.githubusercontent.com/{repo}/{branch}/docs/{path_part}"
        if path_part.startswith("../"):
            repo_rel = path_part[3:]
            return f"https://github.com/{repo}/blob/{branch}/{repo_rel}{suffix}"
        if path_part.startswith("/"):
            repo_rel = path_part.lstrip("/")
            return f"https://github.com/{repo}/blob/{branch}/{repo_rel}{suffix}"
    else:
        if path_part.startswith("docs/"):
            sub = path_part[len("docs/") :]
            if sub in DOC_PAGES:
                return f"{DOC_PAGES[sub]}{suffix}"
            if sub.startswith("images/"):
                return f"https://raw.githubusercontent.com/{repo}/{branch}/docs/{sub}"
        if path_part.startswith("/"):
            repo_rel = path_part.lstrip("/")
            return f"https://github.com/{repo}/blob/{branch}/{repo_rel}{suffix}"

    return target


def rewrite_markdown(text: str, *, from_docs: bool, repo: str, branch: str, strip_h1: bool) -> str:
    if strip_h1:
        lines = text.splitlines()
        if lines and lines[0].startswith("# "):
            lines = lines[1:]
            while lines and not lines[0].strip():
                lines = lines[1:]
            text = "\n".join(lines) + "\n"

    text = LINK_RE.sub(
        lambda m: f"{m.group(1)}{rewrite_target(m.group(2), from_docs=from_docs, repo=repo, branch=branch)}{m.group(3)}",
        text,
    )
    text = IMG_SRC_RE.sub(
        lambda m: f"{m.group(1)}{rewrite_target(m.group(2), from_docs=from_docs, repo=repo, branch=branch)}{m.group(3)}",
        text,
    )
    return text


def build_wiki(output_dir: Path, *, repo: str, branch: str = "main") -> list[Path]:
    output_dir.mkdir(parents=True, exist_ok=True)
    written: list[Path] = []

    home = output_dir / "Home.md"
    home.write_text(
        rewrite_markdown(
            README_PATH.read_text(encoding="utf-8"),
            from_docs=False,
            repo=repo,
            branch=branch,
            strip_h1=False,
        ),
        encoding="utf-8",
    )
    written.append(home)

    sidebar = output_dir / "_Sidebar.md"
    sidebar.write_text(SIDEBAR, encoding="utf-8")
    written.append(sidebar)

    for doc_name, wiki_slug in DOC_PAGES.items():
        source = DOCS_DIR / doc_name
        dest = output_dir / f"{wiki_slug}.md"
        dest.write_text(
            rewrite_markdown(
                source.read_text(encoding="utf-8"),
                from_docs=True,
                repo=repo,
                branch=branch,
                strip_h1=True,
            ),
            encoding="utf-8",
        )
        written.append(dest)

    return written


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Generate GitHub Wiki pages from README.md and docs/.")
    parser.add_argument("--output", type=Path, required=True, help="Directory to write wiki markdown files into.")
    parser.add_argument("--repo", default="RishiMenon2004/nte-exporter", help="GitHub owner/repo for raw/blob links.")
    parser.add_argument("--branch", default="main", help="Branch name for raw/blob links.")
    args = parser.parse_args(argv)

    written = build_wiki(args.output, repo=args.repo, branch=args.branch)
    print(f"Wrote {len(written)} wiki pages to {args.output}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
