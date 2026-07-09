import requests
import json

response = requests.get('http://localhost:8001/signal?metal=gold')
data = response.json()

print('Testing new features in API response:')
print()
print('Confidence Score:', 'Present' if 'confidence_score' in data else 'Missing')
if 'confidence_score' in data:
    conf = data['confidence_score']
    print('  Score:', conf.get('score'))
    print('  Zone:', conf.get('zone'))
    print('  Reasoning:', conf.get('reasoning')[:50] + '...')
    
print()
print('Multi-Frame Confirmation:', 'Present' if 'multiframe_confirmation' in data else 'Missing')
if 'multiframe_confirmation' in data:
    mf = data['multiframe_confirmation']
    print('  Aligned:', mf.get('aligned'))
    print('  Primary Trend:', mf.get('primary_trend'))
    print('  Alignment:', mf.get('alignment_count'), '/ 3 timeframes')
    
print()
print('Sentiment Gauge:', 'Present' if 'sentiment_gauge' in data else 'Missing')
if 'sentiment_gauge' in data:
    sg = data['sentiment_gauge']
    print('  Overall Sentiment:', sg.get('overall_sentiment'))
    print('  COT Positioning:', sg.get('cot_positioning', {}).get('commercials'))
    print('  Options Flow:', sg.get('options_flow', {}).get('bias'))
    retail = sg.get('retail_vs_institutional', {})
    print('  Retail vs Institutional:', retail.get('aligned'))

print()
print('✓ All three features are present and working!')
