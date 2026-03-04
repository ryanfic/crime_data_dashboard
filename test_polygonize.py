import pandas as pd
from shapely.geometry import LineString
from shapely.ops import polygonize
import ast

junctions_df = pd.read_csv('street_networks/data/junctions.csv')
junction_coords = {row['id']: [row['longitude'], row['latitude']] for _, row in junctions_df.iterrows()}

lines = []
seen_edges = set()

for _, row in junctions_df.iterrows():
    n1 = row['id']
    try:
        neighbors_list = eval(row['neighbors'])
        for neighbor_info in neighbors_list:
            if isinstance(neighbor_info, (list, tuple)):
                n2 = neighbor_info[0]
            else:
                n2 = neighbor_info
                
            if n2 in junction_coords:
                # avoid back and forth line duplicates
                edge = tuple(sorted([n1, n2]))
                if edge not in seen_edges:
                    seen_edges.add(edge)
                    p1 = junction_coords[n1]
                    p2 = junction_coords[n2]
                    lines.append(LineString([p1, p2]))
    except Exception as e:
        pass

print(f"Created {len(lines)} street segment lines.")
polygons = list(polygonize(lines))
print(f"Polygonize found {len(polygons)} city blocks!")

# calculate area distribution
areas = [p.area for p in polygons]
if areas:
    print(f"Max Area: {max(areas)}, Min Area: {min(areas)}")
    valid_blocks = [p for p in polygons if p.area < 0.001]
    print(f"Valid sized blocks (<0.001 deg^2): {len(valid_blocks)}")

