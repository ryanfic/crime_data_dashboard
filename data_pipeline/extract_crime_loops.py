import json
import numpy as np
import pandas as pd
from ripser import ripser
from sklearn.preprocessing import StandardScaler
from shapely.geometry import Point, shape
from tqdm import tqdm
import math
import alphashape
from collections import defaultdict, Counter
from shapely.geometry import MultiPolygon, Polygon, MultiPoint
from pyproj import Geod

geod = Geod(ellps="WGS84")

# Monkey-patch alphashape 1.3.1 for Shapely 2.0+ compatibility
import sys
import alphashape
if 'alphashape.optimizealpha' in sys.modules:
    oa_module = sys.modules['alphashape.optimizealpha']
else:
    import importlib
    oa_module = importlib.import_module('alphashape.optimizealpha')

original_testalpha = oa_module._testalpha

def patched_testalpha(points, alpha):
    try:
        from alphashape import alphashape as alphashape_func
    except ImportError:
        pass
    polygon = alphashape_func(points, alpha)
    if isinstance(polygon, Polygon):
        # Shapely 2.0 MultiPoint is not iterable, check if it has 'geoms'
        pts_iter = points.geoms if hasattr(points, 'geoms') else points
        # Ensure we check against Point objects
        pts_to_check = [p if isinstance(p, Point) else Point(p) for p in pts_iter]
        return all([polygon.contains(pt) or polygon.touches(pt) for pt in pts_to_check])
    return False

oa_module._testalpha = patched_testalpha

def compute_area(poly_coords):
    if not poly_coords or len(poly_coords) == 0:
        return 0
    try:
        ring_lons = [p[0] for p in poly_coords[0]]
        ring_lats = [p[1] for p in poly_coords[0]]
        if len(ring_lons) < 3: return 0
        area, perim = geod.geometry_area_perimeter(ring_lons, ring_lats)
        area = abs(area)
        for hole in poly_coords[1:]:
            h_lons = [p[0] for p in hole]
            h_lats = [p[1] for p in hole]
            if len(h_lons) < 3: continue
            ha, _ = geod.geometry_area_perimeter(h_lons, h_lats)
            area -= abs(ha)
        return area / 1e6
    except Exception:
        return 0

