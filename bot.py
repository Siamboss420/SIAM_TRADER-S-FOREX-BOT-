import asyncio
import random
import requests
import pandas as pd
from datetime import datetime, timedelta, timezone
from telegram import InlineKeyboardButton, InlineKeyboardMarkup, Update
from telegram.ext import (
    ApplicationBuilder,
    CallbackQueryHandler,
    CommandHandler,
    MessageHandler,
    filters,
    ContextTypes,
)
from telegram.request import HTTPXRequest
from telegram.error import TelegramError, RetryAfter

# টেলিগ্রাম বট টোকেন
TELEGRAM_BOT_TOKEN = '8817403825:AAE--3DW1JyBljPr1FQFnwsD5bEGUnSfBQs'

# সিক্রেট পাসওয়ার্ড
CORRECT_PASSWORD = 'SIAM MEGHLA'

# আপনার নতুন গ্রুপের চ্যাট আইডি
TARGET_GROUP_IDS = [-1004294815851]

# ব্লক প্রুফ ইউজার এজেন্ট লিস্ট
USER_AGENTS = [
    'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36',
    'Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/605.1.15 (KHTML, like Gecko) Version/17.2 Safari/605.1.15',
    'Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/119.0.0.0 Safari/537.36',
    'Mozilla/5.0 (Windows NT 10.0; Win64; x64; rv:121.0) Gecko/20100101 Firefox/121.0'
]

REAL_PAIRS = {
    'EUR/USD': {'ticker': 'EURUSD=X', 'alpha': 'EURUSD', 'flag': '🇪🇺🇺🇸'},
    'GBP/USD': {'ticker': 'GBPUSD=X', 'alpha': 'GBPUSD', 'flag': '🇬🇧🇺🇸'},
    'USD/JPY': {'ticker': 'USDJPY=X', 'alpha': 'USDJPY', 'flag': '🇺🇸🇯🇵'},
    'AUD/USD': {'ticker': 'AUDUSD=X', 'alpha': 'AUDUSD', 'flag': '🇦🇺🇺🇸'},
    'USD/CAD': {'ticker': 'USDCAD=X', 'alpha': 'USDCAD', 'flag': '🇺🇸🇨🇦'},
    'USD/CHF': {'ticker': 'USDCHF=X', 'alpha': 'USDCHF', 'flag': '🇺🇸🇨🇭'},
    'EUR/GBP': {'ticker': 'EURGBP=X', 'alpha': 'EURGBP', 'flag': '🇪🇺🇬🇧'},
    'EUR/JPY': {'ticker': 'EURJPY=X', 'alpha': 'EURJPY', 'flag': '🇪🇺🇯🇵'},
    'GBP/JPY': {'ticker': 'GBPJPY=X', 'alpha': 'GBPJPY', 'flag': '🇬🇧🇯🇵'},
    'AUD/JPY': {'ticker': 'AUDJPY=X', 'alpha': 'AUDJPY', 'flag': '🇦🇺🇯🇵'},
    'CAD/JPY': {'ticker': 'CADJPY=X', 'alpha': 'CADJPY', 'flag': '🇨🇦🇯🇵'},
    'EUR/AUD': {'ticker': 'EURAUD=X', 'alpha': 'EURAUD', 'flag': '🇪🇺🇦🇺'},
    'GBP/AUD': {'ticker': 'GBPAUD=X', 'alpha': 'GBPAUD', 'flag': '🇬🇧🇦🇺'},
}

user_selections = {}
authorized_users = set()
active_signals = []
auto_live_subscribers = set()

# কনকারেন্সি ও রেস কন্ডিশন এড়ানোর জন্য এসিনক্রোনাস লক
data_lock = asyncio.Lock()


def get_detailed_market_status():
    """বাংলাদেশ সময় (UTC +6) অনুযায়ী রিয়েল-টাইম ফরেক্স মার্কেট স্ট্যাটাস"""
    bd_now = datetime.now(timezone.utc) + timedelta(hours=6)
    weekday = bd_now.weekday()
    hour = bd_now.hour

    if weekday == 5 or weekday == 6:
        return "🔴 CLOSED (Weekend - Opens Monday 03:00 AM)"
    
    if weekday == 4 and hour >= 23:
        return "🔴 CLOSED (Weekend Mode Active)"

    current_time_formatted = bd_now.strftime('%I:%M %p (%d %b %Y)')
    return f"🟢 OPEN (Live) | Time: {current_time_formatted}"


# ==========================================
# অ্যান্টি-ব্লক ও অটো-রিসেন্ট রোটেশন সহ ডেটা ফেচিং সিস্টেম
# ==========================================
async def fetch_yahoo_data_safe(ticker, interval='1m', range_val='1d'):
    for attempt in range(2):
        try:
            url = f'https://query1.finance.yahoo.com/v8/finance/chart/{ticker}?interval={interval}&range={range_val}'
            headers = {'User-Agent': random.choice(USER_AGENTS)}
            response = await asyncio.to_thread(requests.get, url, headers=headers, timeout=4)
            if response.status_code == 200:
                data = response.json()
                result = data.get('chart', {}).get('result')
                if result:
                    quotes = result[0].get('indicators', {}).get('quote', [{}])[0]
                    opens = quotes.get('open', [])
                    highs = quotes.get('high', [])
                    lows = quotes.get('low', [])
                    closes = quotes.get('close', [])
                    if closes:
                        df = pd.DataFrame({'Open': opens, 'High': highs, 'Low': lows, 'Close': closes})
                        df.dropna(inplace=True)
                        if not df.empty and len(df) >= 15:
                            return df
            elif response.status_code == 429:
                await asyncio.sleep(1.5 * (attempt + 1))
                continue
        except Exception:
            await asyncio.sleep(0.5)
    return None


