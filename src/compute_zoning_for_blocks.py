import json
import os
import collections

# Load the logic from vancouver_block_profile.py
def classify_zone(district: str) -> str:
    if not district:
        return "other"
    d = str(district).strip().upper()
    if d.startswith("RS") or d.startswith("R1"): return "single_family"
    if d.startswith("R3") or d.startswith("R4") or d.startswith("R5"): return "multifamily"
    if d.startswith("RT"): return "two_family"
    if d.startswith("RM") or d.startswith("FM"): return "multifamily"
    MIXED_USE_PREFIXES = ("C-2", "C-3", "C-5", "C-6", "FC-")
    if any(d.startswith(p) for p in MIXED_USE_PREFIXES): return "mixed_use"
    if d.startswith("MC"): return "mixed_use"
    if d == "C-1" or d.startswith("C-1 "): return "commercial_only"
    if d.startswith("C-7") or d.startswith("C-8"): return "shopping_centre"
    if (d.startswith("M-") or d.startswith("M1") or d.startswith("M2")
            or d.startswith("I-") or d.startswith("IC-")): return "industrial"
    if d.startswith("HA"): return "historic_area"
    if d in ("DD", "CWD", "DEOD", "FCCDD"): return "downtown"
    if d.startswith("CD") or d == "CD-1": return "cd_unknown"
    if d.startswith("RA"): return "other"
    return "other"

CATEGORIES = [
    "single_family", "two_family", "multifamily", "mixed_use", 
    "commercial_only", "shopping_centre", "industrial", 
    "historic_area", "downtown", "cd_unknown", "other"
]

def main():
    base_dir = os.path.dirname(os.path.abspath(__file__))
    data_dir = os.path.join(base_dir, '..', 'dashboard', 'web_dashboard', 'public', 'data')
    
    # 1. Load properties to get zoning
    props_path = os.path.join(data_dir, 'properties.json')
    with open(props_path, 'r') as f:
        props_data = json.load(f)
        
    block_zone_counts = collections.defaultdict(lambda: collections.defaultdict(int))
    block_prop_counts = collections.defaultdict(int)
    
    for feat in props_data['features']:
        p = feat['properties']
        bid = p.get('block_id')
        if bid is None: continue
        
        district = p.get('ZONING_DISTRICT')
        z_class = classify_zone(district)
        
        block_zone_counts[bid][z_class] += 1
        block_prop_counts[bid] += 1

    # 2. Update blocks.json with precise percentages
    blocks_path = os.path.join(data_dir, 'blocks.json')
    with open(blocks_path, 'r') as f:
        blocks_data = json.load(f)

    for feat in blocks_data['features']:
        bid = feat['properties'].get('block_id')
        total = block_prop_counts.get(bid, 0)
        
        zoning_pcts = {}
        if total > 0:
            counts = block_zone_counts[bid]
            for cat in CATEGORIES:
                zoning_pcts[cat] = (counts.get(cat, 0) / total) * 100.0
                
            # Redistribute cd_unknown
            pct_cd = zoning_pcts["cd_unknown"]
            known = 100.0 - pct_cd
            
            if known > 0:
                scale = 100.0 / known
                for cat in CATEGORIES:
                    if cat != "cd_unknown":
                        zoning_pcts[cat] = round(zoning_pcts[cat] * scale, 1)
            else:
                # Edge case: Block is 100% CD-1, shove into 'other' to maintain exactly 10 dimensions safely
                for cat in CATEGORIES:
                    zoning_pcts[cat] = 0.0
                zoning_pcts["other"] = 100.0
                
            # Drop cd_unknown yielding exactly 10 dimensions
            del zoning_pcts["cd_unknown"]
                
        feat['properties']['zoning_percentages'] = zoning_pcts

    with open(blocks_path, 'w') as f:
        json.dump(blocks_data, f)

    print(f"Computed accurately redistributed categorical zoning (10 dims) for {len(blocks_data['features'])} blocks!")

if __name__ == '__main__':
    main()
