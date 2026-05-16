from textual.app import App, ComposeResult
from textual.widgets import Footer, Header, Static


class HackerWeatherApp(App[None]):
    """Placeholder Textual app for the future radar browser."""

    TITLE = "hacker-weather"
    SUB_TITLE = "Terminal weather radar"

    def compose(self) -> ComposeResult:
        yield Header()
        yield Static("Radar visualization is coming soon.", id="status")
        yield Footer()
