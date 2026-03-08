import asyncio
import aiohttp
import os
import time
from flask import Flask
from threading import Thread

# --- ЦЕНТРАЛЬНЫЕ НАСТРОЙКИ ---
SETTINGS = {
    'top_pump': 15.0,
    'top_dump': 15.0,
    'rare_pump': 20.0,
    'rare_dump': 20.0,
    'h1_dump': 25.0,
    'min_liq': 50000.0,    # Минимальная ликвидность ($) для монет БЕЗ ID
    'cooldown': 3600,      # 1 час молчания для дубликатов
    'api_pause': 2.3,      # Пауза между страницами API
    'tg_pause': 1.5,       # Пауза между сообщениями в ТГ
    'request_timeout': 15  # Секунд на ожидание ответа
}

TG_BOT_TOKEN = os.environ.get('TG_BOT_TOKEN')
TG_CHAT_ID = os.environ.get('TG_CHAT_ID')

if not TG_BOT_TOKEN or not TG_CHAT_ID:
    raise ValueError("❌ КРИТИЧЕСКАЯ ОШИБКА: Проверь переменные окружения!")

TOP_CHAINS = ['eth', 'bsc', 'polygon', 'arbitrum', 'base', 'solana']
sent_signals = {}

# Словарь для конвертации сетей для прямого API CoinGecko
CG_NETWORKS = {
    'eth': 'ethereum', 'bsc': 'binance-smart-chain', 
    'polygon_pos': 'polygon-pos', 'arbitrum': 'arbitrum-one', 
    'base': 'base', 'solana': 'solana'
}

app = Flask(__name__)
@app.route('/')
def home(): return "Arbitrage Pro (ID + Liq + CG API) Active"

async def check_coingecko_listing(session, address, network):
    """Прямой запрос в CoinGecko (запасной вариант)"""
    cg_net = CG_NETWORKS.get(network, network)
    url = f"https://api.coingecko.com/api/v3/coins/{cg_net}/contract/{address}"
    try:
        async with session.get(url, timeout=5) as resp:
            if resp.status == 200:
                data = await resp.json()
                return data.get('id')
            return None
    except:
        return None

async def send_tg(session, text):
    url = f"https://api.telegram.org/bot{TG_BOT_TOKEN}/sendMessage"
    payload = {'chat_id': TG_CHAT_ID, 'text': text, 'parse_mode': 'HTML', 'disable_web_page_preview': True}
    try:
        async with session.post(url, json=payload, timeout=SETTINGS['request_timeout']) as resp:
            data = await resp.json()
            if not data.get('ok'):
                print(f"⚠️ Ошибка Telegram API: {data.get('description')}")
            return data
    except Exception as e:
        print(f"❌ Сбой сети ТГ: {e}")

async def get_all_networks(session):
    all_nets = []
    headers = {'User-Agent': 'Mozilla/5.0'}
    for page in range(1, 5):
        url = f"https://api.geckoterminal.com/api/v2/networks?page={page}"
        try:
            async with session.get(url, headers=headers, timeout=SETTINGS['request_timeout']) as resp:
                if resp.status != 200: break
                data = await resp.json()
                for net in data.get('data', []):
                    all_nets.append(net['id'])
            await asyncio.sleep(1)
        except: break
    for top in TOP_CHAINS:
        if top not in all_nets: all_nets.append(top)
    return all_nets

