def calculate_ma(data, period=5):
    closes = [d['close'] for d in data]
    return [sum(closes[i-period+1:i+1])/period if i >= period-1 else None for i in range(len(closes))]

def calculate_macd(data):
    closes = [d['close'] for d in data]
    ema12 = _ema(closes, 12)
    ema26 = _ema(closes, 26)
    macd_line = [e1 - e2 if e1 is not None and e2 is not None else None for e1, e2 in zip(ema12, ema26)]
    signal_line = _ema(macd_line, 9)
    return {'macd': macd_line, 'signal': signal_line}

def calculate_rsi(data, period=14):
    closes = [d['close'] for d in data]
    gains = [max(closes[i] - closes[i-1], 0) for i in range(1, len(closes))]
    losses = [max(closes[i-1] - closes[i], 0) for i in range(1, len(closes))]
    avg_gain = [sum(gains[max(0,i-period+1):i+1])/period if i >= period-1 else None for i in range(len(gains))]
    avg_loss = [sum(losses[max(0,i-period+1):i+1])/period if i >= period-1 else None for i in range(len(losses))]
    rs = [g/l if l and l > 0 else 100 for g, l in zip(avg_gain, avg_loss)]
    rsi = [100 - 100/(1+r) if r is not None else None for r in rs]
    return [None] + rsi

def _ema(values, period):
    ema = []
    k = 2/(period+1)
    for i, v in enumerate(values):
        if i == 0:
            ema.append(v)
        elif ema[-1] is not None and v is not None:
            ema.append(v*k + ema[-1]*(1-k))
        else:
            ema.append(None)
    return ema
