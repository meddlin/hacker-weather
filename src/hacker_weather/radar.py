from __future__ import annotations

import json
import math
import os
import re
import subprocess
import tempfile
import time
import urllib.request
from collections.abc import Callable, Mapping, Sequence
from contextlib import suppress
from dataclasses import dataclass
from datetime import UTC
from email.utils import parsedate_to_datetime
from io import BytesIO
from typing import Any

from PIL import Image, ImageSequence
from rich.console import Console

from .image_test import (
    ImageRenderError,
    ImageRenderOptions,
    ImageRenderResult,
    RendererName,
)

NWS_RADAR_STATIONS_URL = "https://api.weather.gov/radar/stations?stationType=WSR-88D"
RIDGE2_STANDARD_URL = "https://radar.weather.gov/ridge/standard/{station_id}_loop.gif"
USER_AGENT = "hacker-weather/0.1.0"
DEFAULT_REFRESH_SECONDS = 120.0
DEFAULT_FRAME_DELAY_SECONDS = 0.1
EARTH_RADIUS_KM = 6371.0088


@dataclass(frozen=True)
class ZipLocation:
    zip_code: str
    latitude: float
    longitude: float
    city: str
    state: str


@dataclass(frozen=True)
class RadarStation:
    station_id: str
    name: str
    latitude: float
    longitude: float


@dataclass(frozen=True)
class RadarLoop:
    content: bytes
    headers: Mapping[str, str]
    url: str


class RadarError(RuntimeError):
    pass


SubprocessRunner = Callable[..., subprocess.CompletedProcess[object]]


class RadarDownloader:
    def __init__(
        self,
        *,
        timeout: float = 20.0,
        urlopen: Callable[..., Any] = urllib.request.urlopen,
    ) -> None:
        self._timeout = timeout
        self._urlopen = urlopen

    def fetch_stations(self) -> Sequence[RadarStation]:
        request = urllib.request.Request(
            NWS_RADAR_STATIONS_URL,
            headers={
                "Accept": "application/geo+json",
                "User-Agent": USER_AGENT,
            },
        )
        with self._urlopen(request, timeout=self._timeout) as response:
            payload = json.loads(response.read().decode("utf-8"))
        return parse_radar_stations(payload)

    def fetch_loop(self, station_id: str) -> RadarLoop:
        url = RIDGE2_STANDARD_URL.format(station_id=station_id)
        request = urllib.request.Request(url, headers={"User-Agent": USER_AGENT})
        with self._urlopen(request, timeout=self._timeout) as response:
            return RadarLoop(
                content=response.read(),
                headers=dict(response.headers.items()),
                url=url,
            )


class ChafaRadarPlayer:
    def __init__(
        self,
        *,
        chafa_path: str = "chafa",
        runner: SubprocessRunner = subprocess.run,
    ) -> None:
        self._chafa_path = chafa_path
        self._runner = runner

    def play(
        self,
        content: bytes,
        *,
        duration_seconds: float,
        options: ImageRenderOptions,
        console: Console,
    ) -> None:
        temp_path = _write_temp_gif(content)
        try:
            command = _build_chafa_command(
                self._chafa_path,
                temp_path,
                duration_seconds=duration_seconds,
                options=options,
            )
            self._runner(command, check=True)
        except FileNotFoundError as error:
            raise RadarError(
                "chafa is not installed or not on PATH. Install it with "
                "`brew install chafa`."
            ) from error
        except subprocess.CalledProcessError as error:
            raise RadarError(
                f"chafa radar playback failed with exit code {error.returncode}"
            ) from error
        finally:
            with suppress(FileNotFoundError):
                os.unlink(temp_path)


def resolve_zip_code(
    zip_code: str,
    *,
    lookup: Callable[[str], Sequence[Mapping[str, Any]]] | None = None,
) -> ZipLocation:
    lookup_zip = lookup or _zipcodes_matching
    try:
        matches = lookup_zip(zip_code)
    except (TypeError, ValueError) as error:
        raise RadarError(f"Invalid ZIP code {zip_code!r}: {error}") from error

    if not matches:
        raise RadarError(f"ZIP code {zip_code!r} was not found")

    for entry in matches:
        country = str(entry.get("country", "")).upper()
        latitude = entry.get("lat")
        longitude = entry.get("long")
        if country == "US" and latitude is not None and longitude is not None:
            try:
                return ZipLocation(
                    zip_code=str(entry.get("zip_code", zip_code)),
                    latitude=float(latitude),
                    longitude=float(longitude),
                    city=str(entry.get("city", "")),
                    state=str(entry.get("state", "")),
                )
            except (TypeError, ValueError) as error:
                raise RadarError(
                    f"ZIP code {zip_code!r} has invalid coordinates"
                ) from error

    raise RadarError("Only U.S. ZIP codes with coordinates are supported")