async def fetch_alpha_data_safe(symbol_pair):
    for attempt in range(2):
        try:
            from_curr = symbol_pair[:3]
            to_curr = symbol_pair[3:]
            url = f'https://www.alphavantage.co/query?function=FX_INTRADAY&from_symbol={from_curr}&to_symbol={to_curr}&interval=1min&apikey=demo'
            response = await asyncio.to_thread(requests.get, url, timeout=4)
            if response.status_code == 200:
                data = response.json()
                time_series = data.get('Time Series FX (1min)')
                if time_series:
                    df_list = []
                    for time_str, values in list(time_series.items())[:50]:
                        df_list.append({
                            'Open': float(values.get('1. open', 0)),
                            'High': float(values.get('2. high', 0)),
                            'Low': float(values.get('3. low', 0)),
                            'Close': float(values.get('4. close', 0))
                        })
                    if df_list:
                        df = pd.DataFrame(df_list)
                        df = df.iloc[::-1].reset_index(drop=True)
                        if len(df) >= 15:
                            return df
            elif response.status_code == 429:
                await asyncio.sleep(2.0)
                continue
        except Exception:
            await asyncio.sleep(0.5)
    return None


async def fetch_twelve_data_safe(symbol_pair):
    try:
        clean_sym = symbol_pair.replace('=X', '')
        url = f"https://api.twelvedata.com/time_series?symbol={clean_sym}&interval=1min&outputsize=15&apikey=demo"
        response = await asyncio.to_thread(requests.get, url, timeout=4)
        if response.status_code == 200:
            data = response.json()
            values = data.get('values')
            if values:
                df_list = []
                for v in values:
                    df_list.append({
                        'Open': float(v.get('open', 0)),
                        'High': float(v.get('high', 0)),
                        'Low': float(v.get('low', 0)),
                        'Close': float(v.get('close', 0))
                    })
                if df_list:
                    df = pd.DataFrame(df_list)
                    df = df.iloc[::-1].reset_index(drop=True)
                    if len(df) >= 10:
                        return df
    except Exception:
        pass
    return None


async def get_robust_market_data(ticker, alpha_symbol):
    """ব্লক-প্রুফ মাল্টি-এপিআই অটো-রিসেন্ট ও ফলব্যাক রোটেশন ম্যানেজার"""
    df = await fetch_yahoo_data_safe(ticker)
    if df is not None and len(df) >= 15:
        return df

    df = await fetch_alpha_data_safe(alpha_symbol)
    if df is not None and len(df) >= 15:
        return df

    df = await fetch_twelve_data_safe(alpha_symbol)
    if df is not None and len(df) >= 10:
        return df

    return None


# ==========================================
# ফিউচার সিগন্যাল ডুয়াল-ইঞ্জিন সিস্টেম
# ==========================================

async def analyze_future_engine1(ticker, alpha_symbol):
    try:
        df = await get_robust_market_data(ticker, alpha_symbol)
        if df is None or len(df) < 30:
            return None

        close = df['Close']
        high = df['High']
        low = df['Low']
        
        delta = close.diff()
        gain = (delta.where(delta > 0, 0)).rolling(window=14).mean()
        loss = (-delta.where(delta < 0, 0)).rolling(window=14).mean()
        loss = loss.replace(0, 0.0001)
        rs = gain / loss
        df['RSI'] = 100 - (100 / (1 + rs))
        
        df['SMA20'] = close.rolling(window=20).mean()
        df['EMA50'] = close.ewm(span=50, adjust=False).mean()

        if df['RSI'].isna().iloc[-1] or df['SMA20'].isna().iloc[-1]:
            return None

        current_rsi = float(df.iloc[-1]['RSI'])
        last_close = float(df.iloc[-1]['Close'])
        sma20 = float(df.iloc[-1]['SMA20'])
        ema50 = float(df.iloc[-1]['EMA50'])

        recent_high = float(high.iloc[-30:-2].max())
        recent_low = float(low.iloc[-30:-2].min())

        score_call = 0
        score_put = 0

        if last_close > ema50:
            score_call += 2
        else:
            score_put += 2

        if last_close >= recent_high * 0.9995:
            score_put += 2
        elif last_close <= recent_low * 1.0005:
            score_call += 2

        if current_rsi > 58:
            score_call += 1
        elif current_rsi < 42:
            score_put += 1

        if last_close > sma20:
            score_call += 1
        else:
            score_put += 1

        if score_call > score_put:
            return 'CALL'
        elif score_put > score_call:
            return 'PUT'
        return None
    except Exception:
        return None


