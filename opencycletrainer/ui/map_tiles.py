from __future__ import annotations

from collections import OrderedDict
from dataclasses import dataclass, field
import math
from pathlib import Path
import time

import numpy as np
from PySide6.QtCore import QObject, QUrl, Signal
from PySide6.QtGui import QImage
from PySide6.QtNetwork import (
    QNetworkAccessManager,
    QNetworkDiskCache,
    QNetworkReply,
    QNetworkRequest,
)

from opencycletrainer import __version__
from opencycletrainer.storage.paths import ensure_dir, get_map_tile_cache_dir
from opencycletrainer.storage.settings import (
    MAP_TILE_SOURCE_CYCLOSM,
    MAP_TILE_SOURCE_OPENTOPOMAP,
    MAP_TILE_SOURCE_THUNDERFOREST_CYCLE,
)

TileKey = tuple[int, int, int]
"""A map tile as (zoom, x, y), in the standard XYZ ("slippy map") numbering."""

# Web Mercator (EPSG:3857), the projection XYZ tiles are drawn in.
_EARTH_RADIUS_M = 6_378_137.0
_HALF_WORLD_M = math.pi * _EARTH_RADIUS_M
TILE_SIZE_PX = 256

USER_AGENT = f"OpenCycleTrainer/{__version__}"
"""Identifies the app to tile servers, as the OpenStreetMap tile usage policy requires."""
MAX_CONCURRENT_DOWNLOADS = 2
"""Tile downloads in flight at once; tile servers are volunteer-run and ask clients to be light."""
_FAILED_TILE_RETRY_SECONDS = 60.0
_MEMORY_CACHE_TILES = 256
_DISK_CACHE_BYTES = 100 * 1024 * 1024

_OSM_ATTRIBUTION = "© OpenStreetMap contributors"

_WHOLE_ROUTE_PADDING_RATIO = 0.08  # margin around the route when it is shown whole
_MIN_WHOLE_ROUTE_SPAN_M = 200.0    # a tiny route still gets a sensible view


@dataclass(frozen=True)
class TileSource:
    """An XYZ tile server: its URL template, the credit it requires, and how far it zooms.

    The template uses ``{z}``, ``{x}`` and ``{y}``, plus ``{s}`` for sources that spread
    tiles across several servers named in *subdomains*.
    """

    name: str
    url_template: str
    attribution: str
    max_zoom: int = 19
    subdomains: tuple[str, ...] = field(default=())

    def tile_url(self, zoom: int, x: int, y: int) -> str:
        url = self.url_template
        if self.subdomains:
            url = url.replace("{s}", self.subdomains[(x + y) % len(self.subdomains)])
        return url.replace("{z}", str(zoom)).replace("{x}", str(x)).replace("{y}", str(y))


OPENSTREETMAP = TileSource(
    name="OpenStreetMap",
    url_template="https://tile.openstreetmap.org/{z}/{x}/{y}.png",
    attribution=_OSM_ATTRIBUTION,
    max_zoom=19,
)
CYCLOSM = TileSource(
    name="CyclOSM",
    url_template="https://{s}.tile-cyclosm.openstreetmap.fr/cyclosm/{z}/{x}/{y}.png",
    attribution=f"{_OSM_ATTRIBUTION}, style CyclOSM",
    max_zoom=20,
    subdomains=("a", "b", "c"),
)
OPENTOPOMAP = TileSource(
    name="OpenTopoMap",
    url_template="https://{s}.tile.opentopomap.org/{z}/{x}/{y}.png",
    attribution=f"{_OSM_ATTRIBUTION}, SRTM | style © OpenTopoMap (CC-BY-SA)",
    max_zoom=17,
    subdomains=("a", "b", "c"),
)


def thunderforest_cycle(api_key: str) -> TileSource:
    """Thunderforest's OpenCycleMap, which needs the rider's own (free tier) API key."""
    return TileSource(
        name="Thunderforest OpenCycleMap",
        url_template=f"https://tile.thunderforest.com/cycle/{{z}}/{{x}}/{{y}}.png?apikey={api_key}",
        attribution=f"Maps © Thunderforest, data {_OSM_ATTRIBUTION}",
        max_zoom=22,
    )


