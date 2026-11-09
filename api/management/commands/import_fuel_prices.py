from collections import Counter, defaultdict
from difflib import SequenceMatcher

import geonamescache
import pandas as pd
from django.core.management.base import BaseCommand

from api.models import FuelStation


US_STATES = {
    "AL": "Alabama", "AK": "Alaska", "AZ": "Arizona", "AR": "Arkansas",
    "CA": "California", "CO": "Colorado", "CT": "Connecticut", "DE": "Delaware",
    "FL": "Florida", "GA": "Georgia", "HI": "Hawaii", "ID": "Idaho",
    "IL": "Illinois", "IN": "Indiana", "IA": "Iowa", "KS": "Kansas",
    "KY": "Kentucky", "LA": "Louisiana", "ME": "Maine", "MD": "Maryland",
    "MA": "Massachusetts", "MI": "Michigan", "MN": "Minnesota", "MS": "Mississippi",
    "MO": "Missouri", "MT": "Montana", "NE": "Nebraska", "NV": "Nevada",
    "NH": "New Hampshire", "NJ": "New Jersey", "NM": "New Mexico", "NY": "New York",
    "NC": "North Carolina", "ND": "North Dakota", "OH": "Ohio", "OK": "Oklahoma",
    "OR": "Oregon", "PA": "Pennsylvania", "RI": "Rhode Island", "SC": "South Carolina",
    "SD": "South Dakota", "TN": "Tennessee", "TX": "Texas", "UT": "Utah",
    "VT": "Vermont", "VA": "Virginia", "WA": "Washington", "WV": "West Virginia",
    "WI": "Wisconsin", "WY": "Wyoming",
}

STATE_CENTROIDS = {
    "AL": (32.806671, -86.791130), "AK": (61.370716, -152.404419),
    "AZ": (33.729759, -111.431221), "AR": (34.969704, -92.373123),
    "CA": (36.116203, -119.681564), "CO": (39.059811, -105.311104),
    "CT": (41.597782, -72.755371), "DE": (39.318523, -75.507141),
    "FL": (27.766279, -81.686783), "GA": (33.040619, -83.643074),
    "HI": (21.094318, -157.498337), "ID": (44.240459, -114.478828),
    "IL": (40.349457, -88.986137), "IN": (39.849426, -86.258278),
    "IA": (42.011539, -93.210526), "KS": (38.526600, -96.726486),
    "KY": (37.668140, -84.670067), "LA": (31.169546, -91.867805),
    "ME": (44.693947, -69.381927), "MD": (39.063946, -76.802101),
    "MA": (42.230171, -71.530106), "MI": (43.326618, -84.536095),
    "MN": (45.694454, -93.900192), "MS": (32.741646, -89.678696),
    "MO": (38.456085, -92.288368), "MT": (46.921925, -110.454353),
    "NE": (41.125370, -98.268082), "NV": (38.313515, -117.055374),
    "NH": (43.452492, -71.563896), "NJ": (40.298904, -74.521011),
    "NM": (34.840515, -106.248482), "NY": (42.165726, -74.948051),
    "NC": (35.630066, -79.806419), "ND": (47.528912, -99.784012),
    "OH": (40.388783, -82.764915), "OK": (35.565342, -96.928917),
    "OR": (44.572021, -122.070938), "PA": (40.590752, -77.209755),
    "RI": (41.680893, -71.511780), "SC": (33.856892, -80.945007),
    "SD": (44.299782, -99.438828), "TN": (35.747845, -86.692345),
    "TX": (31.054487, -97.563461), "UT": (40.150032, -111.862434),
    "VT": (44.045876, -72.710686), "VA": (37.769337, -78.169968),
    "WA": (47.400902, -121.490494), "WV": (38.491226, -80.954453),
    "WI": (44.268543, -89.616508), "WY": (42.755966, -107.302490),
}