async def check_markets(session, network):
    is_top = network in TOP_CHAINS
    p_th = SETTINGS['top_pump'] if is_top else SETTINGS['rare_pump']
    d_th = SETTINGS['top_dump'] if is_top else SETTINGS['rare_dump']
    h1_th = SETTINGS['h1_dump']
    min_liq = SETTINGS['min_liq']
    
    print(f"\n📡 СКАНИРУЮ: {network.upper()}")
    headers = {'User-Agent': 'Mozilla/5.0'}
    stats = {'passed': 0, 'trash': 0, 'signals': 0, 'cg_api_hits': 0}
    now = time.time()
    
    for page in range(1, 11):
        url = f"https://api.geckoterminal.com/api/v2/networks/{network}/pools?page={page}&include=base_token"
        try:
            async with session.get(url, headers=headers, timeout=SETTINGS['request_timeout']) as resp:
                if resp.status == 429:
                    print(f"🛑 БАН 429 на {network}")
                    await asyncio.sleep(60); break
                if resp.status != 200: break
                
                rj = await resp.json()
                pools = rj.get('data', [])
                inc = rj.get('included') or []
                tokens = {t['id']: t['attributes'] for t in inc if t.get('type') == 'token'}
                
                for p in pools:
                    try:
                        attrs = p.get('attributes', {})
                        addr = attrs.get('address')
                        t_id = p.get('relationships', {}).get('base_token', {}).get('data', {}).get('id')
                        cg_id = tokens.get(t_id, {}).get('coingecko_coin_id')
                        liq = float(attrs.get('reserve_in_usd') or 0)
                        
                        pct = attrs.get('price_change_percentage') or {}
                        m5, h1, h24 = float(pct.get('m5') or 0), float(pct.get('h1') or 0), float(pct.get('h24') or 0)
                        
                        is_p, is_d = m5 >= p_th, m5 <= -d_th
                        is_h1 = (h1 <= -h1_th) and (h24 <= (h1 * 0.8))
                        is_triggered = is_p or is_d or is_h1
                        
                        # --- ЛОГИКА ФИЛЬТРАЦИИ ---
                        if cg_id:
                            pass # 1. Есть ID от GeckoTerminal -> Пропускаем
                        elif liq >= min_liq:
                            pass # 2. Нет ID, но ликвидность высокая -> Пропускаем
                        else:
                            # 3. Нет ID, ликвидность низкая. Ждем триггера.
                            if not is_triggered:
                                stats['trash'] += 1
                                continue
                            
                            # 4. Произошел ПАМП/ДАМП! Делаем запасной запрос в CoinGecko
                            print(f"🔍 Прямой запрос в CoinGecko для: {attrs.get('name')} ({addr})")
                            cg_id = await check_coingecko_listing(session, addr, network)
                            
                            if cg_id:
                                stats['cg_api_hits'] += 1
                                print(f"✅ Найден скрытый ID: {cg_id}")
                            else:
                                stats['trash'] += 1
                                continue # Если и тут нет - в мусор
                        
                        stats['passed'] += 1
                        
                        # --- ОТПРАВКА СИГНАЛА ---
                        if is_triggered:
                            type_sig = "P5" if is_p else ("D5" if is_d else "DH1")
                            key = f"{network}_{addr}_{type_sig}"
                            
                            if key in sent_signals and (now - sent_signals[key]) < SETTINGS['cooldown']: continue
                            sent_signals[key] = now
                            stats['signals'] += 1
                            
                            act = "🚀 ПАМП (5м)" if is_p else ("🩸 ДАМП (5м)" if is_d else "⚠️ ЧАСОВОЙ ДАМП")
                            id_str = f"<code>{cg_id}</code>" if cg_id else "❌ <i>(Только ликвидность)</i>"
                            
                            # Ссылки на CoinGecko
                            cg_link = f"🦎 <a href='https://www.coingecko.com/en/coins/{cg_id}'>CoinGecko</a>" if cg_id else "🦎 <i>Нет на CG</i>"
                            gt_link = f"📈 <a href='https://www.geckoterminal.com/{network}/pools/{addr}'>График (GeckoTerminal)</a>"
                            
                            msg = (f"{act} | <b>{network.upper()}</b>\n"
                                   f"Пара: <code>{attrs.get('name')}</code>\n"
                                   f"ID: {id_str}\n"
                                   f"Ликвидность: <b>${liq:,.0f}</b>\n\n"
                                   f"5m: <b>{m5}%</b> | 1h: <b>{h1}%</b> | 24h: <b>{h24}%</b>\n\n"
                                   f"Контракт: <code>{addr}</code>\n"
                                   f"{cg_link} | {gt_link}")
                            await send_tg(session, msg)
                            await asyncio.sleep(SETTINGS['tg_pause'])
                    except: continue
            await asyncio.sleep(SETTINGS['api_pause'])
        except Exception as e:
            print(f"❌ Ошибка страницы {page}: {e}"); break
            
    print(f"📊 {network}: Прошли: {stats['passed']} | Мусор: {stats['trash']} | Найдено через API: {stats['cg_api_hits']} | Сигналы: {stats['signals']}")