_SOURCE_BY_SETTING = {
    MAP_TILE_SOURCE_CYCLOSM: CYCLOSM,
    MAP_TILE_SOURCE_OPENTOPOMAP: OPENTOPOMAP,
}


def tile_source_for(setting: str, *, thunderforest_api_key: str = "") -> TileSource:
    """Return the tile server a ``map_tile_source`` setting names.

    Thunderforest needs the rider's API key; without one the map uses OpenStreetMap.
    """
    if setting == MAP_TILE_SOURCE_THUNDERFOREST_CYCLE:
        api_key = thunderforest_api_key.strip()
        return thunderforest_cycle(api_key) if api_key else OPENSTREETMAP
    return _SOURCE_BY_SETTING.get(setting, OPENSTREETMAP)


def _tile_size_m(zoom: int) -> float:
    return 2.0 * _HALF_WORLD_M / 2**zoom


def tile_bounds(zoom: int, x: int, y: int) -> tuple[float, float, float, float]:
    """Return a tile's (x_min, y_min, x_max, y_max) in Web Mercator metres; rows count down from the north."""
    size = _tile_size_m(zoom)
    return (
        x * size - _HALF_WORLD_M,
        _HALF_WORLD_M - (y + 1) * size,
        (x + 1) * size - _HALF_WORLD_M,
        _HALF_WORLD_M - y * size,
    )


def visible_tiles(view: tuple[float, float, float, float], zoom: int) -> list[TileKey]:
    """Return the tiles at *zoom* that cover *view* (x_min, x_max, y_min, y_max), within the world."""
    x_min, x_max, y_min, y_max = view
    size = _tile_size_m(zoom)
    last = 2**zoom - 1

    def clamp(index: float) -> int:
        return min(max(int(math.floor(index)), 0), last)

    first_x, last_x = clamp((x_min + _HALF_WORLD_M) / size), clamp((x_max + _HALF_WORLD_M) / size)
    first_y, last_y = clamp((_HALF_WORLD_M - y_max) / size), clamp((_HALF_WORLD_M - y_min) / size)
    return [
        (zoom, x, y)
        for y in range(first_y, last_y + 1)
        for x in range(first_x, last_x + 1)
    ]


def tile_zoom_for(metres_per_px: float, max_zoom: int) -> int:
    """Return the tile zoom whose pixels come closest to *metres_per_px* on screen, within 0..max_zoom."""
    exact = math.log2(2.0 * _HALF_WORLD_M / (TILE_SIZE_PX * metres_per_px))
    return min(max(int(math.floor(exact + 0.5)), 0), max_zoom)


def fit_view(
    xs: np.ndarray, ys: np.ndarray, width_px: float, height_px: float,
) -> tuple[tuple[float, float, float, float], float]:
    """Frame every point in a *width_px* × *height_px* view, with a margin, keeping the map's shape.

    Returns the view (x_min, x_max, y_min, y_max) in Web Mercator metres and the metres
    each pixel covers.
    """
    span_x = max(float(np.ptp(xs)), _MIN_WHOLE_ROUTE_SPAN_M)
    span_y = max(float(np.ptp(ys)), _MIN_WHOLE_ROUTE_SPAN_M)
    padded = 1.0 + 2.0 * _WHOLE_ROUTE_PADDING_RATIO
    metres_per_px = max(span_x * padded / width_px, span_y * padded / height_px)
    centre_x = (float(np.min(xs)) + float(np.max(xs))) / 2.0
    centre_y = (float(np.min(ys)) + float(np.max(ys))) / 2.0
    half_width = width_px * metres_per_px / 2.0
    half_height = height_px * metres_per_px / 2.0
    view = (centre_x - half_width, centre_x + half_width, centre_y - half_height, centre_y + half_height)
    return view, metres_per_px


