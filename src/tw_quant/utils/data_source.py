def get_daily_data(stock, as_of_date, lookback=60):
    # 假設有資料庫或API，這裡用假資料模擬
    import random
    from datetime import datetime, timedelta
    data = []
    for i in range(lookback):
        d = as_of_date - timedelta(days=lookback-i)
        data.append({
            'date': d,
            'open': random.uniform(50, 150),
            'close': random.uniform(50, 150),
            'high': random.uniform(50, 150),
            'low': random.uniform(50, 150),
            'volume': random.randint(1000, 10000)
        })
    return data
