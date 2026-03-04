import json

with open('web_dashboard/public/data/blocks.json', 'r') as f:
    blocks = json.load(f)['features']
    
with open('web_dashboard/public/data/properties.json', 'r') as f:
    properties = json.load(f)['features']

# Find block that might be in the screenshot
# Map bounds: Main, Powell, Gore.
# Find blocks with high avg_value. Look at the top ones and see their properties.
max_val = max([b['properties']['avg_value'] for b in blocks if b['properties']['avg_value'] is not None])
print(f"Max block avg_value is: {max_val}")

for b in blocks:
    if b['properties']['avg_value'] and b['properties']['avg_value'] > 3000000:
        block_id = b['properties']['block_id']
        props_in_block = [p['properties'] for p in properties if p['properties'].get('block_id') == block_id]
        
        # Look for the block with street name matching Powell, Gore, or Main
        found_street = False
        for p in props_in_block:
            addr = f"{p.get('FROM_CIVIC_NUMBER')} {p.get('STREET_NAME')}"
            if "POWELL" in addr or "MAIN" in addr or "GORE" in addr or "ALEX" in addr:
                found_street = True
                
        if found_street:
            print(f"Block ID {block_id} has avg_val {b['properties']['avg_value']}")
            print(f"  Properties matched exactly to this block ID: {len(props_in_block)}")
            for p in props_in_block:
                print(f"    - Address: {p.get('FROM_CIVIC_NUMBER')} {p.get('STREET_NAME')}, Value: {p.get('property_value')}")
