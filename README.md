# hacker-weather

`hacker-weather` is a Python CLI for terminal-first weather visualization. The first iteration focuses on a terminal-rendered rainy weather image test that will become the radar rendering path.

NOAA API integrations are intentionally not included yet.

## Requirements

- Python 3.12+
- uv
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
```

`--image-renderer auto` is the default. It uses Kitty graphics for Ghostty, Kitty,
and WezTerm; iTerm2 graphics for iTerm2; and Chafa symbols elsewhere. If native
graphics are not detected, the command prints the fallback reason before the image.

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
