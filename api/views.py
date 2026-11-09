import numpy as np
from geopy.extra.rate_limiter import RateLimiter
from geopy.geocoders import Nominatim
from rest_framework import status
from rest_framework.response import Response
from rest_framework.views import APIView

from .models import FuelStation
from .serializers import RouteRequestSerializer
from .services.fuel_optimizer import (
    MAX_RANGE_MILES,
    MPG,
    StationOnRoute,
    optimize_fuel_stops,
)
from .services.routing import get_route


CORRIDOR_MILES = 40.0


class RouteFuelView(APIView):
    def post(self, request):
        serializer = RouteRequestSerializer(data=request.data)
        if not serializer.is_valid():
            return Response(serializer.errors, status=status.HTTP_400_BAD_REQUEST)

        start_text = serializer.validated_data["start"]
        finish_text = serializer.validated_data["finish"]

        geolocator = Nominatim(user_agent="spotter-fuel-assessment")
        geocode = RateLimiter(geolocator.geocode, min_delay_seconds=1.0)

        try:
            start_loc = geocode(f"{start_text}, USA", timeout=15)
            finish_loc = geocode(f"{finish_text}, USA", timeout=15)
        except Exception as exc:
            return Response(
                {"error": f"Geocoding failed: {exc}"},
                status=status.HTTP_502_BAD_GATEWAY,
            )

        if not start_loc or not finish_loc:
            return Response(
                {"error": "Could not geocode start or finish location"},
                status=status.HTTP_400_BAD_REQUEST,
            )

        try:
            route = get_route(
                (start_loc.latitude, start_loc.longitude),
                (finish_loc.latitude, finish_loc.longitude),
            )
        except Exception as exc:
            return Response(
                {"error": f"Routing failed: {exc}"},
                status=status.HTTP_502_BAD_GATEWAY,
            )

        stations_on_route = self._stations_along_route(
            route["geometry"], route["distance_miles"]
        )

        try:
            fuel_stops, total_cost = optimize_fuel_stops(
                route["distance_miles"], stations_on_route
            )
        except ValueError as exc:
            return Response(
                {
                    "error": str(exc),
                    "route_distance_miles": round(route["distance_miles"], 2),
                    "stations_found_on_route": len(stations_on_route),
                },
                status=status.HTTP_422_UNPROCESSABLE_ENTITY,
            )

        return Response(
            {
                "start": {
                    "text": start_text,
                    "latitude": start_loc.latitude,
                    "longitude": start_loc.longitude,
                },
                "finish": {
                    "text": finish_text,
                    "latitude": finish_loc.latitude,
                    "longitude": finish_loc.longitude,
                },
                "route": {
                    "distance_miles": round(route["distance_miles"], 2),
                    "duration_seconds": route["duration_seconds"],
                    "geometry": route["geometry"],
                },
                "vehicle": {
                    "max_range_miles": MAX_RANGE_MILES,
                    "miles_per_gallon": MPG,
                    "starts_with_full_tank": True,
                },
                "fuel_stops": [
                    {
                        "name": stop.station.name,
                        "city": stop.station.city,
                        "state": stop.station.state,
                        "price_per_gallon": round(stop.station.price_per_gallon, 3),
                        "mile_marker": round(stop.station.mile_marker, 1),
                        "gallons_purchased": round(stop.gallons_purchased, 2),
                        "cost": round(stop.cost, 2),
                    }
                    for stop in fuel_stops
                ],
                "total_fuel_cost": round(total_cost, 2),
                "total_gallons_consumed": round(route["distance_miles"] / MPG, 2),
                "stations_considered": len(stations_on_route),
            }
        )

    def _stations_along_route(self, geometry, total_distance):
        if not geometry:
            return []

        pts = np.array(geometry, dtype=np.float32)
        lat_ref = float(np.radians(pts[:, 0].mean()))
        cos_lat = float(np.cos(lat_ref))

        dlat = np.diff(pts[:, 0]) * 69.0
        dlon = np.diff(pts[:, 1]) * 69.0 * cos_lat
        seg_dist = np.sqrt(dlat**2 + dlon**2)
        cum_dist = np.concatenate([[0.0], np.cumsum(seg_dist)])

        lat_min, lat_max = float(pts[:, 0].min()) - 1.0, float(pts[:, 0].max()) + 1.0
        lon_min, lon_max = float(pts[:, 1].min()) - 1.0, float(pts[:, 1].max()) + 1.0
        candidates = list(
            FuelStation.objects.filter(
                latitude__gte=lat_min,
                latitude__lte=lat_max,
                longitude__gte=lon_min,
                longitude__lte=lon_max,
            )
        )
        if not candidates:
            return []

        cand_lat = np.array([s.latitude for s in candidates], dtype=np.float32)
        cand_lon = np.array([s.longitude for s in candidates], dtype=np.float32)

        CHUNK = 500
        stations = []
        for start in range(0, len(candidates), CHUNK):
            stop = start + CHUNK
            sub_lat = cand_lat[start:stop][:, None]
            sub_lon = cand_lon[start:stop][:, None]

            d_lat = (sub_lat - pts[None, :, 0]) * 69.0
            d_lon = (sub_lon - pts[None, :, 1]) * 69.0 * cos_lat
            dists = np.sqrt(d_lat**2 + d_lon**2)

            nearest_idx = dists.argmin(axis=1)
            nearest_dist = dists[np.arange(dists.shape[0]), nearest_idx]

            for j, cand in enumerate(candidates[start:stop]):
                if nearest_dist[j] > CORRIDOR_MILES:
                    continue
                stations.append(
                    StationOnRoute(
                        name=cand.name,
                        city=cand.city,
                        state=cand.state,
                        price_per_gallon=float(cand.retail_price),
                        mile_marker=float(cum_dist[nearest_idx[j]]),
                    )
                )

        seen = set()
        unique = []
        for s in stations:
            key = (s.name, round(s.mile_marker, 1))
            if key in seen:
                continue
            seen.add(key)
            unique.append(s)
        return unique
