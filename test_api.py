import requests
import json

r = requests.get('http://localhost:8001/signal?metal=gold')
d = r.json()

# List all keys received
print('Response keys received:')
for k in sorted(d.keys()):
    print(f'  - {k}')

print()
print('Check for new fields:')
print(f'  confluence: {"confluence" in d}')
print(f'  momentum: {"momentum" in d}')
print(f'  divergences: {"divergences" in d}')
print(f'  market_session: {"market_session" in d}')
print(f'  economic_events: {"economic_events" in d}')
print(f'  risk_reward: {"risk_reward" in d}')
print(f'  signal_strength: {"signal_strength" in d}')

print()
print('Sample confluence data:', json.dumps(d.get('confluence'), indent=2)[:300])
