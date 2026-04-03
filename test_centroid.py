import json
from shapely.geometry import shape

data = json.load(open("dashboard/web_dashboard/public/data/blocks.json"))
feat = data['features'][100]
geom = shape(feat['geometry'])
c = geom.centroid

minx, miny, maxx, maxy = geom.bounds
bx = (minx+maxx)/2
by = (miny+maxy)/2

print(f"Block: {feat['properties'].get('block_id')}")
print(f"Centroid (center of mass): ({c.x:.6f}, {c.y:.6f})")
print(f"Bounding Box Center:       ({bx:.6f}, {by:.6f})")
print(f"Difference: dx={c.x-bx:.6f}, dy={c.y-by:.6f}")
