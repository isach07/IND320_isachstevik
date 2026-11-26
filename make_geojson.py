# Converts the part 3 shapefiles to the GeoJSON files the Map page uses (Data/geojson).
# Run once from the project folder: uv run python make_geojson.py
import geopandas as gpd
from pathlib import Path

GEO_DIR = Path("Data/geojson")
GEO_DIR.mkdir(exist_ok=True)

# the shapefiles from part 3, with the same area labels as Magasinstatistikk
price = gpd.read_file(Path(__file__).parent / "Data/Budområder/Budområder.shp")
price["area"] = price["budomr"].str.replace("NO", "EL")
regions = gpd.read_file(Path(__file__).parent / "Data/NVE_Region/NVE_Region.shp", encoding="utf-8")
REGION_TO_VASS = {"RS": "VASS 1", "RØ": "VASS 1", "RV": "VASS 2", "RM": "VASS 3", "RN": "VASS 3"}
regions["area"] = regions["REGION"].map(REGION_TO_VASS)

# one file per area type in Magasinstatistikk: NO (all of Norway), EL (price areas) and VASS (water areas)
layers = {
    "norway": price.dissolve().assign(area="NO 0")[["area", "geometry"]],
    "price_areas": price[["area", "geometry"]],
    "water_areas": regions.dissolve("area").reset_index()[["area", "geometry"]],
}
for name, layer in layers.items():
    # Simplified to 500 m while still in metres (EPSG:25833): a map of the whole country does not
    # need more detail, and the files get much smaller. GeoJSON uses longitude/latitude (EPSG:4326).
    layer = layer.assign(geometry=layer.simplify(500)).to_crs(4326)
    path = GEO_DIR / f"{name}.geojson"
    layer.to_file(path, driver="GeoJSON")
    print(f"{path.name:20} {', '.join(layer['area']):30} {path.stat().st_size / 1000:6.0f} kB")
