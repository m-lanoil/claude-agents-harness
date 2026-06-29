import asyncio
import argparse

from .orchestrator import run


def main() -> None:
    parser = argparse.ArgumentParser(
        prog="python -m coordinator",
        description="Coordinator — automated orchestration loop for claude_agents.",
    )
    parser.add_argument(
        "task",
        nargs="?",
        help="Task description. Prompted interactively if omitted.",
    )
    parser.add_argument(
        "--workers",
        default=None,
        metavar="CHAIN",
        help=(
            "Worker name or comma-separated multi-hop chain "
            "(e.g. 'developer' or 'architect,developer'). "
            "Prompted interactively if omitted."
        ),
    )
    parser.add_argument(
        "--output",
        default=None,
        metavar="PATH",
        help=(
            "Expected output path (e.g. ../../output/report.md). "
            "Prompted interactively if omitted."
        ),
    )
    parser.add_argument(
        "--sections",
        default=None,
        metavar="SECTIONS",
        help=(
            "Required sections, comma-separated "
            "(e.g. 'Summary,Results'). "
            "Prompted interactively if omitted."
        ),
    )
    parser.add_argument(
        "--approved-urls",
        default=None,
        metavar="JSON",
        help=(
            "Pre-register approved URLs into the Source Registry before invoking workers. "
            'JSON format: \'{"libraries": {"name": "url"}, "clis": {"name": "url"}, '
            '"other": {"name": "url"}}\' (any of the three keys may be omitted).'
        ),
    )
    args = parser.parse_args()
    task = args.task or input("Task: ").strip()
    asyncio.run(
        run(
            task,
            workers=args.workers,
            output=args.output,
            sections=args.sections,
            approved_urls=args.approved_urls,
        )
    )


if __name__ == "__main__":
    main()
