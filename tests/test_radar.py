from __future__ import annotations

import io
import os
import subprocess
from collections.abc import Callable
from dataclasses import dataclass

import pytest
from PIL import Image
from rich.console import Console

from hacker_weather.image_test import ImageRenderOptions
from hacker_weather.radar import (
    ChafaRadarPlayer,
    RadarError,
    RadarLoop,
    RadarStation,
    ZipLocation,
    calculate_refresh_deadline,
    resolve_zip_code,
    select_nearest_station,
    show_radar,
)


def test_resolve_zip_code_rejects_malformed_zip() -> None:
    def lookup(_zip_code: str) -> list[dict[str, object]]:
        raise ValueError("Invalid format")

    with pytest.raises(RadarError, match="Invalid ZIP code"):
        resolve_zip_code("abcde", lookup=lookup)


def test_resolve_zip_code_rejects_unknown_zip() -> None:
    with pytest.raises(RadarError, match="was not found"):
        resolve_zip_code("00000", lookup=lambda _zip_code: [])


def test_resolve_zip_code_rejects_non_us_zip() -> None:
    with pytest.raises(RadarError, match="Only U.S. ZIP codes"):
        resolve_zip_code(
            "H0H0H0",
            lookup=lambda _zip_code: [
                {
                    "country": "CA",
                    "lat": "90.0",
                    "long": "135.0",
                    "zip_code": "H0H0H0",
                }
            ],
        )


def malformed_lookup(_zip_code: str) -> list[dict[str, object]]:
    raise ValueError("bad")


@pytest.mark.parametrize(
    ("zip_code", "lookup", "expected_message"),
    [
        ("abcde", malformed_lookup, "Invalid ZIP code"),
        ("00000", lambda _zip_code: [], "was not found"),
        (
            "H0H0H0",
            lambda _zip_code: [{"country": "CA", "lat": "90.0", "long": "135.0"}],
            "Only U.S. ZIP codes",
        ),
    ],
)
def test_show_radar_returns_nonzero_for_invalid_zip(
    zip_code: str,
    lookup: Callable[[str], list[dict[str, object]]],
    expected_message: str,
) -> None:
    stream = io.StringIO()
    console = Console(file=stream, force_terminal=False, width=80)

    exit_code = show_radar(
        zip_code,
        console=console,
        downloader=FakeDownloader(),
        zip_lookup=lookup,
    )

    assert exit_code == 1
    assert expected_message in stream.getvalue()


def test_select_nearest_station_uses_haversine_distance() -> None:
    location = ZipLocation(
        zip_code="90210",
        latitude=34.0901,
        longitude=-118.4065,
        city="Beverly Hills",
        state="CA",
    )

    station = select_nearest_station(
        location,
        [
            RadarStation("KOKX", "New York City", 40.8656, -72.8647),
            RadarStation("KVTX", "Los Angeles", 34.4116, -119.1795),
            RadarStation("KLOT", "Chicago", 41.6044, -88.0847),
        ],
    )

    assert station.station_id == "KVTX"


def test_refresh_deadline_uses_date_and_expires_headers() -> None:
    deadline = calculate_refresh_deadline(
        {
            "Date": "Wed, 08 Jul 2026 04:47:51 GMT",
            "Expires": "Wed, 08 Jul 2026 04:49:51 GMT",
            "Cache-Control": "max-age=999",
        },
        now=1000.0,
    )

    assert deadline == 1120.0


def test_refresh_deadline_uses_cache_control_max_age() -> None:
    assert (
        calculate_refresh_deadline({"Cache-Control": "public, max-age=30"}, now=10.0)
        == 40.0
    )


def test_refresh_deadline_falls_back_to_120_seconds() -> None:
    assert calculate_refresh_deadline({}, now=5.0) == 125.0