async def analyze_future_engine2(alpha_symbol, ticker):
    try:
        df = await get_robust_market_data(ticker, alpha_symbol)
        if df is None or len(df) < 25:
            return None

        high = df['High']
        low = df['Low']
        close = df['Close']

        tr1 = high - low
        tr2 = (high - close.shift()).abs()
        tr3 = (low - close.shift()).abs()
        tr = pd.concat([tr1, tr2, tr3], axis=1).max(axis=1)
        atr = tr.rolling(window=14).mean()

        hl2 = (high + low) / 2
        multiplier = 2.5
        supertrend_upper = hl2 + (multiplier * atr)
        supertrend_lower = hl2 - (multiplier * atr)

        plus_dm = high.diff()
        minus_dm = low.diff()
        plus_dm = plus_dm.where((plus_dm > 0) & (plus_dm > minus_dm), 0.0)
        minus_dm = minus_dm.where((minus_dm > 0) & (minus_dm > plus_dm), 0.0)
        
        tr_smooth = atr
        plus_di = 100 * (plus_dm.rolling(window=14).mean() / tr_smooth.replace(0, 0.0001))
        minus_di = 100 * (minus_dm.rolling(window=14).mean() / tr_smooth.replace(0, 0.0001))
        dx = 100 * (plus_di - minus_di).abs() / (plus_di + minus_di).replace(0, 0.0001)
        adx = dx.rolling(window=14).mean()

        if adx.isna().iloc[-1]:
            return None

        current_adx = float(adx.iloc[-1])
        last_close = float(close.iloc[-1])
        sup_level = float(low.iloc[-20:-2].min())
        res_level = float(high.iloc[-20:-2].max())
        st_lower = float(supertrend_lower.iloc[-1])
        st_upper = float(supertrend_upper.iloc[-1])

        if current_adx < 22:
            return None

        if last_close > st_lower and last_close <= sup_level * 1.001:
            return 'CALL'
        elif last_close < st_upper and last_close >= res_level * 0.999:
            return 'PUT'

        return None
    except Exception:
        return None


async def analyze_future_market_combined(ticker, alpha_symbol):
    action1 = await analyze_future_engine1(ticker, alpha_symbol)
    if action1:
        return action1
    
    action2 = await analyze_future_engine2(alpha_symbol, ticker)
    if action2:
        return action2

    return None


# ==========================================
# লাইভ অটো ফিড ডুয়াল-ইঞ্জিন সিস্টেম
# ==========================================

async def analyze_live_feed_market_engine1(ticker, alpha_symbol):
    try:
        df = await get_robust_market_data(ticker, alpha_symbol)
        if df is None or len(df) < 20:
            return None

        close = df['Close']
        high = df['High']
        low = df['Low']

        sma20 = close.rolling(window=20).mean()
        std20 = close.rolling(window=20).std()
        df['Upper_Band'] = sma20 + (std20 * 2)
        df['Lower_Band'] = sma20 - (std20 * 2)

        low_min14 = low.rolling(window=14).min()
        high_max14 = high.rolling(window=14).max()
        denom = (high_max14 - low_min14).replace(0, 0.0001)
        df['%K'] = 100 * ((close - low_min14) / denom)
        df['%D'] = df['%K'].rolling(window=3).mean()

        if df['Upper_Band'].isna().iloc[-1] or df['%D'].isna().iloc[-1]:
            return None

        last_close = float(close.iloc[-1])
        last_upper = float(df.iloc[-1]['Upper_Band'])
        last_lower = float(df.iloc[-1]['Lower_Band'])
        stoch_k = float(df.iloc[-1]['%K'])
        stoch_d = float(df.iloc[-1]['%D'])

        candle_body = abs(float(close.iloc[-1]) - float(df.iloc[-1]['Open']))
        avg_body = abs(close - df['Open']).rolling(window=10).mean().iloc[-1]

        if candle_body < avg_body * 0.3:
            return None

        if last_close <= last_lower * 1.0002 and stoch_k < 25 and stoch_k > stoch_d:
            return 'CALL'
        elif last_close >= last_upper * 0.9998 and stoch_k > 75 and stoch_k < stoch_d:
            return 'PUT'

        return None
    except Exception:
        return None


async def analyze_live_feed_market_engine2(alpha_symbol, ticker):
    try:
        df = await get_robust_market_data(ticker, alpha_symbol)
        if df is None or len(df) < 15:
            return None

        open_p = df['Open']
        high_p = df['High']
        low_p = df['Low']
        close_p = df['Close']

        sup = float(low_p.iloc[-15:-2].min())
        res = float(high_p.iloc[-15:-2].max())

        cur_open = float(open_p.iloc[-1])
        cur_high = float(high_p.iloc[-1])
        cur_low = float(low_p.iloc[-1])
        cur_close = float(close_p.iloc[-1])

        prev_open = float(open_p.iloc[-2])
        prev_close = float(close_p.iloc[-2])

        body_size = abs(cur_close - cur_open)
        lower_wick = min(cur_open, cur_close) - cur_low
        upper_wick = cur_high - max(cur_open, cur_close)

        if cur_low <= sup * 1.0005 and lower_wick > body_size * 2 and cur_close > cur_open:
            return 'CALL'

        if cur_high >= res * 0.9995 and upper_wick > body_size * 2 and cur_close < cur_open:
            return 'PUT'

        return None
    except Exception:
        return None


