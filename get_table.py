import sys
import os
sys.path.insert(0, os.path.join(os.getcwd(), 'src'))
from ph_server import PHRequest, compute_ph, load_data

load_data()

configs = {
    "Equal": (0.333, 0.333, 0.334),
    "Value Only": (1.0, 0.0, 0.0),
    "Age Only": (0.0, 1.0, 0.0),
    "Zone Only": (0.0, 0.0, 1.0)
}

print(f"{'Config':<15} | {'eps2':<8} | {'Bound Seg':<10} | {'Int Seg':<8} | {'Bound Crime':<12} | {'Int Crime':<10} | {'R Ratio':<8}")
print("-" * 85)

for name, (a, b, g) in configs.items():
    # crime_types for B&E by default
    crime_types = ['Break and Enter Residential/Other', 'Break and Enter Commercial']
    req = PHRequest(
        crime_types=crime_types,
        epsilon1_m=200.0, # The dashboard default is 200m
        alpha=a,
        beta=b,
        gamma=g
    )
    
    res = compute_ph(req)
    
    adj = res['adjacency']
    stats = adj['stats']
    
    eps2 = stats['auto_epsilon2']
    tot_boundary_seg = stats['boundary_edges']
    tot_interior_seg = stats['interior_edges']
    
    # Calculate boundary crimes and interior crimes
    boundary_crimes = sum(e['crime_count'] for e in adj['boundary_edges'])
    interior_crimes = sum(e['crime_count'] for e in adj['interior_edges'])
    
    norm_bound = boundary_crimes / tot_boundary_seg if tot_boundary_seg > 0 else 0
    norm_inter = interior_crimes / tot_interior_seg if tot_interior_seg > 0 else 0
    ratio = norm_bound / norm_inter if norm_inter > 0 else 0
    
    print(f"{name:<15} | {eps2:<8.6f} | {tot_boundary_seg:<10} | {tot_interior_seg:<8} | {boundary_crimes:<12} | {interior_crimes:<10} | {ratio:<8.4f}")
