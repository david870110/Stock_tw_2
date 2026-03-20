from .basic_selection_contract import BasicSelectionContract
from ..utils.indicators import calculate_ma, calculate_macd, calculate_rsi
from ..utils.data_source import get_daily_data
from ..utils.volume import check_volume_increase
from ..utils.news import check_negative_news

class QizhangSelectionStrategy(BasicSelectionContract):
    """
    起漲選股策略：判斷均線突破、量能放大、MACD黃金交叉、RSI強勢區、利空排除。
    """
    def get_candidates(self, stock_list, as_of_date):
        candidates = []
        for stock in stock_list:
            data = get_daily_data(stock, as_of_date, lookback=60)
            if not data or len(data) < 20:
                continue
            ma_short = calculate_ma(data, period=5)
            ma_long = calculate_ma(data, period=20)
            macd = calculate_macd(data)
            rsi = calculate_rsi(data)
            volume_ok = check_volume_increase(data)
            negative_news = check_negative_news(stock, as_of_date)

            # 均線突破
            ma_break = ma_short[-1] > ma_long[-1] and ma_short[-2] <= ma_long[-2]
            # MACD黃金交叉
            macd_cross = macd['signal'][-1] > macd['macd'][-1] and macd['signal'][-2] <= macd['macd'][-2]
            # RSI強勢區
            rsi_strong = rsi[-1] > 60
            # 利空排除
            no_negative = not negative_news and data[-1]['close'] > data[-1]['low'] * 1.03

            if ma_break and volume_ok and macd_cross and rsi_strong and no_negative:
                candidates.append({
                    'stock': stock,
                    'date': as_of_date,
                    'reason': {
                        'ma_break': ma_break,
                        'volume_ok': volume_ok,
                        'macd_cross': macd_cross,
                        'rsi_strong': rsi_strong,
                        'no_negative': no_negative
                    },
                    'indicators': {
                        'ma_short': ma_short[-1],
                        'ma_long': ma_long[-1],
                        'macd': macd['macd'][-1],
                        'signal': macd['signal'][-1],
                        'rsi': rsi[-1],
                        'volume': data[-1]['volume']
                    }
                })
        return candidates
