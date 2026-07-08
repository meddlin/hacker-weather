# Development Docs

## PoC: Display Radar images in the Terminal

```bash
brew install chafa
curl -o radar.gif https://radar.weather.gov/ridge/standard/CONUS_loop.gif
chafa radar.gif
```

## Radar CLI Flow

`hacker-weather --radar ZIP` uses the bundled `zipcodes` package for offline U.S.
ZIP-to-coordinate lookup, fetches WSR-88D station metadata from
`api.weather.gov`, selects the nearest station, and downloads the station GIF
loop from `radar.weather.gov/ridge/standard/{station}_loop.gif`.

The GIF response headers drive refresh timing. `Date` plus `Expires` is used
when available, `Cache-Control: max-age` is the next fallback, and 120 seconds is
used if NOAA does not return cache timing.

Radar playback writes the downloaded GIF to a temporary file and shells out to
the `chafa` CLI for the current NOAA cache window. The CLI receives
`--animate=on`, `--duration=<cache-window-seconds>`, `--clear`, renderer format
arguments when requested, and size arguments when provided. After Chafa returns,
the next radar GIF is fetched and the process repeats.

## Displaying Images in the CLI

Using Pillow and Chafa to get images displayed in the terminal.

Main Python stack:

- Textual
- Rich
- Pillow
- Chafa