def parse_radar_stations(payload: Mapping[str, Any]) -> list[RadarStation]:
    stations: list[RadarStation] = []
    for feature in payload.get("features", []):
        if not isinstance(feature, Mapping):
            continue

        geometry = feature.get("geometry")
        properties = feature.get("properties")
        if not isinstance(geometry, Mapping) or not isinstance(properties, Mapping):
            continue

        coordinates = geometry.get("coordinates")
        if not isinstance(coordinates, Sequence) or len(coordinates) < 2:
            continue

        station_id = properties.get("id")
        if not station_id:
            continue

        try:
            longitude = float(coordinates[0])
            latitude = float(coordinates[1])
        except (TypeError, ValueError):
            continue

        stations.append(
            RadarStation(
                station_id=str(station_id),
                name=str(properties.get("name", station_id)),
                latitude=latitude,
                longitude=longitude,
            )
        )

    if not stations:
        raise RadarError("No NWS radar stations were returned")

    return stations


def select_nearest_station(
    location: ZipLocation, stations: Sequence[RadarStation]
) -> RadarStation:
    if not stations:
        raise RadarError("No NWS radar stations are available")
    return min(
        stations,
        key=lambda station: haversine_km(
            location.latitude,
            location.longitude,
            station.latitude,
            station.longitude,
        ),
    )


def haversine_km(
    latitude_a: float,
    longitude_a: float,
    latitude_b: float,
    longitude_b: float,
) -> float:
    lat_a = math.radians(latitude_a)
    lat_b = math.radians(latitude_b)
    delta_lat = math.radians(latitude_b - latitude_a)
    delta_lon = math.radians(longitude_b - longitude_a)
    half_chord = (
        math.sin(delta_lat / 2) ** 2
        + math.cos(lat_a) * math.cos(lat_b) * math.sin(delta_lon / 2) ** 2
    )
    return 2 * EARTH_RADIUS_KM * math.asin(math.sqrt(half_chord))


def calculate_refresh_deadline(
    headers: Mapping[str, str],
    *,
    now: float,
    fallback_seconds: float = DEFAULT_REFRESH_SECONDS,
) -> float:
    normalized = {key.lower(): value for key, value in headers.items()}

    date_timestamp = _parse_http_timestamp(normalized.get("date"))
    expires_timestamp = _parse_http_timestamp(normalized.get("expires"))
    if date_timestamp is not None and expires_timestamp is not None:
        return now + max(0.0, expires_timestamp - date_timestamp)
    if expires_timestamp is not None:
        return expires_timestamp

    max_age = _parse_max_age(normalized.get("cache-control", ""))
    if max_age is not None:
        return now + max_age

    return now + fallback_seconds


def iter_gif_frames(content: bytes) -> list[tuple[Image.Image, float]]:
    try:
        image = Image.open(BytesIO(content))
    except Exception as error:
        raise RadarError(f"Downloaded radar image is not readable: {error}") from error

    frames: list[tuple[Image.Image, float]] = []
    for frame in ImageSequence.Iterator(image):
        default_duration_ms = round(DEFAULT_FRAME_DELAY_SECONDS * 1000)
        duration_ms = frame.info.get("duration", default_duration_ms)
        delay = max(float(duration_ms) / 1000, DEFAULT_FRAME_DELAY_SECONDS)
        frames.append((frame.convert("RGBA"), delay))

    if not frames:
        raise RadarError("Downloaded radar GIF did not contain any frames")

    return frames