def _normalize(s):
    """Lowercase, strip common prefix variants and punctuation."""
    s = s.lower().strip()
    replacements = {
        "st.": "saint", "st ": "saint ", "ste.": "sainte",
        "mt.": "mount", "mt ": "mount ",
        "ft.": "fort",  "ft ": "fort ",
    }
    for a, b in replacements.items():
        s = s.replace(a, b)
    for tok in (" city", " town", " village", " township", " (", ")"):
        s = s.replace(tok, "")
    return s.strip(" .,-")


class Command(BaseCommand):
    help = "Import fuel prices with local geocoding (exact + fuzzy + state fallback)"

    def add_arguments(self, parser):
        parser.add_argument("csv_path", type=str)

    def handle(self, *args, **options):
        self.stdout.write(f"Reading {options['csv_path']} ...")
        df = pd.read_csv(options["csv_path"], encoding="utf-8-sig")
        df.columns = [c.strip() for c in df.columns]
        self.stdout.write(f"  Raw rows: {len(df)}")

        df["State"] = df["State"].astype(str).str.strip().str.upper()
        df["City"] = df["City"].astype(str).str.strip()
        df["Address"] = df["Address"].astype(str).str.strip()
        df = df[df["State"].isin(US_STATES)]
        self.stdout.write(f"  After US filter: {len(df)}")

        df = df.sort_values("Retail Price")
        df = df.drop_duplicates(subset=["OPIS Truckstop ID"], keep="first")
        self.stdout.write(f"  After dedupe by OPIS ID: {len(df)}")

        # Build lookups from geonamescache
        gc = geonamescache.GeonamesCache()
        cities = gc.get_cities()

        # exact: (normalized_name, state) -> (lat, lon, pop)
        exact = {}
        # by_state: state -> [(normalized_name, lat, lon, pop), ...] for fuzzy search
        by_state = defaultdict(list)

        for c in cities.values():
            state = c.get("admin1code", "")
            if state not in US_STATES:
                continue
            name_norm = _normalize(c["name"])
            pop = c.get("population", 0)
            lat, lon = c["latitude"], c["longitude"]
            by_state[state].append((name_norm, lat, lon, pop))
            key = (name_norm, state)
            if key not in exact or pop > exact[key][2]:
                exact[key] = (lat, lon, pop)
        self.stdout.write(f"  Cities in geonamescache (US): {len(exact)} unique")

        # Resolve every unique (City, State)
        unique_pairs = Counter(zip(df["City"], df["State"]))
        coords = {}
        exact_hits = 0
        fuzzy_hits = 0
        fallbacks = 0

        for (city, state) in unique_pairs:
            name_norm = _normalize(city)
            key = (name_norm, state)
            if key in exact:
                lat, lon, _ = exact[key]
                coords[(city, state)] = (lat, lon)
                exact_hits += 1
                continue
            # Fuzzy: find best match within the same state
            best = None
            best_ratio = 0.0
            for other_norm, lat, lon, pop in by_state[state]:
                ratio = SequenceMatcher(None, name_norm, other_norm).ratio()
                # Boost ratio for larger populations, mildly
                adj = ratio + min(pop / 1_000_000, 0.05)
                if adj > best_ratio:
                    best_ratio = adj
                    best = (lat, lon)
            if best and best_ratio >= 0.80:
                coords[(city, state)] = best
                fuzzy_hits += 1
            else:
                coords[(city, state)] = STATE_CENTROIDS[state]
                fallbacks += 1

        self.stdout.write(
            f"  Resolved: exact={exact_hits}, fuzzy={fuzzy_hits}, "
            f"state_centroid_fallback={fallbacks}"
        )

        # Write
        created = 0
        for _, row in df.iterrows():
            lat, lon = coords[(row["City"], row["State"])]
            FuelStation.objects.update_or_create(
                opis_id=int(row["OPIS Truckstop ID"]),
                defaults={
                    "name": row["Truckstop Name"],
                    "address": row["Address"],
                    "city": row["City"],
                    "state": row["State"],
                    "retail_price": row["Retail Price"],
                    "latitude": lat,
                    "longitude": lon,
                },
            )
            created += 1

        self.stdout.write(self.style.SUCCESS(f"Done. {created} stations upserted."))