def test_chafa_player_invokes_command_with_gif_duration_renderer_and_size() -> None:
    gif_bytes = _gif_bytes()
    runner = RecordingRunner(expected_content=gif_bytes)
    player = ChafaRadarPlayer(chafa_path="/opt/homebrew/bin/chafa", runner=runner)
    console = Console(file=io.StringIO(), force_terminal=False, width=80)

    player.play(
        gif_bytes,
        duration_seconds=12.3456,
        options=ImageRenderOptions(renderer="kitty", width=120, height=40),
        console=console,
    )

    assert len(runner.calls) == 1
    command = runner.calls[0]
    assert command[0] == "/opt/homebrew/bin/chafa"
    assert "--animate=on" in command
    assert "--duration=12.346" in command
    assert "--clear" in command
    assert "--format=kitty" in command
    assert "--size=120x40" in command
    assert command[-1].endswith(".gif")
    assert not os.path.exists(command[-1])


@pytest.mark.parametrize(
    ("renderer", "expected_format"),
    [
        ("auto", None),
        ("kitty", "kitty"),
        ("iterm2", "iterm"),
        ("sixel", "sixels"),
        ("symbols", "symbols"),
    ],
)
def test_chafa_player_maps_renderer_formats(
    renderer: str,
    expected_format: str | None,
) -> None:
    runner = RecordingRunner(expected_content=_gif_bytes())
    player = ChafaRadarPlayer(runner=runner)

    player.play(
        _gif_bytes(),
        duration_seconds=1.0,
        options=ImageRenderOptions(renderer=renderer),  # type: ignore[arg-type]
        console=Console(file=io.StringIO(), force_terminal=False, width=80),
    )

    command = runner.calls[0]
    format_args = [part for part in command if part.startswith("--format=")]
    if expected_format is None:
        assert format_args == []
    else:
        assert format_args == [f"--format={expected_format}"]


def test_chafa_player_reports_missing_binary() -> None:
    def runner(
        _command: list[str], *, check: bool
    ) -> subprocess.CompletedProcess[object]:
        raise FileNotFoundError("missing")

    player = ChafaRadarPlayer(runner=runner)

    with pytest.raises(RadarError, match="brew install chafa"):
        player.play(
            _gif_bytes(),
            duration_seconds=1.0,
            options=ImageRenderOptions(renderer="auto"),
            console=Console(file=io.StringIO(), force_terminal=False, width=80),
        )


def test_chafa_player_reports_nonzero_exit() -> None:
    def runner(
        command: list[str], *, check: bool
    ) -> subprocess.CompletedProcess[object]:
        raise subprocess.CalledProcessError(returncode=7, cmd=command)

    player = ChafaRadarPlayer(runner=runner)

    with pytest.raises(RadarError, match="exit code 7"):
        player.play(
            _gif_bytes(),
            duration_seconds=1.0,
            options=ImageRenderOptions(renderer="auto"),
            console=Console(file=io.StringIO(), force_terminal=False, width=80),
        )


def test_show_radar_plays_one_refresh_with_chafa_without_network_or_sleep() -> None:
    stream = io.StringIO()
    console = Console(file=stream, force_terminal=False, width=80)
    downloader = FakeDownloader()
    clock = MutableClock(100.0)
    player = FakeChafaPlayer(clock)

    exit_code = show_radar(
        "90210",
        console=console,
        renderer_name="symbols",
        width=80,
        height=24,
        downloader=downloader,
        radar_player=player,  # type: ignore[arg-type]
        zip_lookup=lambda _zip_code: [
            {
                "country": "US",
                "lat": "34.0901",
                "long": "-118.4065",
                "city": "Beverly Hills",
                "state": "CA",
                "zip_code": "90210",
            }
        ],
        clock=clock,
        sleeper=clock.sleep,
        max_refreshes=1,
    )

    assert exit_code == 0
    assert downloader.loop_station_ids == ["KVTX"]
    assert clock.current == 101.0
    assert len(player.calls) == 1
    assert player.calls[0].content == _gif_bytes()
    assert player.calls[0].duration_seconds == 1.0
    assert player.calls[0].options.renderer == "symbols"
    assert player.calls[0].options.width == 80
    assert player.calls[0].options.height == 24