async def handle_cmds():
    offset = 0
    async with aiohttp.ClientSession() as sess:
        while True:
            url = f"https://api.telegram.org/bot{TG_BOT_TOKEN}/getUpdates?offset={offset}&timeout=10"
            try:
                async with sess.get(url, timeout=SETTINGS['request_timeout']) as resp:
                    data = await resp.json()
                    for up in data.get('result', []):
                        offset = up['update_id'] + 1
                        msg = up.get('message')
                        if not msg or str(msg.get('chat', {}).get('id')) != str(TG_CHAT_ID): continue
                        txt = msg.get('text', '')
                        
                        if txt == '/start':
                            await send_tg(sess, f"🤖 <b>Pro Scanner (ID + Liq + CG API)</b>\n\n"
                                               f"🏆 ТОП-6 (P/D): <b>{SETTINGS['top_pump']}%</b> / <b>-{SETTINGS['top_dump']}%</b>\n"
                                               f"💎 Редкие (P/D): <b>{SETTINGS['rare_pump']}%</b> / <b>-{SETTINGS['rare_dump']}%</b>\n"
                                               f"⏳ H1 Дамп: <b>-{SETTINGS['h1_dump']}%</b>\n"
                                               f"💧 Мин. ликвидность: <b>${SETTINGS['min_liq']:,.0f}</b>\n\n"
                                               "<b>Команды:</b>\n"
                                               "/pump_top [ч] | /dump_top [ч]\n"
                                               "/pump_rare [ч] | /dump_rare [ч]\n"
                                               "/dump_h1 [ч] | /min_liq [ч]")
                        elif txt.startswith('/'):
                            parts = txt.split()
                            if len(parts) == 2:
                                try:
                                    val = abs(float(parts[1]))
                                    if '/pump_top' in txt: SETTINGS['top_pump'] = val
                                    elif '/dump_top' in txt: SETTINGS['top_dump'] = val
                                    elif '/pump_rare' in txt: SETTINGS['rare_pump'] = val
                                    elif '/dump_rare' in txt: SETTINGS['rare_dump'] = val
                                    elif '/dump_h1' in txt: SETTINGS['h1_dump'] = val
                                    elif '/min_liq' in txt: SETTINGS['min_liq'] = val
                                    await send_tg(sess, f"✅ Обновлено: {val}")
                                except: pass
            except: pass
            await asyncio.sleep(2)

async def main_loop():
    asyncio.create_task(handle_cmds())
    conn = aiohttp.TCPConnector(limit=10)
    async with aiohttp.ClientSession(connector=conn) as sess:
        while True:
            nets = await get_all_networks(sess)
            print(f"\n====================================")
            print(f"🚀 НАЧИНАЮ НОВЫЙ КРУГ ({len(nets)} сетей)")
            print(f"====================================")
            for n in nets: await check_markets(sess, n)
            
            cur = time.time()
            to_del = [k for k, v in sent_signals.items() if (cur - v) > SETTINGS['cooldown']]
            for k in to_del: del sent_signals[k]
            
            print("🏁 КРУГ ЗАВЕРШЕН. Отдыхаем 30 секунд...")
            await asyncio.sleep(30)

if __name__ == "__main__":
    srv = Thread(target=lambda: app.run(host='0.0.0.0', port=int(os.environ.get('PORT', 8080))), daemon=True)
    srv.start()
    asyncio.run(main_loop())
