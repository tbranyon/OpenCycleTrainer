# Course ride ideas

Unsorted notes to explore later, written after the first round of GPX course rides and grade
simulation (v0.9.0). Each item has a little context on where it would fit; none of this is
designed yet.

## Map view

- Show the route from above with the rider's position on it.
- The data is already there: every `CoursePoint` keeps latitude and longitude, and
  `CourseRide.position` gives the rider's current coordinates.
- A street or terrain basemap needs map tiles from the internet, which goes against "no
  internet access required". Drawing just the route outline offline (on a plain background,
  or pyqtgraph like the other charts) avoids that. A basemap could be optional.

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

## Add map view to the PNG?

- The finished ride's chart is saved as a PNG (`ui/chart_export.py`). Once there is a map view,
  the route could be drawn into that image too.

## Switch surfaces mid course (manual)

- The road surface can already change mid-ride, but only from the Settings tab.
- A control on the workout screen, or a hotkey, would let the rider change it while riding,
  e.g. when the course turns onto gravel.
- Further out: surface per section of the course, stored with the course or set on import.