def test_show_radar_fetches_next_gif_after_chafa_window() -> None:
    stream = io.StringIO()
    console = Console(file=stream, force_terminal=False, width=80)
    downloader = FakeDownloader()
    clock = MutableClock(100.0)
    player = FakeChafaPlayer(clock)

    exit_code = show_radar(
        "90210",
        console=console,
        renderer_name="kitty",
        width=12,
        height=6,
        downloader=downloader,
        radar_player=player,  # type: ignore[arg-type]
        zip_lookup=valid_zip_lookup,
        clock=clock,
        sleeper=clock.sleep,
        max_refreshes=2,
    )

    assert exit_code == 0
    assert downloader.loop_station_ids == ["KVTX", "KVTX"]
    assert clock.current == 102.0
    assert len(player.calls) == 2


def test_show_radar_returns_nonzero_when_chafa_fails() -> None:
    stream = io.StringIO()
    console = Console(file=stream, force_terminal=False, width=80)
    downloader = FakeDownloader()
    clock = MutableClock(100.0)

    exit_code = show_radar(
        "90210",
        console=console,
        renderer_name="kitty",
        downloader=downloader,
        radar_player=FailingChafaPlayer(),  # type: ignore[arg-type]
        zip_lookup=valid_zip_lookup,
        clock=clock,
        sleeper=clock.sleep,
        max_refreshes=1,
    )

    assert exit_code == 1
    assert "chafa failed" in stream.getvalue()


def valid_zip_lookup(_zip_code: str) -> list[dict[str, object]]:
    return [
        {
            "country": "US",
            "lat": "34.0901",
            "long": "-118.4065",
            "city": "Beverly Hills",
            "state": "CA",
            "zip_code": "90210",
        }
    ]


@dataclass
class MutableClock:
    current: float

    def __call__(self) -> float:
        return self.current

    def sleep(self, seconds: float) -> None:
        self.current += seconds


class FakeDownloader:
    def __init__(self) -> None:
        self.loop_station_ids: list[str] = []

    def fetch_stations(self) -> list[RadarStation]:
        return [
            RadarStation("KOKX", "New York City", 40.8656, -72.8647),
            RadarStation("KVTX", "Los Angeles", 34.4116, -119.1795),
        ]

    def fetch_loop(self, station_id: str) -> RadarLoop:
        self.loop_station_ids.append(station_id)
        return RadarLoop(
            content=_gif_bytes(),
            headers={"Cache-Control": "max-age=1"},
            url=f"https://radar.weather.gov/ridge/standard/{station_id}_loop.gif",
        )


@dataclass(frozen=True)
class FakeChafaCall:
    content: bytes
    duration_seconds: float
    options: ImageRenderOptions


class FakeChafaPlayer:
    def __init__(self, clock: MutableClock) -> None:
        self.clock = clock
        self.calls: list[FakeChafaCall] = []

    def play(
        self,
        content: bytes,
        *,
        duration_seconds: float,
        options: ImageRenderOptions,
        console: Console,
    ) -> None:
        self.calls.append(FakeChafaCall(content, duration_seconds, options))
        self.clock.sleep(duration_seconds)


class FailingChafaPlayer:
    def play(
        self,
        content: bytes,
        *,
        duration_seconds: float,
        options: ImageRenderOptions,
        console: Console,
    ) -> None:
        raise RadarError("chafa failed")


class RecordingRunner:
    def __init__(self, *, expected_content: bytes) -> None:
        self.expected_content = expected_content
        self.calls: list[list[str]] = []

    def __call__(
        self,
        command: list[str],
        *,
        check: bool,
    ) -> subprocess.CompletedProcess[object]:
        assert check is True
        gif_path = command[-1]
        assert os.path.exists(gif_path)
        with open(gif_path, "rb") as gif_file:
            assert gif_file.read() == self.expected_content
        self.calls.append(command)
        return subprocess.CompletedProcess(command, 0)


def _gif_bytes() -> bytes:
    output = io.BytesIO()
    frames = [
        Image.new("RGBA", (2, 2), (20, 80, 140, 255)),
        Image.new("RGBA", (2, 2), (180, 30, 80, 255)),
    ]
    frames[0].save(
        output,
        format="GIF",
        save_all=True,
        append_images=frames[1:],
        duration=[100, 100],
        loop=0,
    )
    return output.getvalue()
