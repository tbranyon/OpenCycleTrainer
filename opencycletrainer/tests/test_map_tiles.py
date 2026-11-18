from __future__ import annotations

import math
import time

import pytest
from PySide6.QtCore import QCoreApplication
from PySide6.QtGui import QColor, QImage

from opencycletrainer import __version__
from opencycletrainer.ui.map_tiles import (
    CYCLOSM,
    OPENSTREETMAP,
    OPENTOPOMAP,
    MAX_CONCURRENT_DOWNLOADS,
    NetworkTileProvider,
    TileSource,
    thunderforest_cycle,
    tile_bounds,
    tile_source_for,
    tile_zoom_for,
    visible_tiles,
)

_HALF_WORLD_M = math.pi * 6_378_137.0


# ── Tile maths ────────────────────────────────────────────────────────────────

def test_zoom_zero_is_one_tile_covering_the_world():
    assert tile_bounds(0, 0, 0) == pytest.approx((-_HALF_WORLD_M, -_HALF_WORLD_M, _HALF_WORLD_M, _HALF_WORLD_M))


def test_tile_rows_count_down_from_the_north():
    # (x_min, y_min, x_max, y_max): tile (0, 0) at zoom 1 is the north-west quarter.
    assert tile_bounds(1, 0, 0) == pytest.approx((-_HALF_WORLD_M, 0.0, 0.0, _HALF_WORLD_M))
    assert tile_bounds(1, 1, 1) == pytest.approx((0.0, -_HALF_WORLD_M, _HALF_WORLD_M, 0.0))


def test_visible_tiles_cover_the_view():
    x0, y0, x1, y1 = tile_bounds(10, 530, 360)
    view = (x0 + 1.0, x1 + 1.0, y0 - 1.0, y1 - 1.0)  # nudged into the neighbours east and south

    tiles = visible_tiles(view, 10)

    assert set(tiles) == {(10, 530, 360), (10, 531, 360), (10, 530, 361), (10, 531, 361)}


def test_visible_tiles_stay_inside_the_world():
    huge = (-10 * _HALF_WORLD_M, 10 * _HALF_WORLD_M, -10 * _HALF_WORLD_M, 10 * _HALF_WORLD_M)

    assert set(visible_tiles(huge, 1)) == {(1, 0, 0), (1, 1, 0), (1, 0, 1), (1, 1, 1)}


def test_tile_zoom_matches_tiles_to_screen_pixels():
    metres_per_px_at_15 = 2 * _HALF_WORLD_M / (256 * 2**15)

    assert tile_zoom_for(metres_per_px_at_15, max_zoom=19) == 15
    assert tile_zoom_for(metres_per_px_at_15 * 1.3, max_zoom=19) == 15
    assert tile_zoom_for(metres_per_px_at_15 * 2.0, max_zoom=19) == 14
    assert tile_zoom_for(metres_per_px_at_15 / 64, max_zoom=17) == 17
    assert tile_zoom_for(1e12, max_zoom=19) == 0


# ── Tile sources ──────────────────────────────────────────────────────────────

def test_openstreetmap_tile_url_and_attribution():
    assert OPENSTREETMAP.tile_url(15, 17000, 11500) == "https://tile.openstreetmap.org/15/17000/11500.png"
    assert OPENSTREETMAP.attribution == "© OpenStreetMap contributors"


def test_sources_with_several_servers_spread_tiles_across_them():
    urls = {CYCLOSM.tile_url(15, x, 11500) for x in range(17000, 17006)}

    assert len({url.split("//")[1].split(".")[0] for url in urls}) == 3
    assert all("{s}" not in url for url in urls)


def test_presets_credit_openstreetmap():
    for source in (CYCLOSM, OPENTOPOMAP, thunderforest_cycle("key")):
        assert "OpenStreetMap contributors" in source.attribution


def test_thunderforest_needs_an_api_key_in_its_urls():
    url = thunderforest_cycle("abc123").tile_url(12, 1, 2)

    assert url == "https://tile.thunderforest.com/cycle/12/1/2.png?apikey=abc123"


def test_custom_source_fills_in_its_template():
    source = TileSource(name="Mine", url_template="https://tiles.example/{z}/{x}/{y}.png", attribution="Me")

    assert source.tile_url(3, 4, 5) == "https://tiles.example/3/4/5.png"


# ── Fetching ──────────────────────────────────────────────────────────────────