class NetworkTileProvider(QObject):
    """Downloads the tiles the map wants from a tile server and keeps them for reuse.

    Downloads go through a disk cache that honours the server's cache headers, at most
    MAX_CONCURRENT_DOWNLOADS at a time, and only for tiles the map currently shows. A
    tile that failed (for example with no internet) is not asked for again for a while.
    """

    tile_ready = Signal(int, int, int)

    def __init__(
        self,
        source: TileSource,
        *,
        cache_dir: Path | None = None,
        parent: QObject | None = None,
    ) -> None:
        super().__init__(parent)
        self.source = source
        self._manager = QNetworkAccessManager(self)
        if cache_dir is not None:
            disk_cache = QNetworkDiskCache(self)
            disk_cache.setCacheDirectory(str(ensure_dir(cache_dir)))
            disk_cache.setMaximumCacheSize(_DISK_CACHE_BYTES)
            self._manager.setCache(disk_cache)
        self._images: OrderedDict[TileKey, QImage] = OrderedDict()
        self._queue: list[TileKey] = []
        self._in_flight: dict[QNetworkReply, TileKey] = {}
        self._failed_at: dict[TileKey, float] = {}
        self.requests_started = 0

    @property
    def requests_in_flight(self) -> int:
        return len(self._in_flight)

    def build_request(self, key: TileKey) -> QNetworkRequest:
        """Return the request for one tile, identifying the app and preferring cached copies."""
        request = QNetworkRequest(QUrl(self.source.tile_url(*key)))
        request.setRawHeader(b"User-Agent", USER_AGENT.encode("ascii"))
        request.setAttribute(
            QNetworkRequest.Attribute.CacheLoadControlAttribute,
            QNetworkRequest.CacheLoadControl.PreferCache,
        )
        return request

    def set_wanted(self, tiles: list[TileKey]) -> None:
        """Fetch *tiles* (the map's current view), dropping queued tiles it no longer shows."""
        in_flight = set(self._in_flight.values())
        now = time.monotonic()
        self._queue = [
            key for key in dict.fromkeys(tiles)
            if key not in self._images and key not in in_flight and not self._failed_recently(key, now)
        ]
        self._start_downloads()

    def image(self, key: TileKey) -> QImage | None:
        """Return a tile already downloaded, or None."""
        image = self._images.get(key)
        if image is not None:
            self._images.move_to_end(key)
        return image

    def _failed_recently(self, key: TileKey, now: float) -> bool:
        failed_at = self._failed_at.get(key)
        return failed_at is not None and now - failed_at < _FAILED_TILE_RETRY_SECONDS

    def _start_downloads(self) -> None:
        while self._queue and len(self._in_flight) < MAX_CONCURRENT_DOWNLOADS:
            key = self._queue.pop(0)
            reply = self._manager.get(self.build_request(key))
            self._in_flight[reply] = key
            self.requests_started += 1
            # A bound slot, not a lambda holding the reply: a lambda that keeps a reply
            # alive across deleteLater() crashes PySide6 once the provider is destroyed.
            reply.finished.connect(self._on_reply_finished)

    def _on_reply_finished(self) -> None:
        reply = self.sender()
        if isinstance(reply, QNetworkReply):
            self._on_finished(reply)

    def _on_finished(self, reply: QNetworkReply) -> None:
        key = self._in_flight.pop(reply, None)
        if key is not None:
            image = QImage()
            loaded = reply.error() == QNetworkReply.NetworkError.NoError and image.loadFromData(
                bytes(reply.readAll())
            )
            if loaded:
                self._store(key, image)
                self.tile_ready.emit(*key)
            else:
                self._failed_at[key] = time.monotonic()
        reply.deleteLater()
        self._start_downloads()

    def _store(self, key: TileKey, image: QImage) -> None:
        self._failed_at.pop(key, None)
        self._images[key] = image
        self._images.move_to_end(key)
        while len(self._images) > _MEMORY_CACHE_TILES:
            self._images.popitem(last=False)


def create_tile_provider(source: TileSource) -> NetworkTileProvider:
    """Return a provider of *source*'s tiles, cached on disk."""
    return NetworkTileProvider(source, cache_dir=get_map_tile_cache_dir())
