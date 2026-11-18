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
2. **Tile background.** *(Done in v0.13.0.)* OpenStreetMap tiles fetched with a QNetworkAccessManager, kept in a
   disk cache, with attribution and an identifying User-Agent. Further presets (CyclOSM,
   OpenTopoMap, Thunderforest OpenCycleMap with an API key). A custom tile URL is not done.
3. **Settings.** *(Done in v0.14.0.)* "Show map on course rides" toggle, tile source choice and
   Thunderforest API key in Settings → Charts; the panel's edge can be dragged, and its width
   and whether it is collapsed are remembered between rides.
4. **Map in the ride image.** *(Done in v0.15.0.)* On course rides the saved ride PNG has the
   whole route beside the chart, ridden road in green and any left in red. Its tiles are
   fetched when the ride ends and the image is written once they arrive (or after a few
   seconds with those that did; straight away if the app is closing).
5. **Points of interest.** *(Done in v0.16.0.)* POIs from the course file show as small icons
   on the map (shaped and coloured by kind) for the lap being ridden; hovering one shows
   what the file says about it and how far ahead it is.

## Course files and POIs

*(Done in v0.16.0.)* Courses load from GPX, TCX and FIT files (TCX and FIT activities work
too). Distances are measured from the coordinates for every format. Points of interest come
from TCX and FIT course points (turn cues are left out) and from GPX waypoints within
100 m of the route. They show as subtle markers on the elevation profile and icons on the
map. Hovering one shows its name, kind and notes (FIT has no notes), then its distance along
the course and how far ahead of the rider it is.

Still open:

- A "next POI in X km" tile.
- Turn cues, if there is ever a use for them indoors.

## Elevation gain

*(Done in v0.16.0.)* An "Elevation Gain" tile shows the climbing done and still to come on
a course ride. Still open: climbing totals in the end-of-ride summary.

## Switch surfaces mid course (manual)

- The road surface can already change mid-ride, but only from the Settings tab.
- A control on the workout screen, or a hotkey, would let the rider change it while riding,
  e.g. when the course turns onto gravel.
- Further out: surface per section of the course, stored with the course or set on import.
