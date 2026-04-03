import os
import json
import geopandas as gpd
import pandas as pd
from shapely.geometry import shape

print("Loading blocks.json...")
blocks_path = "dashboard/web_dashboard/public/data/blocks.json"
blocks_gdf = gpd.read_file(blocks_path)

print("Loading zoning_d.csv...")
zoning_csv_path = "Data /zoning_d.csv"
zoning_df = pd.read_csv(zoning_csv_path)

# Parse GeoJSON strings in the 'Geom' column to shapely geometries
print("Parsing zoning geometries...")
geometries = []
valid_indices = []
for idx, row in zoning_df.iterrows():
    try:
        geom = json.loads(row['Geom'])
        geometries.append(shape(geom))
        valid_indices.append(idx)
    except Exception as e:
        continue

zoning_gdf = gpd.GeoDataFrame(zoning_df.loc[valid_indices], geometry=geometries, crs="EPSG:4326")

# Use a projected CRS for accurate area calculations in meters (e.g., EPSG:32610 for Vancouver)
projected_crs = "EPSG:32610"
blocks_proj = blocks_gdf.to_crs(projected_crs)
zoning_proj = zoning_gdf.to_crs(projected_crs)

blocks_proj['block_area'] = blocks_proj.geometry.area

print("Calculating spatial intersections...")
# Perform intersection
intersections = gpd.overlay(blocks_proj, zoning_proj, how='intersection')
intersections['intersect_area'] = intersections.geometry.area

print("Aggregating zoning percentages...")
# Calculate percentage
# Group by block_id and Zoning Category
zoning_stats = intersections.groupby(['block_id', 'Zoning Category'])['intersect_area'].sum().reset_index()

# Merge total block area back to calculate percentages
area_map = blocks_proj.set_index('block_id')['block_area'].to_dict()
zoning_stats['block_area'] = zoning_stats['block_id'].map(area_map)
zoning_stats['percentage'] = (zoning_stats['intersect_area'] / zoning_stats['block_area']) * 100

# Build a dictionary for fast lookup: block_id -> { "Residential": 45.2, "Commercial": 54.8 }
zoning_dict = {}
for _, row in zoning_stats.iterrows():
    b_id = int(row['block_id'])
    cat = str(row['Zoning Category'])
    pct = float(row['percentage'])
    if b_id not in zoning_dict:
        zoning_dict[b_id] = {}
    if pct > 0.5:  # Only keep if > 0.5%
        zoning_dict[b_id][cat] = round(pct, 1)

print("Updating blocks.json...")
# Rewrite blocks.json with the new properties
with open(blocks_path, 'r') as f:
    blocks_data = json.load(f)

for feature in blocks_data['features']:
    props = feature['properties']
    b_id = props.get('block_id')
    if b_id in zoning_dict:
        props['zoning_percentages'] = zoning_dict[b_id]
    else:
        props['zoning_percentages'] = {}

with open(blocks_path, 'w') as f:
    json.dump(blocks_data, f)
    
print("Successfully appended zoning percentages to blocks.json!")
