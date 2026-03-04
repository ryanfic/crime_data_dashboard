import json

with open('web_dashboard/public/data/blocks.json', 'r') as f:
    blocks = json.load(f)['features']
    
red_blocks = []
for b in blocks:
    props = b['properties']
    # Dark red would be near the max. The dynamic limit max is around $50M probably if there's a huge outlier, or maybe 3.5M.
    # Let's just find blocks with high avg_value and small property_count
    if props['avg_value'] is not None and props['avg_value'] > 3000000:
        red_blocks.append(props)

print(f"Found {len(red_blocks)} blocks with avg_value > 3M")
for b in sorted(red_blocks, key=lambda x: x['avg_value'], reverse=True)[:5]:
    print(b)