async def start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    try:
        user_id = update.message.from_user.id
        if user_id in authorized_users:
            authorized_users.remove(user_id)

        welcome_text = """
👑 === SIAM TRADERS LUXURY FOREX AI === 👑
 
🔒 *SECURITY ACCESS REQUIRED* 🔒
━━━━━━━━━━━━━━━━━━━━━━━━━━
✨ Please enter the correct password to access the VIP Forex Signal Bot:
"""
        await update.message.reply_text(welcome_text, parse_mode='Markdown')
    except Exception as e:
        print(f'Start command error: {e}')


async def handle_message(update: Update, context: ContextTypes.DEFAULT_TYPE):
    try:
        if not update.message or not update.message.text:
            return
        user_id = update.message.from_user.id
        text = update.message.text.strip()

        try:
            await update.message.delete()
        except TelegramError:
            pass

        if user_id in authorized_users:
            return

        if text == CORRECT_PASSWORD:
            authorized_users.add(user_id)
            await update.message.reply_text(
                "✅ *Access Granted!* Welcome to SIAM TRADERS VIP System.",
                parse_mode='Markdown',
            )
            
            market_status = get_detailed_market_status()
            bd_now = datetime.now(timezone.utc) + timedelta(hours=6)
            time_str = bd_now.strftime('%I:%M %p (%d %b %Y)')
            
            online_popup_text = f"""
╔═════════════════════════════════╗
║     🟢 SIAM TRADERS ONLINE      ║
║       SESSION STARTED           ║
╚═════════════════════════════════╝
🇧🇩 TIME: `{time_str}`
🌐 MARKET STATUS: `{market_status}`
✨ *Status:* Bot is active & online.
🚀 *Engine:* Anti-Block Multi-API Ready!
╔═════════════════════════════╗
║ DEVELOPER & OWNER: SIAM TRADERS ║
╚═════════════════════════════╝
"""
            for group_id in TARGET_GROUP_IDS:
                try:
                    await context.bot.send_message(chat_id=group_id, text=online_popup_text, parse_mode='Markdown')
                except Exception:
                    pass

            await show_main_menu_new(update, context)
        else:
            await update.message.reply_text(
                "❌ *Incorrect Password!* Please try again or type /start.",
                parse_mode='Markdown',
            )
    except Exception as e:
        print(f'Message handler error: {e}')


async def show_main_menu(update: Update, context: ContextTypes.DEFAULT_TYPE):
    try:
        user_id = update.effective_user.id if update.effective_user else 0
        if user_id not in authorized_users:
            if update.callback_query:
                await update.callback_query.message.reply_text("🔒 Session locked! Please type /start to enter password again.", parse_mode='Markdown')
            return

        market_status = get_detailed_market_status()
        bd_now = datetime.now(timezone.utc) + timedelta(hours=6)
        time_str = bd_now.strftime('%I:%M %p')
        
        is_active = user_id in auto_live_subscribers
        status_text = "🟢 ACTIVE" if is_active else "⚪ OFF"
        toggle_label = "⚡ Live Auto Signal Feed: [ ON ]" if is_active else "⚡ Live Auto Signal Feed: [ OFF ]"

        keyboard = [
            [InlineKeyboardButton(toggle_label, callback_data='TOGGLE_AUTO')],
            [InlineKeyboardButton('🔒 Lock Bot', callback_data='LOCK_BOT')]
        ]
        row = []
        for pair_name, info in REAL_PAIRS.items():
            btn = InlineKeyboardButton(f"{info['flag']} {pair_name}", callback_data=f'PAIR_{pair_name}')
            row.append(btn)
            if len(row) == 2:
                keyboard.append(row)
                row = []
        if row:
            keyboard.append(row)

        reply_markup = InlineKeyboardMarkup(keyboard)
        
        menu_text = f"""
👑 === SIAM TRADERS LUXURY FOREX AI === 👑
 
🇧🇩 LOCATION: `Bangladesh (UTC +6:00)`
⏰ LOCAL TIME: `{time_str}`
🌐 MARKET: `{market_status}`
🚀 FUTURE DUAL-ENGINE: `EMA/RSI + SuperTrend/ADX`
⚡ LIVE DUAL-ENGINE: `Bollinger/Stoch + S/R Patterns`
⚡ *Live Auto Feed Status:* `{status_text}`
━━━━━━━━━━━━━━━━━━━━━━━━━━
╔═════════════════════════════╗
║ DEVELOPER & OWNER: SIAM TRADERS ║
╚═════════════════════════════╝
━━━━━━━━━━━━━━━━━━━━━━━━━━
✨ *Select Forex Pair or Start Live Auto Signals below:* 👇
"""
        if update.message:
            await update.message.reply_text(menu_text, reply_markup=reply_markup)
        elif update.callback_query:
            await update.callback_query.message.reply_text(menu_text, reply_markup=reply_markup)
    except Exception as e:
        print(f'Show menu error: {e}')


