# hacker-weather

`hacker-weather` is a Python CLI for terminal-first weather visualization. It can render a sample rainy weather image and display current NWS radar GIF loops for U.S. ZIP codes.

## Requirements

- Python 3.12+
- uv
- Chafa for radar GIF playback
- Opengrep for local SAST scanning

## Setup

```bash
uv sync --dev
```

## CLI

```bash
uv run hacker-weather --help
uv run hacker-weather --version
uv run hacker-weather --image-test
uv run hacker-weather --image-test --image-renderer symbols --image-width 120
uv run hacker-weather --image-test --image-renderer kitty --image-width 120
uv run hacker-weather --radar 90210
uv run hacker-weather --radar 90210 --image-renderer symbols --image-width 120
```

`--image-renderer auto` is the default. It uses Kitty graphics for Ghostty, Kitty,
and WezTerm; iTerm2 graphics for iTerm2; and Chafa symbols elsewhere. If native
graphics are not detected, the command prints the fallback reason before the image.

`--radar ZIP` resolves a U.S. ZIP code locally, chooses the nearest NWS WSR-88D
station, downloads the current RIDGE2 GIF loop, and refreshes when NOAA's cache
window expires. Radar playback shells out to `chafa`; install it with
`brew install chafa` if it is not already available. Press `Ctrl-C` to stop
playback.

## Local Development

```bash
uv run pytest
uv run ruff check .
uv run ruff format .
opengrep scan --config opengrep-rules src tests
```

Install Opengrep with the official installer if it is not already available:

```bash
curl -fsSL https://raw.githubusercontent.com/opengrep/opengrep/main/install.sh | bash
```
