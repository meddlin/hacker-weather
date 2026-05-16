from __future__ import annotations

import argparse
from collections.abc import Callable, Sequence

from rich.console import Console

from . import __version__


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="hacker-weather",
        description=(
            "Terminal weather radar and NOAA weather visualization CLI. "
            "NOAA API commands are not wired yet."
        ),
    )
    parser.add_argument(
        "--version",
        action="version",
        version=f"%(prog)s {__version__}",
    )
    parser.add_argument(
        "--image-test",
        action="store_true",
        help="render a sample rainy weather cartoon image in the terminal",
    )
    parser.add_argument(
        "--image-renderer",
        choices=("auto", "kitty", "iterm2", "sixel", "symbols"),
        default="auto",
        help="terminal image renderer to use with --image-test",
    )
    parser.add_argument(
        "--image-width",
        type=_positive_int,
        help="image-test render width in terminal cells",
    )
    parser.add_argument(
        "--image-height",
        type=_positive_int,
        help="image-test render height in terminal cells",
    )
    return parser


def main(
    argv: Sequence[str] | None = None,
    *,
    console: Console | None = None,
    image_renderer: Callable[..., object] | None = None,
) -> int:
    parser = build_parser()
    args = parser.parse_args(argv)

    if args.image_test:
        from .image_test import show_image_test

        return show_image_test(
            console=console,
            renderer=image_renderer,
            renderer_name=args.image_renderer,
            width=args.image_width,
            height=args.image_height,
        )

    parser.print_help()
    return 0


def _positive_int(value: str) -> int:
    parsed = int(value)
    if parsed < 1:
        raise argparse.ArgumentTypeError("must be a positive integer")
    return parsed
