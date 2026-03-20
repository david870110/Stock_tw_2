import json
from collections import Counter, defaultdict

# 輸入檔案路徑
INPUT_PATH = r"c:/Users/JIANG/Desktop/AutoPrograming/artifacts/tw_quant/daily_selection/2026-03-10/pullback_trend_120d_optimized.json"

# 讀取 JSON
with open(INPUT_PATH, encoding="utf-8") as f:
    data = json.load(f)

fail_counter = Counter()
module_counter = defaultdict(Counter)

for sig in data["signals"]:
    # 取得主因
    reason = None
    if "failure_reason" in sig.get("metadata", {}):
        reason = sig["metadata"]["failure_reason"]
    # 解析 module:reason
    if reason and ":" in reason:
        module, detail = reason.split(":", 1)
        fail_counter[module] += 1
        module_counter[module][detail] += 1
    elif reason:
        fail_counter[reason] += 1
        module_counter[reason][reason] += 1

print("各篩選模組被刷掉的股票數量：")
for module, count in fail_counter.most_common():
    print(f"{module}: {count}")
    for detail, dcount in module_counter[module].most_common():
        print(f"  - {detail}: {dcount}")