async def show_main_menu_new(update: Update, context: ContextTypes.DEFAULT_TYPE):
    try:
        user_id = update.effective_user.id if update.effective_user else 0
        if user_id not in authorized_users:
            return

        market_status = get_detailed_market_status()
        bd_now = datetime.now(timezone.utc) + timedelta(hours=6)
        time_str = bd_now.strftime('%I:%M %p')
        
        is_active = user_id in auto_live_subscribers
        status_text = "🟢 ACTIVE" if is_active else "⚪ OFF"
        toggle_label = "⚡ Live Auto Signal Feed: [ ON ]" if is_active else "⚡ Live Auto Signal Feed: [ OFF ]"

        keyboard = [
            [InlineKeyboardButton(toggle_label, callback_data='TOGGLE_AUTO')],
            [InlineKeyboardButton('🔒 Lock Bot', callback_data='LOCK_BOT')]
        ]
        row = []
        for pair_name, info in REAL_PAIRS.items():
            btn = InlineKeyboardButton(f"{info['flag']} {pair_name}", callback_data=f'PAIR_{pair_name}')
            row.append(btn)
            if len(row) == 2:
                keyboard.append(row)
                row = []
        if row:
            keyboard.append(row)

        reply_markup = InlineKeyboardMarkup(keyboard)
        
        menu_text = f"""
👑 === SIAM TRADERS LUXURY FOREX AI === 👑
 
🇧🇩 LOCATION: `Bangladesh (UTC +6:00)`
⏰ LOCAL TIME: `{time_str}`
🌐 MARKET: `{market_status}`
🚀 FUTURE DUAL-ENGINE: `EMA/RSI + SuperTrend/ADX`
⚡ LIVE DUAL-ENGINE: `Bollinger/Stoch + S/R Patterns`
⚡ *Live Auto Feed Status:* `{status_text}`
━━━━━━━━━━━━━━━━━━━━━━━━━━
╔═════════════════════════════╗
║ DEVELOPER & OWNER: SIAM TRADERS ║
╚═════════════════════════════╝
━━━━━━━━━━━━━━━━━━━━━━━━━━
✨ *Select Forex Pair or Start Live Auto Signals below:* 👇
"""
        if update.message:
            await update.message.reply_text(menu_text, reply_markup=reply_markup)
    except Exception as e:
        print(f'Show new menu error: {e}')