def extract_loops():
    print("Loading datasets...")
    # Load Crimes
    with open('dashboard/web_dashboard/public/data/crimes.json', 'r') as f:
        crimes_data = json.load(f)
        
    # Find all unique crime types
    unique_types = set([f['properties']['TYPE'] for f in crimes_data['features']])
    print(f"Found crime types: {unique_types}")

    # Load blocks to find block_id
    print("Loading blocks to link IDs...")
    with open('dashboard/web_dashboard/public/data/blocks.json', 'r') as f:
        blocks_data = json.load(f)
        
    blocks = []
    for f in blocks_data['features']:
        prop = f['properties']
        poly = shape(f['geometry'])
        center = poly.centroid
        blocks.append({
            'id': prop['block_id'],
            'x': center.x,
            'y': center.y
        })
    
    features = []
    
    for crime_type in unique_types:
        crime_points = []
        crime_neighborhoods = []
        for f in crimes_data['features']:
            if f['properties']['TYPE'] == crime_type:
                coords = f['geometry']['coordinates']
                crime_points.append([coords[0], coords[1]])
                crime_neighborhoods.append(f['properties'].get('NEIGHBOURHOOD', 'Unknown'))
                
        if len(crime_points) < 50:
            print(f"Skipping '{crime_type}' - not enough points ({len(crime_points)})")
            continue
            
        crime_coords = np.array(crime_points)
        print(f"Processing '{crime_type}' with {len(crime_coords)} points...")
        
        # Scale coordinates so Ripser treats X and Y equally
        scaler = StandardScaler()
        scaled_coords = scaler.fit_transform(crime_coords)
        
        res = ripser(scaled_coords, maxdim=1, do_cocycles=True)
        dgms = res['dgms']
        cocycles = res['cocycles'][1]
        
        h1_dgms = dgms[1]
        
        if len(h1_dgms) == 0:
            print(f"No loops found for '{crime_type}'.")
            continue
            
        persistence = h1_dgms[:, 1] - h1_dgms[:, 0]
        
        # Filter for significant loops (signal) - top 15 per crime type
        sorted_idxs = np.argsort(persistence)[::-1]
        top_idxs = sorted_idxs[:15]
        
        for rank, idx in enumerate(top_idxs):
            lifetime = float(persistence[idx])
            birth = float(h1_dgms[idx, 0])
            death = float(h1_dgms[idx, 1])
            cocycle = cocycles[idx]
            
            edges_indices = cocycle[:, :2].astype(int)
            unique_nodes = list(set(edges_indices.flatten()))
            
            # Mode 1: Simplex Graph
            multi_line_coords = []
            nodes_lon = []
            nodes_lat = []
            for e in edges_indices:
                p1 = crime_coords[e[0]].tolist()
                p2 = crime_coords[e[1]].tolist()
                multi_line_coords.append([p1, p2])
                nodes_lon.extend([p1[0], p2[0]])
                nodes_lat.extend([p1[1], p2[1]])
                
            loop_center_lon = np.mean(nodes_lon)
            loop_center_lat = np.mean(nodes_lat)
            
            min_dist = float('inf')
            closest_id = None
            for b in blocks:
                dist = math.hypot(b['x'] - loop_center_lon, b['y'] - loop_center_lat)
                if dist < min_dist:
                    min_dist = dist
                    closest_id = b['id']
                    
            loop_neighborhoods = [crime_neighborhoods[n] for n in unique_nodes]
            majority_hood = Counter(loop_neighborhoods).most_common(1)[0][0] if loop_neighborhoods else "Unknown"
            
            # Mode 3: Alpha Shape
            mode3_coords = None
            if len(unique_nodes) >= 4:
                # Convert coords to list of tuples for compatibility
                loop_points = [tuple(p) for p in crime_coords[unique_nodes]]
                try:
                    alpha = alphashape.optimizealpha(loop_points, upper=100000.0)
                    alpha_poly = alphashape.alphashape(loop_points, alpha)
                    
                    # If it fragmented, loosen it down
                    while isinstance(alpha_poly, MultiPolygon) and alpha > 0:
                        alpha = max(0, alpha - 0.1)
                        if alpha == 0: break
                        alpha_poly = alphashape.alphashape(loop_points, alpha)
                    
                    if alpha <= 0 or isinstance(alpha_poly, MultiPolygon):
                        alpha_poly = MultiPoint(loop_points).convex_hull
                    
                    if isinstance(alpha_poly, Polygon):
                        rings = [list(alpha_poly.exterior.coords)]
                        for interior in alpha_poly.interiors:
                            rings.append(list(interior.coords))
                        mode3_coords = rings
                except Exception as e:
                    print(f"Mode 3 failed: {e}")
                    pass

            # Mode 2: Boundary Cycle
            mode2_coords = None
            try:
                adj = defaultdict(list)
                for u, v in edges_indices:
                    adj[u].append(v)
                    adj[v].append(u)
                if all(len(neighbors) == 2 for neighbors in adj.values()):
                    start_node = next(iter(adj.keys()))
                    curr = start_node
                    prev = None
                    cycle_nodes = []
                    while True:
                        cycle_nodes.append(curr)
                        neighbors = adj[curr]
                        next_node = neighbors[0] if neighbors[0] != prev else neighbors[1]
                        prev = curr
                        curr = next_node
                        if curr == start_node:
                            break
                    if len(cycle_nodes) == len(adj):
                        cycle_nodes.append(start_node)
                        mode2_coords = [[crime_coords[n].tolist() for n in cycle_nodes]]
            except Exception:
                pass
                
            # Fallbacks
            if not mode2_coords and mode3_coords:
                mode2_coords = mode3_coords
            if not mode3_coords and mode2_coords:
                mode3_coords = mode2_coords
                
            area_km2 = 0
            if mode2_coords:
                area_km2 = compute_area(mode2_coords)
            elif mode3_coords:
                area_km2 = compute_area(mode3_coords)
            
            # Base color mapping exactly as requested
            rank_color = "#8888ff" # bottom 5
            if rank < 5:
                rank_color = "#ff69b4" # top 5
            elif rank < 10:
                rank_color = "#ffaa44" # middle 5
            
            feature = {
                "type": "Feature",
                "geometry": {
                    "type": "MultiLineString",
                    "coordinates": multi_line_coords
                },
                "properties": {
                    "crime_type": crime_type,
                    "rank": rank + 1,
                    "rank_color": rank_color,
                    "persistence": round(lifetime, 3),
                    "birth": round(birth, 3),
                    "death": round(death, 3),
                    "closest_block": closest_id,
                    "neighbourhood": majority_hood,
                    "num_edges": len(multi_line_coords),
                    "mode1_coords": multi_line_coords,
                    "mode2_coords": mode2_coords,
                    "mode3_coords": mode3_coords,
                    "area_km2": round(area_km2, 3)
                }
            }
            features.append(feature)
            
    geojson = {
        "type": "FeatureCollection",
        "properties": {
            "total_loops": len(features)
        },
        "features": features
    }
    
    out_path = 'dashboard/web_dashboard/public/data/crime_loops.json'
    with open(out_path, 'w') as f:
        json.dump(geojson, f)
        
    print(f"Successfully exported {len(features)} H1 loops to {out_path}!")

if __name__ == "__main__":
    extract_loops()
