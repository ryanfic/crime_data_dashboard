import json

with open('web_dashboard/public/data/blocks.json', 'r') as f:
    blocks = json.load(f)['features']

with open('web_dashboard/public/data/properties.json', 'r') as f:
    properties = json.load(f)['features']

block_2352 = next(b for b in blocks if b['properties']['block_id'] == 2352)
print("Block 2352 geom:")
print(block_2352['geometry']['coordinates'][0][:3])

# properties in block 2352
props = [p['properties'] for p in properties if p['properties'].get('block_id') == 2352]
print(f"Properties in 2352: {len(props)}")
for p in props:
    print(p)