async def button_handler(update: Update, context: ContextTypes.DEFAULT_TYPE):
    try:
        query = update.callback_query
        try:
            await query.answer()
        except TelegramError:
            pass
            
        data = query.data
        user_id = query.from_user.id

        if data == 'LOCK_BOT':
            if user_id in authorized_users:
                authorized_users.remove(user_id)
            
            offline_popup_text = """
╔═════════════════════════════════╗
║     🔒 SIAM TRADERS OFFLINE     ║
║        SESSION CLOSED           ║
╚═════════════════════════════════╝
✨ *Status:* Bot is securely locked.
🔐 *Security:* All sessions cleared.
📱 Type /start to unlock and enter password again.
╔═════════════════════════════╗
║ DEVELOPER & OWNER: SIAM TRADERS ║
╚═════════════════════════════╝
"""
            await query.message.edit_text(offline_popup_text, parse_mode='Markdown')
            
            for group_id in TARGET_GROUP_IDS:
                try:
                    await context.bot.send_message(chat_id=group_id, text=offline_popup_text, parse_mode='Markdown')
                except Exception:
                    pass
            return

        if user_id not in authorized_users:
            await query.message.edit_text("🔒 *Session Locked!* Please type /start and enter password to continue.", parse_mode='Markdown')
            return

        if data == 'TOGGLE_AUTO':
            market_status = get_detailed_market_status()
            if "CLOSED" in market_status:
                closed_msg = f"⚠️ *Warning:* Forex Market is currently `{market_status}`! Auto signals might be paused until market opens."
                await query.message.reply_text(closed_msg, parse_mode='Markdown')

            if user_id in auto_live_subscribers:
                auto_live_subscribers.remove(user_id)
                await query.message.reply_text("🛑 *Live Auto Signals Stopped.*", parse_mode='Markdown')
            else:
                auto_live_subscribers.add(user_id)
                await query.message.reply_text(
                    "🚀 *Live Dual-Engine Auto Signals Started!*",
                    parse_mode='Markdown',
                )
            
            await show_main_menu(update, context)
            return

        if data.startswith('PAIR_'):
            selected_pair = data.replace('PAIR_', '')
            user_selections[user_id] = {'pair': selected_pair}

            keyboard = [
                [
                    InlineKeyboardButton('1 Signal', callback_data='COUNT_1'),
                    InlineKeyboardButton('2 Signals', callback_data='COUNT_2'),
                    InlineKeyboardButton('3 Signals', callback_data='COUNT_3'),
                    InlineKeyboardButton('4 Signals', callback_data='COUNT_4'),
                ],
                [
                    InlineKeyboardButton('5 Signals', callback_data='COUNT_5'),
                    InlineKeyboardButton('6 Signals', callback_data='COUNT_6'),
                    InlineKeyboardButton('7 Signals', callback_data='COUNT_7'),
                    InlineKeyboardButton('8 Signals (MAX)', callback_data='COUNT_8'),
                ],
                [
                    InlineKeyboardButton('🔙 Back to Main Menu', callback_data='BACK_TO_MENU')
                ]
            ]
            reply_markup = InlineKeyboardMarkup(keyboard)
            await query.message.edit_text(
                f'💱 Selected Forex Pair: `{selected_pair}`\n\n✨ *Step 2: How many signals do you want?* 👇',
                reply_markup=reply_markup,
                parse_mode='Markdown',
            )

        elif data.startswith('COUNT_'):
            count = int(data.replace('COUNT_', ''))
            if user_id in user_selections:
                user_selections[user_id]['count'] = count

            keyboard = [
                [
                    InlineKeyboardButton('⚡ 1 Minute Gap', callback_data='GAP_1'),
                    InlineKeyboardButton('🕒 3 Minutes Gap', callback_data='GAP_3'),
                    InlineKeyboardButton('🕔 5 Minutes Gap', callback_data='GAP_5'),
                ],
                [
                    InlineKeyboardButton('🔙 Back to Pairs', callback_data='BACK_TO_PAIRS')
                ]
            ]
            reply_markup = InlineKeyboardMarkup(keyboard)
            await query.message.edit_text(
                f'📊 Signals Count: `{count}`\n\n✨ *Step 3: Select time gap between signals:* 👇',
                reply_markup=reply_markup,
                parse_mode='Markdown',
            )

        elif data.startswith('GAP_'):
            gap = int(data.replace('GAP_', ''))
            user_data = user_selections.get(user_id)

            if not user_data:
                await query.message.edit_text('⚠️ Session expired. Please press /start again.')
                return

            market_status = get_detailed_market_status()
            if "CLOSED" in market_status:
                closed_market_msg = f"⚠️ *Market is currently {market_status}!*\nReal-time forex market is closed right now. Signals may not process accurately until market opens."
                await query.message.edit_text(closed_market_msg, parse_mode='Markdown')
                return

            pair_name = user_data['pair']
            count = user_data['count']
            info = REAL_PAIRS[pair_name]
            
            bd_now = datetime.now(timezone.utc) + timedelta(hours=6)
            current_date = bd_now.strftime('%d.%m.%Y')

            signals_generated = []
            session_items = []
            base_time = bd_now + timedelta(minutes=gap)

            for _ in range(count):
                action = None
                for _retry in range(2):
                    action = await analyze_future_market_combined(info['ticker'], info['alpha'])
                    if action:
                        break
                    await asyncio.sleep(0.3)

                if not action:
                    continue

                target_time_str = base_time.strftime('%H:%M')
                flag = info['flag']

                line_str = f'{flag} `{pair_name}` | `{action}` | `{target_time_str}` (Pending)'
                signals_generated.append(line_str)

                session_items.append({
                    'pair': pair_name,
                    'ticker': info['ticker'],
                    'alpha': info['alpha'],
                    'action': action,
                    'time': target_time_str,
                    'datetime_obj': base_time,
                    'status': '(Pending)',
                    'flag': flag,
                    'checked': False,
                })

                base_time += timedelta(minutes=gap)
                await asyncio.sleep(0.2)

            if not signals_generated:
                await query.message.edit_text(
                    "⚠️ *Market connection unstable or data unavailable right now.* Please try again after a moment.",
                    parse_mode='Markdown'
                )
                return

            final_text = f"""
👑 === SIAM TRADERS LUXURY FOREX MASTER === 👑

🇧🇩 TIME: ➡️ UTC +6:00 (Dhaka) | MARKET: `{market_status}`
💱 ASSET: `{pair_name}` (Real Forex Market)
⏳ GAP: `{gap} Minutes` | TOTAL: `{len(signals_generated)} Signals`
💎 FUTURE ENGINE: `EMA + SuperTrend + ADX + S/R`

────────────────────────
📊 🟢I🟢 PREMIUM REAL SIGNALS LIST 📉🔴.
────────────────────────

📅 `{current_date}`
🇧🇩 UTC +6:00 (Dhaka, Bangladesh)
🚀 INTERNATIONAL FOREX FEED
⚠️ **NOTE: SAFETY MARGIN MUST BE USED!**
🚨 MAX MARTINGALE: 1
╔═════════════════════════════╗
║ DEVELOPER & OWNER: SIAM TRADERS ║
╚═════════════════════════════╝

""" + '\n'.join(signals_generated) + """

────────────────────────
╔═════════════════════════════╗
║ DEVELOPER & OWNER: SIAM TRADERS ║
╚═════════════════════════════╝
"""

            back_keyboard = InlineKeyboardMarkup([
                [InlineKeyboardButton('🔙 Return to Main Menu', callback_data='BACK_TO_MENU'),
                 InlineKeyboardButton('🔒 Lock Bot', callback_data='LOCK_BOT')]
            ])

            sent_message = await query.message.edit_text(final_text, reply_markup=back_keyboard, parse_mode='Markdown')

            for group_id in TARGET_GROUP_IDS:
                try:
                    g_msg = await context.bot.send_message(chat_id=group_id, text=final_text, parse_mode='Markdown')
                    async with data_lock:
                        for sig in session_items:
                            active_signals.append({
                                'pair': sig['pair'],
                                'ticker': sig['ticker'],
                                'alpha': sig['alpha'],
                                'action': sig['action'],
                                'time': sig['time'],
                                'datetime_obj': sig['datetime_obj'],
                                'status': sig['status'],
                                'flag': sig['flag'],
                                'checked': False,
                                'chat_id': group_id,
                                'msg_id': g_msg.message_id,
                            })
                except Exception:
                    pass

            async with data_lock:
                for sig in session_items:
                    sig['chat_id'] = sent_message.chat_id
                    sig['msg_id'] = sent_message.message_id
                    active_signals.append(sig)

        elif data == 'BACK_TO_MENU':
            await show_main_menu(update, context)

        elif data == 'BACK_TO_PAIRS':
            keyboard = []
            row = []
            for pair_name, info in REAL_PAIRS.items():
                btn = InlineKeyboardButton(f"{info['flag']} {pair_name}", callback_data=f'PAIR_{pair_name}')
                row.append(btn)
                if len(row) == 2:
                    keyboard.append(row)
                    row = []
            if row:
                keyboard.append(row)
            keyboard.append([InlineKeyboardButton('🔙 Main Menu', callback_data='BACK_TO_MENU')])
            
            reply_markup = InlineKeyboardMarkup(keyboard)
            await query.message.edit_text('✨ *Select Forex Pair:* 👇', reply_markup=reply_markup, parse_mode='Markdown')

    except Exception as e:
        print(f'Button handler error: {e}')


