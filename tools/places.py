"""Build web/places.json: Wisconsin's cities, villages, census-designated places and counties, for the map's
place names. Public 2020 census data (TIGERweb). Run again only if you want newer census numbers.

    .venv/bin/python tools/places.py
"""
import json
import pathlib
import urllib.parse
import urllib.request

TIGER = "https://tigerweb.geo.census.gov/arcgis/rest/services/TIGERweb/tigerWMS_Census2020/MapServer"
OUT = pathlib.Path(__file__).resolve().parent.parent / "web" / "places.json"


def query(layer):
    q = urllib.parse.urlencode({"where": "STATE='55'", "outFields": "BASENAME,POP100,INTPTLAT,INTPTLON",
                                "returnGeometry": "false", "f": "json", "resultRecordCount": 2000})
    with urllib.request.urlopen(f"{TIGER}/{layer}/query?{q}", timeout=60) as r:
        return [f["attributes"] for f in json.load(r)["features"]]


def main():
    rows = []
    # kind: "t" a city or village (incorporated), "d" a census-designated place (a named community without
    # its own government), "k" a county.
    for layer, kind in ((26, "t"), (28, "d"), (82, "k")):
        for a in query(layer):
            rows.append([a["BASENAME"], round(float(a["INTPTLON"]), 4), round(float(a["INTPTLAT"]), 4), a["POP100"] or 0, kind])
    rows.sort(key=lambda r: -r[3])
    OUT.write_text(json.dumps(rows, separators=(",", ":")))
    print(f"{len(rows)} places, {OUT.stat().st_size / 1e3:.0f} kB -> {OUT}")


if __name__ == "__main__":
    main()
