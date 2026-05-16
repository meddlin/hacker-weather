from __future__ import annotations

from PIL import Image

from hacker_weather.image_test import (
    ImageRenderOptions,
    calculate_canvas_size,
    choose_renderer,
    create_rainy_cartoon,
    render_sample_image,
)


def test_create_rainy_cartoon_returns_rgba_image() -> None:
    image = create_rainy_cartoon()

    assert isinstance(image, Image.Image)
    assert image.mode == "RGBA"
    assert image.size == (640, 400)


def test_auto_renderer_selects_kitty_for_ghostty() -> None:
    selection = choose_renderer("auto", {"TERM_PROGRAM": "ghostty"})

    assert selection.name == "kitty"
    assert selection.pixel_mode == "CHAFA_PIXEL_MODE_KITTY"
    assert selection.fallback_reason is None


def test_auto_renderer_selects_symbols_for_terminal_app() -> None:
    selection = choose_renderer("auto", {"TERM_PROGRAM": "Apple_Terminal"})

    assert selection.name == "symbols"
    assert selection.pixel_mode == "CHAFA_PIXEL_MODE_SYMBOLS"
    assert selection.fallback_reason == "native terminal graphics not detected"


def test_auto_renderer_selects_symbols_for_tmux() -> None:
    selection = choose_renderer(
        "auto",
        {"TERM_PROGRAM": "ghostty", "TMUX": "/tmp/tmux-501/default,1,0"},
    )

    assert selection.name == "symbols"
    assert selection.fallback_reason is not None
    assert "TMUX detected" in selection.fallback_reason


def test_forced_symbols_renderer_never_chooses_native_graphics() -> None:
    selection = choose_renderer(
        "symbols",
        {"TERM_PROGRAM": "ghostty", "KITTY_WINDOW_ID": "1"},
    )

    assert selection.name == "symbols"
    assert selection.forced is True
    assert selection.fallback_reason is None


def test_canvas_size_respects_width_and_derives_height() -> None:
    image = create_rainy_cartoon()

    assert calculate_canvas_size(image, width=120, height=None) == (120, 41)


def test_canvas_size_respects_width_and_height_overrides() -> None:
    image = create_rainy_cartoon()

    assert calculate_canvas_size(image, width=100, height=30) == (100, 30)


def test_symbol_render_result_includes_fallback_status() -> None:
    image = create_rainy_cartoon((64, 40))
    result = render_sample_image(
        image,
        ImageRenderOptions(
            renderer="auto",
            width=32,
            env={"TERM_PROGRAM": "Apple_Terminal"},
        ),
    )

    assert result.renderer_name == "symbols"
    assert result.pixel_mode == "CHAFA_PIXEL_MODE_SYMBOLS"
    assert result.width == 32
    assert result.height == 11
    assert "symbols fallback" in result.status
    assert "native terminal graphics not detected" in result.status
    assert result.output