async def background_live_auto_scanner(app):
    await asyncio.sleep(10)
    while True:
        try:
            market_status = get_detailed_market_status()
            if "CLOSED" in market_status:
                await asyncio.sleep(60)
                continue

            if auto_live_subscribers:
                pair_keys = list(REAL_PAIRS.keys())
                selected_sample = random.sample(pair_keys, min(2, len(pair_keys)))
                
                for pair_name in selected_sample:
                    info = REAL_PAIRS[pair_name]
                    
                    action = None
                    engine_used = ""
                    
                    for _retry in range(2):
                        action = await analyze_live_feed_market_engine1(info['ticker'], info['alpha'])
                        if action:
                            engine_used = "Bollinger + Stochastic (Engine 1)"
                            break
                        
                        action = await analyze_live_feed_market_engine2(info['alpha'], info['ticker'])
                        if action:
                            engine_used = "Support/Resistance + Rejection (Engine 2)"
                            break

                        await asyncio.sleep(0.4)

                    if not action:
                        continue
                    
                    bd_now = datetime.now(timezone.utc) + timedelta(hours=6)
                    target_time = bd_now + timedelta(minutes=1)
                    target_time_str = target_time.strftime('%H:%M')
                    current_date = bd_now.strftime('%d.%m.%Y')
                    flag = info['flag']

                    signal_box_text = f"""
👑 === SIAM TRADERS DUAL-ENGINE LIVE FEED === 👑

🇧🇩 TIME: ➡️ UTC +6:00 (Dhaka) | MARKET: `{market_status}`
💱 ASSET: `{pair_name}` (Real Forex Market)
⚡ STRATEGY: `{engine_used}`

────────────────────────
📊 🟢I🟢 LIVE DUAL-CONFIRMATION SIGNAL 📉🔴.
────────────────────────

📅 `{current_date}`
{flag} `{pair_name}` | `{action}` | `{target_time_str}` (Pending)

⚠️ **NOTE: TRADE AT CANDLE START WITH SAFETY MARGIN!**
🚨 MAX MARTINGALE: 1
╔═════════════════════════════╗
║ DEVELOPER & OWNER: SIAM TRADERS ║
╚═════════════════════════════╝
"""
                    for user_id in list(auto_live_subscribers):
                        try:
                            sent_msg = await app.bot.send_message(
                                chat_id=user_id, text=signal_box_text, parse_mode='Markdown'
                            )
                            async with data_lock:
                                active_signals.append({
                                    'pair': pair_name,
                                    'ticker': info['ticker'],
                                    'alpha': info['alpha'],
                                    'action': action,
                                    'time': target_time_str,
                                    'datetime_obj': target_time,
                                    'status': '(Pending)',
                                    'flag': flag,
                                    'checked': False,
                                    'chat_id': user_id,
                                    'msg_id': sent_msg.message_id,
                                })
                            await asyncio.sleep(0.1)
                        except Exception:
                            pass

                    for group_id in TARGET_GROUP_IDS:
                        try:
                            g_msg = await app.bot.send_message(
                                chat_id=group_id, text=signal_box_text, parse_mode='Markdown'
                            )
                            async with data_lock:
                                active_signals.append({
                                    'pair': pair_name,
                                    'ticker': info['ticker'],
                                    'alpha': info['alpha'],
                                    'action': action,
                                    'time': target_time_str,
                                    'datetime_obj': target_time,
                                    'status': '(Pending)',
                                    'flag': flag,
                                    'checked': False,
                                    'chat_id': group_id,
                                    'msg_id': g_msg.message_id,
                                })
                            await asyncio.sleep(0.1)
                        except Exception:
                            pass
                    
                    await asyncio.sleep(30)
        except Exception as e:
            print(f'Auto scanner error: {e}')

        await asyncio.sleep(20)


