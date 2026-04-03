import sys, os
sys.path.insert(0, os.path.join(os.getcwd(), 'src'))
from ph_server import PHRequest, optimize_weights, load_data

load_data()
req = PHRequest(
    crime_types=['Break and Enter Residential/Other', 'Break and Enter Commercial'],
    epsilon1_m=200.0
)

res = optimize_weights(req)

print(f"{'Alpha':<5} | {'Beta':<5} | {'Gamma':<5} | {'Bound Seg':<10} | {'Int Seg':<8} | {'Bound Crime':<12} | {'Int Crime':<10} | {'R Ratio':<8}")
for r in res:
    if (r['alpha'] == 0.33 and r['beta'] == 0.33 and r['gamma'] == 0.34) or \
       (r['alpha'] == 1.0 and r['beta'] == 0.0) or \
       (r['alpha'] == 0.0 and r['beta'] == 1.0) or \
       (r['alpha'] == 0.0 and r['beta'] == 0.0 and r['gamma'] == 1.0) or \
       (abs(r['alpha']-0.333) < 0.01 and abs(r['beta']-0.333) < 0.01):
        
        print(f"{r['alpha']:<5.2f} | {r['beta']:<5.2f} | {r['gamma']:<5.2f} | {r['boundary_blocks']:<10} | {r['interior_blocks']:<8} | {r['raw_boundary_crimes']:<12.0f} | {r['raw_interior_crimes']:<10.0f} | {r['normalized_ratio']:<8.4f}")
