from __future__ import annotations

import os
import shutil
from array import array
from collections.abc import Callable, Mapping
from dataclasses import dataclass
from typing import Literal

from PIL import Image, ImageDraw
from rich.console import Console

DEFAULT_IMAGE_SIZE = (640, 400)
DEFAULT_MIN_CANVAS_WIDTH = 32
DEFAULT_MAX_CANVAS_WIDTH = 120
CELL_ASPECT_RATIO = 0.55
TMUX_FALLBACK_REASON = "TMUX detected; native terminal graphics may not pass through"

RendererName = Literal["auto", "kitty", "iterm2", "sixel", "symbols"]


@dataclass(frozen=True)
class ImageRenderOptions:
    renderer: RendererName = "auto"
    width: int | None = None
    height: int | None = None
    env: Mapping[str, str] | None = None


@dataclass(frozen=True)
class RendererSelection:
    name: Literal["kitty", "iterm2", "sixel", "symbols"]
    pixel_mode: str
    fallback_reason: str | None = None
    forced: bool = False


@dataclass(frozen=True)
class ImageRenderResult:
    output: str
    renderer_name: str
    pixel_mode: str
    width: int
    height: int
    fallback_reason: str | None = None

    @property
    def status(self) -> str:
        renderer_label = f"{self.renderer_name} graphics"
        if self.renderer_name == "symbols":
            renderer_label = "symbols fallback" if self.fallback_reason else "symbols"

        status = f"renderer: {renderer_label}, size: {self.width}x{self.height} cells"
        if self.fallback_reason:
            status = f"{status}, reason: {self.fallback_reason}"
        return status


class ImageRenderError(RuntimeError):
    def __init__(self, renderer_name: str, reason: str) -> None:
        super().__init__(f"{renderer_name} renderer failed: {reason}")
        self.renderer_name = renderer_name
        self.reason = reason


