import requests
import polyline

OSRM_URL = "https://router.project-osrm.org/route/v1/driving/{lon1},{lat1};{lon2},{lat2}"


def get_route(start_coords, finish_coords):
    """start/finish: (lat, lon). Returns dict with distance_miles, duration_seconds, geometry."""
    lat1, lon1 = start_coords
    lat2, lon2 = finish_coords
    url = OSRM_URL.format(lon1=lon1, lat1=lat1, lon2=lon2, lat2=lat2)
    resp = requests.get(
        url,
        params={"overview": "full", "geometries": "polyline"},
        timeout=20,
    )
    resp.raise_for_status()
    route = resp.json()["routes"][0]
    return {
        "distance_miles": route["distance"] / 1609.344,
        "duration_seconds": route["duration"],
        "geometry": polyline.decode(route["geometry"]),
    }