def _write_tile(folder, z: int, x: int, y: int) -> None:
    path = folder / str(z) / str(x)
    path.mkdir(parents=True, exist_ok=True)
    image = QImage(256, 256, QImage.Format.Format_RGB32)
    image.fill(QColor(10, 20, 30))
    assert image.save(str(path / f"{y}.png"))


def _local_source(folder) -> TileSource:
    return TileSource(
        name="Local", url_template=folder.as_uri() + "/{z}/{x}/{y}.png", attribution="Local tiles"
    )


def _wait_for(predicate, timeout_s: float = 3.0) -> bool:
    deadline = time.monotonic() + timeout_s
    while time.monotonic() < deadline:
        QCoreApplication.processEvents()
        if predicate():
            return True
        time.sleep(0.01)
    return predicate()


def test_requests_identify_the_app(qapp, tmp_path):
    provider = NetworkTileProvider(OPENSTREETMAP, cache_dir=tmp_path)

    request = provider.build_request((15, 1, 2))

    assert bytes(request.rawHeader("User-Agent")).decode() == f"OpenCycleTrainer/{__version__}"
    assert request.url().toString() == "https://tile.openstreetmap.org/15/1/2.png"


def test_wanted_tiles_are_fetched_and_announced(qapp, tmp_path):
    tiles = tmp_path / "tiles"
    _write_tile(tiles, 5, 1, 2)
    provider = NetworkTileProvider(_local_source(tiles), cache_dir=tmp_path / "cache")
    ready: list[tuple[int, int, int]] = []
    provider.tile_ready.connect(lambda z, x, y: ready.append((z, x, y)))

    provider.set_wanted([(5, 1, 2)])

    assert _wait_for(lambda: ready == [(5, 1, 2)])
    image = provider.image((5, 1, 2))
    assert image is not None and image.width() == 256


def test_a_tile_already_held_is_not_fetched_again(qapp, tmp_path):
    tiles = tmp_path / "tiles"
    _write_tile(tiles, 5, 1, 2)
    provider = NetworkTileProvider(_local_source(tiles), cache_dir=tmp_path / "cache")
    provider.set_wanted([(5, 1, 2)])
    assert _wait_for(lambda: provider.image((5, 1, 2)) is not None)
    started = provider.requests_started

    provider.set_wanted([(5, 1, 2)])
    QCoreApplication.processEvents()

    assert provider.requests_started == started


def test_a_failed_tile_is_not_retried_straight_away(qapp, tmp_path):
    provider = NetworkTileProvider(_local_source(tmp_path / "empty"), cache_dir=tmp_path / "cache")
    provider.set_wanted([(5, 1, 2)])
    assert _wait_for(lambda: provider.requests_in_flight == 0 and provider.requests_started == 1)

    for _ in range(5):
        provider.set_wanted([(5, 1, 2)])
        QCoreApplication.processEvents()

    assert provider.requests_started == 1
    assert provider.image((5, 1, 2)) is None


def test_downloads_are_limited_and_unwanted_ones_dropped_from_the_queue(qapp, tmp_path):
    tiles = tmp_path / "tiles"
    keys = [(6, x, 7) for x in range(8)]
    for key in keys:
        _write_tile(tiles, *key)
    provider = NetworkTileProvider(_local_source(tiles), cache_dir=tmp_path / "cache")

    provider.set_wanted(keys)
    assert provider.requests_in_flight <= MAX_CONCURRENT_DOWNLOADS
    provider.set_wanted(keys[:3])

    assert _wait_for(lambda: provider.requests_in_flight == 0)
    fetched = [key for key in keys if provider.image(key) is not None]
    assert set(keys[:3]) <= set(fetched)
    assert len(fetched) < len(keys)


# ── Choosing a source ─────────────────────────────────────────────────────────

@pytest.mark.parametrize(
    "setting, expected",
    [("openstreetmap", OPENSTREETMAP), ("cyclosm", CYCLOSM), ("opentopomap", OPENTOPOMAP)],
)
def test_each_tile_source_setting_picks_its_server(setting, expected):
    assert tile_source_for(setting) == expected


def test_thunderforest_tiles_are_fetched_with_the_riders_api_key():
    source = tile_source_for("thunderforest_cycle", thunderforest_api_key=" abc123 ")

    assert source.tile_url(3, 4, 5) == "https://tile.thunderforest.com/cycle/3/4/5.png?apikey=abc123"


@pytest.mark.parametrize("api_key", ["", "   "])
def test_thunderforest_without_an_api_key_falls_back_to_openstreetmap(api_key):
    assert tile_source_for("thunderforest_cycle", thunderforest_api_key=api_key) == OPENSTREETMAP
