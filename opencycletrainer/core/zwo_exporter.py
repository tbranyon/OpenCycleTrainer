from __future__ import annotations

import xml.etree.ElementTree as ET

from opencycletrainer.core.workout_model import Workout


def workout_to_zwo_text(workout: Workout, category: str = "") -> str:
    """Convert a Workout to ZWO XML format text.

    Power values on WorkoutInterval are stored as 0-100 percent FTP; the ZWO
    format uses 0.0-1.0 fractions, so values are divided by 100 on output.
    Category is stored in an <oct_category> element (the OCT convention used by
    the ZWO parser and inject_category_into_zwo_text).
    """
    root = ET.Element("workout_file")
    ET.SubElement(root, "name").text = workout.name
    ET.SubElement(root, "description").text = ""
    ET.SubElement(root, "sportType").text = "bike"
    if category:
        ET.SubElement(root, "oct_category").text = category

    workout_el = ET.SubElement(root, "workout")
    for iv in workout.intervals:
        if iv.free_ride:
            el = ET.SubElement(workout_el, "FreeRide")
            el.set("Duration", str(iv.duration_seconds))
        elif iv.is_ramp:
            el = ET.SubElement(workout_el, "Ramp")
            el.set("Duration", str(iv.duration_seconds))
            el.set("PowerLow", f"{iv.start_percent_ftp / 100:.4f}")
            el.set("PowerHigh", f"{iv.end_percent_ftp / 100:.4f}")
        else:
            el = ET.SubElement(workout_el, "SteadyState")
            el.set("Duration", str(iv.duration_seconds))
            el.set("Power", f"{iv.start_percent_ftp / 100:.4f}")

    ET.indent(root, space="  ")
    body = ET.tostring(root, encoding="unicode")
    return f'<?xml version="1.0" encoding="UTF-8"?>\n{body}\n'
