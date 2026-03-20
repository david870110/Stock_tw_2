def check_volume_increase(data):
    if len(data) < 10:
        return False
    avg_vol = sum([d['volume'] for d in data[-10:-1]])/9
    return data[-1]['volume'] > avg_vol * 1.3
