import requests
import json

response = requests.get('http://localhost:8001/signal?metal=gold')
data = response.json()

print("Keys in response:")
for key in sorted(data.keys()):
    print(f"  - {key}")

print("\n\nConfidence score data:")
conf = data.get('confidence_score')
if conf:
    print(json.dumps(conf, indent=2))
else:
    print("MISSING")

print("\n\nMultiframe confirmation data:")
mf = data.get('multiframe_confirmation')
if mf:
    print(json.dumps(mf, indent=2)[:300] + "...")
else:
    print("MISSING")

print("\n\nSentiment gauge data:")
sg = data.get('sentiment_gauge')
if sg:
    print(json.dumps(sg, indent=2)[:300] + "...")
else:
    print("MISSING")
