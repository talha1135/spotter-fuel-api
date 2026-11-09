# Spotter — Backend Django Engineer Assessment

A Django + DRF API that, given a start and finish location in the USA, returns route geometry, optimal fuel stops, and total fuel cost.

Vehicle spec: 500-mile max range, 10 mpg, starts with a full tank.

## Quick start

git clone <your-repo-url>
cd spotter-fuel-api
python3 -m venv venv
source venv/bin/activate
pip install -r requirements.txt
python manage.py migrate
python manage.py import_fuel_prices fuel-prices-for-be-assessment.csv
python manage.py runserver 8000

Then:

curl -X POST http://127.0.0.1:8000/api/route-fuel/ \
  -H "Content-Type: application/json" \
  -d '{"start": "Dallas, TX", "finish": "Denver, CO"}'

## Verified output (Dallas TX -> Denver CO)

- Distance: 795.23 miles
- Stations considered: 181
- Fuel stops: 2
  1. 7-ELEVEN — Wichita Falls, TX — mile 137.3 — $2.761/gal — 13.73 gal — $37.90
  2. QUIKTRIP #7914 — Amarillo, TX — mile 360.5 — $2.846/gal — 15.79 gal — $44.94
- Total fuel cost: $82.84
- Gallons consumed: 79.52 (50 from free initial tank + 29.52 purchased)

Short-route sanity check: LA -> Phoenix, 372.63 miles returns fuel_stops: [] and $0.00.

## Architecture

api/
  models.py                 FuelStation
  serializers.py            RouteRequestSerializer
  urls.py                   /api/route-fuel/
  views.py                  RouteFuelView - pipeline + corridor filter
  services/routing.py       One OSRM call -> geometry + distance
  services/fuel_optimizer.py  Greedy-with-lookahead fuel planner
  management/commands/import_fuel_prices.py  CSV -> DB with local geocoding

Pipeline per request:
1. Geocode start + finish via Nominatim (2 calls).
2. One OSRM call to router.project-osrm.org for the route.
3. Corridor-filter stations: DB bounding box -> numpy nearest-polyline-vertex -> keep within 40 miles -> project to mile marker.
4. Run the fuel optimizer.
5. Return JSON.

Total map/routing API calls per request: 1.

## Fuel optimization

Greedy with lookahead. At each stop (starting with a full tank):

- Look at every station within 500 miles.
- If a strictly cheaper station is reachable, buy just enough to reach the first such station.
- Otherwise fill up completely and drive to the cheapest reachable station.

Stop when finish is reachable on current fuel, buying only the missing amount.

Optimal for a fixed route with static prices.

## CSV cleaning

Input: 8,151 rows.

1. Drop non-US rows: 7,531 remain.
2. Dedupe by OPIS Truckstop ID, keep lowest price: 6,626 stations.
3. Strip whitespace from City, State, Address.
4. Geocode locally with geonamescache (bundled US city DB, no network):
   - 950 exact matches
   - 112 fuzzy matches
   - 2,751 small-town fallbacks to state centroid

The 40-mile corridor compensates for the fallback coordinates.

## Assumptions

- Vehicle starts with a full tank; only fuel bought during the trip counts.
- One-way trips only.
- Prices static.
- No per-station detour miles.

## What I'd change for production

- Real station coordinates via one-time geocoding pass (corridor back to 5 mi).
- PostGIS ST_DWithin on a route linestring.
- City-coordinate cache to drop to 1 API call per request.
- Self-hosted OSRM.
- Add detour distance to the cost model.

## Environment

Python 3.12, Django 6.1, DRF 3.18. Full pinned list: requirements.txt.