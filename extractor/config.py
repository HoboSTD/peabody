"""Sites, tags, paths and settings (README: What's collected; Settings)."""
import os
from pathlib import Path

REPO = Path(__file__).resolve().parent.parent
DB_PATH = REPO / "data" / "readings.db"
SESSION_PATH = REPO / "state" / "session.json"
SITES_CHECKED_PATH = REPO / "state" / "sites-checked"  # the Sydney date of the last site-list check
LOCK_PATH = REPO / "state" / "run.lock"  # one run at a time (README: Collecting)
BACKUP_DIR = REPO / "backups"
OUTPUT_DIR = REPO / "output"

LOCAL_TIMEZONE = "Australia/Sydney"  # backup dates, the daily site check, timestamp_local in the CSVs
# Off on GitHub, where the release keeps a monthly copy instead (README: Running on GitHub)
LOCAL_BACKUPS = os.environ.get("EXTRACTOR_LOCAL_BACKUPS", "on") != "off"
BACKUP_KEEP_DAYS = 7  # keep every backup this recent; older ones only the earliest of each month
BACKFILL_PAUSE = 5  # seconds between backfill requests (README: Being polite to the server)
STALE_HOURS = 12  # fetch warns if the newest reading is older than this (normally about 3 hours)

# Server (README: API reference)
BASE_URL = "https://peabody.ghost.site"
TRENDS_URL = BASE_URL + "/gHostModules/DataAccess/GetTrendValues"
MAP_URL = BASE_URL + "/gHostModules/Mapping/GetMappingData"
DATASERVER = "PEABODYAF"
TIMEZONE_ID = "Etc/UTC"  # we always send UTC times (README: GetTrendValues)
TIMEOUT = 60  # seconds
USER_AGENT = ("Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) "
              "Chrome/153.0.0.0 Safari/537.36")

# The map's request, copied from the page (README: Other endpoints). Used only to check the site list.
MAP_INPUT = {
    "mapLat": -34.187611, "mapLong": 150.99641, "mapZoom": 17, "mapType": "satellite", "hideControls": True,
    "hideDefaultMarkers": True, "preventDragging": True, "defaultSelectedSiteName": "Water Treatment Plant",
    "siteQueries": [{"GServer": "PEABODYAF", "Template": "MonitoringLocation", "Root": "Metropolitan Water Monitoring",
                     "Config": {"Latitude": "{{QueryResults}}|Latitude", "Longitude": "{{QueryResults}}|Longitude",
                                "StatusTag": "{{QueryResults}}|StatusColour", "Name": "{{QueryResults}}|Name",
                                "ValueTags": [], "ToggleOffClass": "StaticValue::monitoringLocation",
                                "ToggleOnId": "{{QueryResults}}|CSS Group ID"}}],
    "staticSites": [],
}

# The 18 series (README: What's collected). Tag name = ASSET_ROOT \ site | attribute.
ASSET_ROOT = "Metropolitan Water Monitoring"
WATER_QUALITY = {
    "ph": "pH",
    "specific_conductivity": "Specific Electrical Conductivity|Display",
    "temperature": "Temperature",
    "turbidity": "Turbidity|Display",
}
FLOW = {"flow_volume": "Instantaneous Volume Discharged"}
SITES = {
    "Upstream": WATER_QUALITY,
    "LDP7 Water Treatment Plant": {**WATER_QUALITY, **FLOW},
    "LDP8 Turkeys Nest": {**WATER_QUALITY, **FLOW},
    "Downstream": WATER_QUALITY,
}
# (site, parameter, attribute) for every series
SERIES = [(site, parameter, attribute) for site, parameters in SITES.items()
          for parameter, attribute in parameters.items()]
