# fvg_trading_dashboard.py (Streamlit Cloud용)

import streamlit as st
import pandas as pd
import ccxt
import time
from datetime import datetime

# Streamlit 페이지 설정
st.set_page_config(layout="wide")
st.title("FVG 실시간 바이낸스 선물 트레이딩 대시보드")

# Streamlit Cloud용 Binance API 키 로딩
api_key = st.secrets["BINANCE_API_KEY"]
secret_key = st.secrets["BINANCE_SECRET_KEY"]

# 바이낸스 연결
exchange = ccxt.binance({
    'apiKey': api_key,
    'secret': secret_key,
    'enableRateLimit': True,
    'options': {'defaultType': 'future'}
})

# 포지션 클래스 정의
class Position:
    def __init__(self, symbol, entry_price):
        self.symbol = symbol
        self.avg_price = entry_price
        self.quantity = 1
        self.level = 1
        self.status = 'open'
        self.entry_log = [(1, entry_price)]
        self.history = []

    def try_dca(self, current_price):
        if self.level == 1 and current_price <= self.avg_price * 0.97:
            self.entry_log.append((1, current_price))
            self._update_avg_price()
            self.level = 2
        elif self.level == 2 and current_price <= self.avg_price * 0.94:
            self.entry_log.append((2, current_price))
            self._update_avg_price()
            self.level = 3

    def _update_avg_price(self):
        total_qty = sum(qty for qty, _ in self.entry_log)
        total_cost = sum(qty * price for qty, price in self.entry_log)
        self.quantity = total_qty
        self.avg_price = total_cost / total_qty

    def should_take_profit(self, current_price):
        return current_price >= self.avg_price * 1.003

    def try_exit(self, current_price, timestamp):
        if self.should_take_profit(current_price):
            profit = (current_price - self.avg_price) * self.quantity
            self.status = 'closed'
            self.history.append({
                'symbol': self.symbol,
                'avg_entry': round(self.avg_price, 4),
                'exit_price': round(current_price, 4),
                'profit': round(profit, 4),
                'quantity': self.quantity,
                'exit_time': timestamp
            })
            return True
        return False

# 거래량 기준 상위 페어 불러오기
@st.cache_data(ttl=300)
def get_top_volume_symbols(limit=10):
    tickers = exchange.fetch_tickers()
    usdt_pairs = [(s, t['quoteVolume']) for s, t in tickers.items() if s.endswith('/USDT') and '/BUSD' not in s]
    top = sorted(usdt_pairs, key=lambda x: x[1], reverse=True)[:limit]
    return [s for s, _ in top]

# OHLCV 수집
def fetch_ohlcv(symbol):
    bars = exchange.fetch_ohlcv(symbol, timeframe='15m', limit=100)
    df = pd.DataFrame(bars, columns=['timestamp','open','high','low','close','volume'])
    df['timestamp'] = pd.to_datetime(df['timestamp'], unit='ms')
    return df

# FVG 탐지
def detect_fvg(df):
    fvg = []
    for i in range(2, len(df)):
        A, C = df.iloc[i-2], df.iloc[i]
        if A['high'] < C['low']:
            fvg.append(('bullish', A['high'], C['low'], df.iloc[i]['timestamp']))
        elif A['low'] > C['high']:
            fvg.append(('bearish', C['high'], A['low'], df.iloc[i]['timestamp']))
    return fvg

# 전략 실행
def simulate_strategy(symbol):
    df = fetch_ohlcv(symbol)
    fvg_list = detect_fvg(df)
    if not fvg_list:
        return None, None
    fvg = fvg_list[-1]
    entry_price = df.iloc[-1]['close']
    pos = Position(symbol, entry_price)
    log = []
    for _, row in df.iterrows():
        price = row['close']
        pos.try_dca(price)
        if pos.try_exit(price, row['timestamp']):
            log.extend(pos.history)
            break
    return pos, pd.DataFrame(log)

# Streamlit UI 구성
symbols = get_top_volume_symbols(limit=10)
st.sidebar.header("거래 페어 선택")
selected = st.sidebar.multiselect("감시할 페어를 선택하세요", symbols, default=symbols[:5])

summary_logs = []
cols = st.columns(len(selected))
for idx, sym in enumerate(selected):
    with cols[idx]:
        pos, log = simulate_strategy(sym)
        if pos:
            st.metric(f"{sym}", f"{pos.status.upper()} @ {round(pos.avg_price,2)}", delta=f"Level {pos.level}")
            if log is not None and not log.empty:
                summary_logs.append(log)

if summary_logs:
    st.subheader("전략 결과")
    combined = pd.concat(summary_logs, ignore_index=True)
    st.dataframe(combined)
    st.line_chart(combined.set_index('exit_time')['profit'].cumsum(), use_container_width=True)
else:
    st.info("전략 진입 조건을 만족한 페어가 없습니다.")