async def background_live_tracker(app):
    global active_signals
    await asyncio.sleep(5)
    while True:
        try:
            bd_now = datetime.now(timezone.utc) + timedelta(hours=6)
            current_time_str = bd_now.strftime('%H:%M')
            current_date = bd_now.strftime('%d.%m.%Y')
            market_status = get_detailed_market_status()

            async with data_lock:
                if active_signals:
                    msg_groups = {}
                    for sig in active_signals:
                        m_id = sig.get('msg_id')
                        c_id = sig.get('chat_id')
                        key = f"{c_id}_{m_id}"
                        if m_id and c_id:
                            if key not in msg_groups:
                                msg_groups[key] = []
                            msg_groups[key].append(sig)

                    for key, sigs in list(msg_groups.items()):
                        updated_any = False
                        for sig in sigs:
                            if not sig['checked'] and current_time_str >= sig['time']:
                                df = await get_robust_market_data(sig['ticker'], sig['alpha'])

                                if df is not None and len(df) >= 2:
                                    sig['checked'] = True
                                    open_price = float(df.iloc[-1]['Open'])
                                    close_price = float(df.iloc[-1]['Close'])

                                    is_win = False
                                    if sig['action'] == 'PUT' and close_price <= open_price:
                                        is_win = True
                                    elif sig['action'] == 'CALL' and close_price >= open_price:
                                        is_win = True

                                    sig['status'] = '✅ (WIN)' if is_win else '❌ (LOSS)'
                                    updated_any = True

                        if updated_any:
                            first_sig = sigs[0]
                            chat_id = first_sig['chat_id']
                            m_id = first_sig['msg_id']
                            pair = first_sig['pair']
                            total_sigs = len(sigs)

                            rebuilt_lines = []
                            for s in sigs:
                                rebuilt_lines.append(
                                    f"{s['flag']} `{s['pair']}` | `{s['action']}` | `{s['time']}` {s['status']}"
                                )

                            new_full_text = f"""
👑 === SIAM TRADERS LUXURY FOREX MASTER === 👑

🇧🇩 TIME: ➡️ UTC +6:00 (Dhaka) | MARKET: `{market_status}`
💱 ASSET: `{pair}` (Real Forex Market) | TOTAL: `{total_sigs} Signals`
💎 ENGINE: `DUAL-ENGINE FUTURE & LIVE ACTIVE`

────────────────────────
📊 🟢I🟢 PREMIUM REAL SIGNALS LIST 📉🔴.
────────────────────────

📅 `{current_date}`
🇧🇩 UTC +6:00 (Dhaka, Bangladesh)
🚀 INTERNATIONAL FOREX FEED
⚠️ **NOTE: SAFETY MARGIN MUST BE USED!**
🚨 MAX MARTINGALE: 1
╔═════════════════════════════╗
║ DEVELOPER & OWNER: SIAM TRADERS ║
╚═════════════════════════════╝

""" + '\n'.join(rebuilt_lines) + """

────────────────────────
╔═════════════════════════════╗
║ DEVELOPER & OWNER: SIAM TRADERS ║
╚═════════════════════════════╝
"""

                            try:
                                if chat_id in TARGET_GROUP_IDS:
                                    markup = None
                                else:
                                    markup = InlineKeyboardMarkup([
                                        [InlineKeyboardButton('🔙 Return to Main Menu', callback_data='BACK_TO_MENU'),
                                         InlineKeyboardButton('🔒 Lock Bot', callback_data='LOCK_BOT')]
                                    ])

                                await app.bot.edit_message_text(
                                    chat_id=chat_id,
                                    message_id=m_id,
                                    text=new_full_text,
                                    reply_markup=markup,
                                    parse_mode='Markdown',
                                )
                                await asyncio.sleep(0.2)
                            except Exception as err:
                                print(f"Edit error for chat {chat_id}: {err}")

                    active_signals[:] = [
                        s for s in active_signals 
                        if not s['checked'] or (bd_now - s['datetime_obj']).total_seconds() < 1800
                    ]

        except Exception as e:
            print(f'Tracker loop error: {e}')

        await asyncio.sleep(10)


async def main_async():
    try:
        request = HTTPXRequest(connect_timeout=40.0, read_timeout=40.0)
        app = ApplicationBuilder().token(TELEGRAM_BOT_TOKEN).request(request).build()

        app.add_handler(CommandHandler('start', start))
        app.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, handle_message))
        app.add_handler(CallbackQueryHandler(button_handler))

        asyncio.create_task(background_live_tracker(app))
        asyncio.create_task(background_live_auto_scanner(app))

        print('SIAM TRADERS Secure Luxury Forex Bot running with Anti-Block Multi-API Circuit Breaker...')
        await app.initialize()
        await app.start()
        await app.updater.start_polling()

        stop_event = asyncio.Event()
        await stop_event.wait()
    except Exception as e:
        print(f'Main async error: {e}')


def main():
    try:
        asyncio.run(main_async())
    except (KeyboardInterrupt, SystemExit):
        print('Bot stopped safely.')


if __name__ == '__main__':
    main()
