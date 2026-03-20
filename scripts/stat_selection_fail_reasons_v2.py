import json
from collections import Counter, defaultdict
import os

# Path to the daily-selection output JSON file
json_path = os.path.join(
    'artifacts', 'tw_quant', 'daily_selection', '2026-03-09', 'pullback_trend_120d_optimized.json'
)

with open(json_path, 'r', encoding='utf-8') as f:
    data = json.load(f)

reason_counter = defaultdict(Counter)

for signal in data.get('signals', []):
    module_debug = signal.get('module_debug', {})
    for module, debug in module_debug.items():
        passed = debug.get('passed')
        reason = debug.get('reason')
        if passed is False:
            # Use string 'null' if reason is None
            reason_str = str(reason) if reason is not None else 'null'
            reason_counter[module][reason_str] += 1

# Print results
for module, counter in reason_counter.items():
    print(f'Module: {module}')
    for reason, count in counter.most_common():
        print(f'  {reason}: {count}')
    print()