def create_rainy_cartoon(size: tuple[int, int] = DEFAULT_IMAGE_SIZE) -> Image.Image:
    width, height = size
    image = Image.new("RGBA", size, (0, 0, 0, 0))
    draw = ImageDraw.Draw(image)

    scale_x = width / DEFAULT_IMAGE_SIZE[0]
    scale_y = height / DEFAULT_IMAGE_SIZE[1]

    def xy(box: tuple[int, ...]) -> tuple[int, ...]:
        return tuple(
            round(value * (scale_x if index % 2 == 0 else scale_y))
            for index, value in enumerate(box)
        )

    line_width = max(1, round(8 * min(scale_x, scale_y)))

    for y in range(height):
        blend = y / max(height - 1, 1)
        red = int(72 + (33 * blend))
        green = int(143 + (53 * blend))
        blue = int(202 + (35 * blend))
        draw.line([(0, y), (width, y)], fill=(red, green, blue, 255))

    draw.ellipse(xy((48, 64, 312, 216)), fill=(224, 233, 239, 255))
    draw.ellipse(xy((184, 40, 472, 224)), fill=(240, 245, 248, 255))
    draw.ellipse(xy((352, 80, 600, 232)), fill=(218, 229, 236, 255))
    draw.rectangle(xy((136, 152, 552, 240)), fill=(230, 238, 243, 255))

    for x in range(round(72 * scale_x), width, max(1, round(72 * scale_x))):
        offset = round(32 * scale_y) if (x // max(1, round(72 * scale_x))) % 2 else 0
        for y in range(
            round(240 * scale_y) + offset, height, max(1, round(96 * scale_y))
        ):
            draw.line(
                (x, y, x - round(24 * scale_x), y + round(44 * scale_y)),
                fill=(40, 95, 159, 230),
                width=max(1, round(7 * min(scale_x, scale_y))),
            )

    draw.pieslice(
        xy((136, 216, 504, 488)),
        start=180,
        end=360,
        fill=(235, 80, 89, 255),
    )
    draw.line(xy((320, 352, 320, 392)), fill=(70, 55, 75, 255), width=line_width)
    draw.arc(
        xy((320, 368, 408, 448)),
        start=0,
        end=180,
        fill=(70, 55, 75, 255),
        width=line_width,
    )
    draw.line(
        xy((136, 352, 504, 352)), fill=(151, 47, 65, 255), width=max(1, line_width // 2)
    )

    draw.ellipse(xy((216, 288, 244, 316)), fill=(255, 228, 125, 255))
    draw.ellipse(xy((396, 288, 424, 316)), fill=(255, 228, 125, 255))

    return image


def choose_renderer(
    requested: RendererName,
    env: Mapping[str, str] | None = None,
) -> RendererSelection:
    terminal_env = env or os.environ

    if requested != "auto":
        return RendererSelection(
            name=requested,
            pixel_mode=_pixel_mode_name(requested),
            forced=True,
        )

    if "TMUX" in terminal_env:
        return RendererSelection(
            name="symbols",
            pixel_mode=_pixel_mode_name("symbols"),
            fallback_reason=TMUX_FALLBACK_REASON,
        )

    term_program = terminal_env.get("TERM_PROGRAM", "")
    term = terminal_env.get("TERM", "")
    term_program_lower = term_program.lower()
    term_lower = term.lower()

    if term_program_lower == "ghostty" or any(
        key.startswith("GHOSTTY") for key in terminal_env
    ):
        return RendererSelection(name="kitty", pixel_mode=_pixel_mode_name("kitty"))

    if terminal_env.get("KITTY_WINDOW_ID") or "kitty" in term_lower:
        return RendererSelection(name="kitty", pixel_mode=_pixel_mode_name("kitty"))

    if terminal_env.get("WEZTERM_EXECUTABLE") or term_program == "WezTerm":
        return RendererSelection(name="kitty", pixel_mode=_pixel_mode_name("kitty"))

    if term_program == "iTerm.app":
        return RendererSelection(name="iterm2", pixel_mode=_pixel_mode_name("iterm2"))

    return RendererSelection(
        name="symbols",
        pixel_mode=_pixel_mode_name("symbols"),
        fallback_reason="native terminal graphics not detected",
    )


def calculate_canvas_size(
    image: Image.Image,
    *,
    width: int | None = None,
    height: int | None = None,
) -> tuple[int, int]:
    if width is None:
        terminal_size = shutil.get_terminal_size(fallback=(80, 24))
        canvas_width = min(
            max(DEFAULT_MIN_CANVAS_WIDTH, terminal_size.columns - 4),
            DEFAULT_MAX_CANVAS_WIDTH,
        )
    else:
        canvas_width = width

    if height is None:
        image_ratio = image.height / image.width
        canvas_height = max(1, round(image_ratio * canvas_width * CELL_ASPECT_RATIO))
    else:
        canvas_height = height

    return canvas_width, canvas_height


def render_sample_image(
    image: Image.Image, options: ImageRenderOptions
) -> ImageRenderResult:
    selection = choose_renderer(options.renderer, options.env)

    try:
        return _render_selection(image, options, selection)
    except Exception as error:
        if selection.forced or selection.name == "symbols":
            raise ImageRenderError(selection.name, str(error)) from error

        fallback_selection = RendererSelection(
            name="symbols",
            pixel_mode=_pixel_mode_name("symbols"),
            fallback_reason=f"{selection.name} graphics failed: {error}",
        )
        return _render_selection(image, options, fallback_selection)


def show_image_test(
    *,
    console: Console | None = None,
    renderer: Callable[[Image.Image, ImageRenderOptions], ImageRenderResult]
    | None = None,
    renderer_name: RendererName = "auto",
    width: int | None = None,
    height: int | None = None,
) -> int:
    output_console = console or Console()
    image = create_rainy_cartoon()
    options = ImageRenderOptions(renderer=renderer_name, width=width, height=height)
    render = renderer or render_sample_image

    output_console.print("[bold cyan]hacker-weather image test[/bold cyan]")
    try:
        result = render(image, options)
    except ImageRenderError as error:
        output_console.print(f"[red]{error}[/red]")
        return 1

    output_console.print(f"[dim]{result.status}[/dim]")
    output_console.file.write(result.output)
    if not result.output.endswith("\n"):
        output_console.file.write("\n")
    output_console.file.flush()
    output_console.print(
        "[dim]Sample rainy weather cartoon rendered in-terminal.[/dim]"
    )
    return 0


def _render_selection(
    image: Image.Image,
    options: ImageRenderOptions,
    selection: RendererSelection,
) -> ImageRenderResult:
    width, height = calculate_canvas_size(
        image,
        width=options.width,
        height=options.height,
    )
    output = _render_with_chafa(image, selection.name, width, height)
    return ImageRenderResult(
        output=output,
        renderer_name=selection.name,
        pixel_mode=selection.pixel_mode,
        width=width,
        height=height,
        fallback_reason=selection.fallback_reason,
    )


def _render_with_chafa(
    image: Image.Image,
    renderer_name: Literal["kitty", "iterm2", "sixel", "symbols"],
    width: int,
    height: int,
) -> str:
    import chafa

    config = chafa.CanvasConfig()
    config.width = width
    config.height = height
    config.canvas_mode = chafa.CanvasMode.CHAFA_CANVAS_MODE_TRUECOLOR
    config.color_space = chafa.ColorSpace.CHAFA_COLOR_SPACE_DIN99D
    config.pixel_mode = _chafa_pixel_mode(chafa, renderer_name)

    if renderer_name == "symbols":
        symbol_map = chafa.SymbolMap()
        symbol_map.add_by_tags(chafa.SymbolTags.CHAFA_SYMBOL_TAG_ALL)
        config.set_symbol_map(symbol_map)

    rgba_image = image.convert("RGBA")
    pixels = array("B", rgba_image.tobytes())
    canvas = chafa.Canvas(config)
    canvas.draw_all_pixels(
        chafa.PixelType.CHAFA_PIXEL_RGBA8_UNASSOCIATED,
        pixels,
        rgba_image.width,
        rgba_image.height,
        rgba_image.width * 4,
    )
    return canvas.print().decode("utf-8")


def _chafa_pixel_mode(chafa_module: object, renderer_name: str) -> object:
    pixel_mode = chafa_module.PixelMode
    return {
        "kitty": pixel_mode.CHAFA_PIXEL_MODE_KITTY,
        "iterm2": pixel_mode.CHAFA_PIXEL_MODE_ITERM2,
        "sixel": pixel_mode.CHAFA_PIXEL_MODE_SIXELS,
        "symbols": pixel_mode.CHAFA_PIXEL_MODE_SYMBOLS,
    }[renderer_name]


def _pixel_mode_name(renderer_name: str) -> str:
    return {
        "kitty": "CHAFA_PIXEL_MODE_KITTY",
        "iterm2": "CHAFA_PIXEL_MODE_ITERM2",
        "sixel": "CHAFA_PIXEL_MODE_SIXELS",
        "symbols": "CHAFA_PIXEL_MODE_SYMBOLS",
    }[renderer_name]
