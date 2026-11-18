# Course ride ideas

Unsorted notes to explore later, written after the first round of GPX course rides and grade
simulation (v0.9.0). Each item has a little context on where it would fit; none of this is
designed yet.

## Map view

A map panel on the right of the workout screen, as tall as the course profile and power plot
together, shown on course rides only.

Decisions:

- Drawn in Qt by the app itself, not an embedded web view (Leaflet would pull in Qt's
  Chromium, 100+ MB and awkward to package for Flatpak) and not QtLocation (its OpenStreetMap
  plugin has relied on Qt-run redirect servers and providers that need API keys).
- The route is drawn from the course's own coordinates, so it works offline. Map tiles are
  only a background layer; with no internet the route shows on a plain background.
- Route still to ride in red, ridden part in green, the rider as a small dot like the one on
  the elevation profile. A lapped course shows one lap's geometry, coloured for the lap being
  ridden.
- Default tile source: OpenStreetMap. Opens in Follow mode (centred on the rider at road zoom),
  with Whole route one click away. The panel starts expanded.
- Using it needs internet only for the tiles, like intervals.icu sync; it never stops a ride.

OpenStreetMap tile usage policy, which the tile layer must follow: send a User-Agent that
identifies the app, show "© OpenStreetMap contributors" on the map, cache tiles and respect
their cache headers, and never download tiles in bulk ahead of time.

### Phases

1. **Panel and offline route.** *(Done in v0.12.0.)* Collapsible panel on course rides with the route (red ahead,
   green ridden), start and finish markers, the rider dot, Follow / Whole route toggle and
   +/− zoom. Positions are in Web Mercator so tiles can sit under the route in phase 2.
2. **Tile background.** *(Done in v0.13.0; presets are in code, choosing one comes with phase 3.)* OpenStreetMap tiles fetched with a QNetworkAccessManager, kept in a
   disk cache, with attribution and an identifying User-Agent. Further presets (CyclOSM,
   OpenTopoMap, Thunderforest OpenCycleMap with an API key) and a custom URL.
3. **Settings.** "Show map on course rides" toggle and tile source choice in Settings →
   Charts; remember the panel's width and whether it is collapsed.
4. **Later.** Draw the map into the saved ride PNG; show points of interest if FIT course
   import happens.

## Import FIT for POIs?

- FIT course files carry course points (climbs, sprints, food, turns) that GPX usually
  doesn't. fit-tool is already a dependency and can read them.
- Would need to decide how POIs show up: markers on the elevation profile, the map, or a
  "next POI in X km" tile.
- Could also accept a FIT course as the course itself, not just for POIs.

## Show / record elevation gain

- Total ascent and descent are already written to the FIT session, but nothing on screen shows
  them.
- Ideas: an elevation gained tile (and gain remaining on the course), and climbing totals in the
  end-of-ride summary.

## Switch surfaces mid course (manual)

- The road surface can already change mid-ride, but only from the Settings tab.
- A control on the workout screen, or a hotkey, would let the rider change it while riding,
  e.g. when the course turns onto gravel.
- Further out: surface per section of the course, stored with the course or set on import.
