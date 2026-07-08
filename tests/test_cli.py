from __future__ import annotations

import io

import pytest
from rich.console import Console

from hacker_weather import __version__
from hacker_weather.cli import build_parser, main
from hacker_weather.image_test import (
    ImageRenderError,
    ImageRenderOptions,
    ImageRenderResult,
)


def test_help_includes_image_options() -> None:
    help_text = build_parser().format_help()

    assert "hacker-weather" in help_text
    assert "--image-test" in help_text
    assert "--radar" in help_text
    assert "--image-renderer" in help_text
    assert "--image-width" in help_text
    assert "--image-height" in help_text


def test_version_option_prints_package_version(
    capsys: pytest.CaptureFixture[str],
) -> None:
    with pytest.raises(SystemExit) as exit_info:
        main(["--version"])

    assert exit_info.value.code == 0
    assert f"hacker-weather {__version__}" in capsys.readouterr().out


def test_image_test_uses_renderer() -> None:
    stream = io.StringIO()
    console = Console(file=stream, force_terminal=False, width=80)

    def renderer(_image: object, options: ImageRenderOptions) -> ImageRenderResult:
        assert options.renderer == "symbols"
        assert options.width == 120
        assert options.height == 40
        return ImageRenderResult(
            output="rendered output\n",
            renderer_name="symbols",
            pixel_mode="CHAFA_PIXEL_MODE_SYMBOLS",
            width=120,
            height=40,
        )

    exit_code = main(
        [
            "--image-test",
            "--image-renderer",
            "symbols",
            "--image-width",
            "120",
            "--image-height",
            "40",
        ],
        console=console,
        image_renderer=renderer,
    )

    assert exit_code == 0
    assert "renderer: symbols, size: 120x40 cells" in stream.getvalue()
    assert "rendered output" in stream.getvalue()


def test_radar_option_delegates_to_radar_runner() -> None:
    stream = io.StringIO()
    console = Console(file=stream, force_terminal=False, width=80)
    calls: list[dict[str, object]] = []

    def renderer(_image: object, _options: ImageRenderOptions) -> ImageRenderResult:
        return ImageRenderResult(
            output="radar",
            renderer_name="symbols",
            pixel_mode="CHAFA_PIXEL_MODE_SYMBOLS",
            width=120,
            height=40,
        )

    def radar_runner(zip_code: str, **kwargs: object) -> int:
        calls.append({"zip_code": zip_code, **kwargs})
        return 0

    exit_code = main(
        [
            "--radar",
            "90210",
            "--image-renderer",
            "symbols",
            "--image-width",
            "120",
            "--image-height",
            "40",
        ],
        console=console,
        image_renderer=renderer,
        radar_runner=radar_runner,
    )

    assert exit_code == 0
    assert calls == [
        {
            "zip_code": "90210",
            "console": console,
            "renderer": renderer,
            "renderer_name": "symbols",
            "width": 120,
            "height": 40,
        }
    ]


def test_forced_renderer_error_returns_nonzero() -> None:
    stream = io.StringIO()
    console = Console(file=stream, force_terminal=False, width=80)

    def renderer(_image: object, _options: ImageRenderOptions) -> ImageRenderResult:
        raise ImageRenderError("kitty", "boom")

    exit_code = main(
        ["--image-test", "--image-renderer", "kitty"],
        console=console,
        image_renderer=renderer,
    )

    assert exit_code == 1
    assert "kitty renderer failed: boom" in stream.getvalue()
