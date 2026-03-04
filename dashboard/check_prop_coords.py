import json

with open('web_dashboard/public/data/properties.json', 'r') as f:
    properties = json.load(f)['features']

p = next((x for x in properties if x['properties'].get('PID') == '028-787-056'), None)
if p:
    print(p['geometry']['coordinates'])