def show_radar(
    zip_code: str,
    *,
    console: Console | None = None,
    renderer: Callable[[Image.Image, ImageRenderOptions], ImageRenderResult]
    | None = None,
    renderer_name: RendererName = "auto",
    width: int | None = None,
    height: int | None = None,
    downloader: RadarDownloader | None = None,
    radar_player: ChafaRadarPlayer | None = None,
    zip_lookup: Callable[[str], Sequence[Mapping[str, Any]]] | None = None,
    clock: Callable[[], float] = time.time,
    sleeper: Callable[[float], None] = time.sleep,
    max_refreshes: int | None = None,
) -> int:
    output_console = console or Console()
    client = downloader or RadarDownloader()
    player = radar_player or ChafaRadarPlayer()

    try:
        location = resolve_zip_code(zip_code, lookup=zip_lookup)
        station = select_nearest_station(location, client.fetch_stations())
    except RadarError as error:
        output_console.print(f"[red]{error}[/red]")
        return 1
    except Exception as error:
        output_console.print(f"[red]Unable to initialize radar playback: {error}[/red]")
        return 1

    output_console.print(
        f"[bold cyan]Radar loop for {location.zip_code}[/bold cyan] "
        f"[dim]({location.city}, {location.state}; {station.station_id} "
        f"{station.name})[/dim]"
    )

    refreshes = 0
    options = ImageRenderOptions(renderer=renderer_name, width=width, height=height)

    try:
        while max_refreshes is None or refreshes < max_refreshes:
            loop = client.fetch_loop(station.station_id)
            now = clock()
            deadline = calculate_refresh_deadline(loop.headers, now=now)
            duration_seconds = max(0.0, deadline - now)
            refreshes += 1
            title = (
                f"{station.station_id} radar loop; refreshes at "
                f"{_format_timestamp(deadline)}"
            )
            output_console.print(f"[bold cyan]{title}[/bold cyan]")
            player.play(
                loop.content,
                duration_seconds=duration_seconds,
                options=options,
                console=output_console,
            )
    except KeyboardInterrupt:
        output_console.print("\n[dim]Radar playback stopped.[/dim]")
        return 0
    except ImageRenderError as error:
        output_console.print(f"[red]{error}[/red]")
        return 1
    except RadarError as error:
        output_console.print(f"[red]{error}[/red]")
        return 1
    except Exception as error:
        output_console.print(f"[red]Radar playback failed: {error}[/red]")
        return 1

    return 0


def _play_frames_until_deadline(
    frames: Sequence[tuple[Image.Image, float]],
    *,
    deadline: float,
    console: Console,
    render: Callable[[Image.Image, ImageRenderOptions], ImageRenderResult],
    options: ImageRenderOptions,
    clock: Callable[[], float],
    sleeper: Callable[[float], None],
    title: str,
) -> None:
    while clock() < deadline:
        for frame, delay in frames:
            remaining = deadline - clock()
            if remaining <= 0:
                return

            result = render(frame, options)
            console.file.write("\x1b[H")
            with console.capture() as capture:
                console.print(f"[bold cyan]{title}[/bold cyan]")
                console.print(f"[dim]{result.status}[/dim]")
            console.file.write(capture.get())
            image_output = result.output
            if not image_output.endswith("\n"):
                image_output = f"{image_output}\n"
            console.file.write(image_output)
            console.file.write("\x1b[J")
            console.file.flush()
            sleeper(min(delay, max(0.0, deadline - clock())))


def _write_temp_gif(content: bytes) -> str:
    with tempfile.NamedTemporaryFile(delete=False, suffix=".gif") as temp_file:
        temp_file.write(content)
        return temp_file.name


def _build_chafa_command(
    chafa_path: str,
    gif_path: str,
    *,
    duration_seconds: float,
    options: ImageRenderOptions,
) -> list[str]:
    command = [
        chafa_path,
        "--animate=on",
        f"--duration={duration_seconds:.3f}",
        "--clear",
    ]
    renderer_format = _chafa_format(options.renderer)
    if renderer_format is not None:
        command.append(f"--format={renderer_format}")
    size = _chafa_size(options.width, options.height)
    if size is not None:
        command.append(f"--size={size}")
    command.append(gif_path)
    return command


def _chafa_format(renderer_name: RendererName) -> str | None:
    return {
        "auto": None,
        "kitty": "kitty",
        "iterm2": "iterm",
        "sixel": "sixels",
        "symbols": "symbols",
    }[renderer_name]


def _chafa_size(width: int | None, height: int | None) -> str | None:
    if width is None and height is None:
        return None
    width_part = "" if width is None else str(width)
    height_part = "" if height is None else str(height)
    return f"{width_part}x{height_part}"


def _zipcodes_matching(zip_code: str) -> Sequence[Mapping[str, Any]]:
    import zipcodes

    return zipcodes.matching(zip_code)


def _parse_http_timestamp(value: str | None) -> float | None:
    if not value:
        return None
    try:
        parsed = parsedate_to_datetime(value)
    except (TypeError, ValueError):
        return None
    if parsed.tzinfo is None:
        parsed = parsed.replace(tzinfo=UTC)
    return parsed.timestamp()


def _parse_max_age(cache_control: str) -> float | None:
    match = re.search(r"(?:^|,)\s*max-age=(\d+)\s*(?:,|$)", cache_control)
    if not match:
        return None
    return float(match.group(1))


def _format_timestamp(timestamp: float) -> str:
    return time.strftime("%H:%M:%S", time.localtime(timestamp))
