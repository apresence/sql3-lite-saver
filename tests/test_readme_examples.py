#!/usr/bin/env python3
"""
tests/test_readme_examples.py

Purpose
-------
Executes README.md python examples so docs can't drift from reality.

Pytest behavior
--------------
- Extracts python fenced blocks from README.md.
- By default, only runs blocks that appear under selected section headers
  (to avoid executing incidental snippets).
- Each block is executed in its own temporary working directory.

CLI behavior
------------
  python tests/test_readme_examples.py --show
    Print the extracted runnable blocks with an index.

  python tests/test_readme_examples.py --run --index N
    Run block N in a temp dir and print created files.

  python tests/test_readme_examples.py --run --all
    Run all runnable blocks.

Notes
-----
- Blocks run as scripts (`__name__ == "__main__"`).
- Output is not asserted; the contract is "runs without error".
"""

import argparse
import os
import re
import sys
import tempfile
from dataclasses import dataclass
from pathlib import Path

import pytest


# Headers whose python blocks we consider "runnable examples".
# Adjust to match your README sections.
RUNNABLE_SECTIONS = {
    "Example",
    ## These two just illustrate usage; Not meant to be run ##
    # "Advanced Retry with Tenacity",
    # "WAL Checkpoint Management",
}


@dataclass(frozen=True)
class Block:
    index: int
    section: str
    code: str


def _repo_root() -> Path:
    return Path(__file__).resolve().parents[1]


def _read_readme(root: Path) -> str:
    return (root / "README.md").read_text(encoding="utf-8")


def _extract_blocks(md_text: str) -> list[Block]:
    """
    Extract python fenced code blocks and associate them with the nearest preceding '## <Section>' header.
    """
    # Find all section headers with their positions
    header_re = re.compile(r"^##\s+(.*)$", re.MULTILINE)
    headers = [(m.start(), m.group(1).strip()) for m in header_re.finditer(md_text)]
    headers.sort()

    def section_for_pos(pos: int) -> str:
        # nearest header before pos
        sec = ""
        for hpos, hname in headers:
            if hpos <= pos:
                sec = hname
            else:
                break
        return sec or ""

    # Find all python fenced blocks with their positions
    block_re = re.compile(r"```python\s+(.*?)```", re.DOTALL)
    blocks: list[Block] = []
    i = 0
    for m in block_re.finditer(md_text):
        sec = section_for_pos(m.start())
        code = m.group(1).strip() + "\n"
        blocks.append(Block(index=i, section=sec, code=code))
        i += 1
    return blocks


def get_runnable_blocks(root: Path) -> list[Block]:
    text = _read_readme(root)
    blocks = _extract_blocks(text)
    runnable = [b for b in blocks if b.section in RUNNABLE_SECTIONS]
    if not runnable:
        raise AssertionError(
            "No runnable README python blocks found. "
            "Check RUNNABLE_SECTIONS matches your README headers."
        )
    return runnable


def run_block_in_temp_dir(block: Block, filename_hint: str) -> list[str]:
    """
    Execute block.code in a temp directory. Return relative paths of files created there.
    """
    with tempfile.TemporaryDirectory() as td:
        td_path = Path(td)
        old_cwd = os.getcwd()
        try:
            os.chdir(td_path)
            exec(compile(block.code, filename_hint, "exec"), {"__name__": "__main__"})
        finally:
            os.chdir(old_cwd)

        created = sorted(p for p in td_path.rglob("*") if p.is_file())
        return [str(p.relative_to(td_path)) for p in created]


@pytest.mark.parametrize("block", get_runnable_blocks(_repo_root()), ids=lambda b: f"{b.index}:{b.section}")
def test_readme_block_runs(tmp_path, monkeypatch, block: Block):
    # Use pytest temp dir (faster than tempfile + keeps pytest semantics)
    monkeypatch.chdir(tmp_path)
    exec(compile(block.code, str(_repo_root() / "README.md"), "exec"), {"__name__": "__main__"})


def main() -> int:
    p = argparse.ArgumentParser(description="Inspect/run python examples extracted from README.md.")
    p.add_argument("--show", action="store_true", help="Show runnable python blocks with indices.")
    p.add_argument("--run", action="store_true", help="Run one or more runnable blocks.")
    p.add_argument("--index", type=int, default=None, help="Run only block N (use with --run).")
    p.add_argument("--all", action="store_true", help="Run all runnable blocks (use with --run).")
    args = p.parse_args()

    if not args.show and not args.run:
        p.print_help()
        return 2

    root = _repo_root()
    blocks = get_runnable_blocks(root)

    if args.show:
        for b in blocks:
            print(f"[{b.index}] section={b.section}")
            print(b.code, end="")
            print("-" * 60)

    if args.run:
        if args.all and args.index is not None:
            print("Use either --all or --index, not both.", file=sys.stderr)
            return 2
        if not args.all and args.index is None:
            print("Use --run with either --all or --index N.", file=sys.stderr)
            return 2

        to_run = blocks if args.all else [b for b in blocks if b.index == args.index]
        if not to_run:
            print(f"No runnable block with index {args.index}.", file=sys.stderr)
            return 2

        for b in to_run:
            created = run_block_in_temp_dir(b, str(root / "README.md"))
            print(f"Ran block [{b.index}] ({b.section})")
            if created:
                print("Created files:")
                for f in created:
                    print(f"  {f}")
            else:
                print("Created files: (none)")
            print("-" * 60)

    return 0


if __name__ == "__main__":
    raise SystemExit(main())
