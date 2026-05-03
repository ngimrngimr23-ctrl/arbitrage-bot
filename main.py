import aiohttp
import asyncio
import json
import os
import urllib.parse

API_TOKEN = os.environ.get("GIFT_SATELLITE_TOKEN")
BASE_URL = "https://gift-satellite.dev/api"

async def main():
    headers = {"Authorization": f"Token {API_TOKEN}"}
    
    # Тестируем Пепе в разных форматах
    test_slugs = [
        "Plush Pepe",                       # Как есть 
        urllib.parse.quote("Plush Pepe"),   # С закодированным пробелом
        "plush-pepe",                       # Классический слаг через дефис
        "plush_pepe"                        # Через нижнее подчеркивание
    ]
    
    print("🚀 Вытаскиваем JSON (без ботов, только логи)...")
    
    async with aiohttp.ClientSession() as session:
        for slug in test_slugs:
            url = f"{BASE_URL}/search/tg/{slug}?limit=1"
            print(f"👉 Пробуем: {slug}")
            
            try:
                async with session.get(url, headers=headers) as r:
                    if r.status == 200:
                        data = await r.json()
                        print(f"✅ УСПЕХ! Правильный формат: '{slug}'")
                        print("================ JSON СТАРТ ================")
                        print(json.dumps(data, indent=4, ensure_ascii=False))
                        print("================ JSON КОНЕЦ ================")
                        return # Выходим, мы получили данные!
                    else:
                        print(f"❌ Ошибка {r.status}")
            except Exception as e:
                print(f"⚠️ Сбой сети: {e}")
            
            # СПИМ 4 СЕКУНДЫ, ЧТОБЫ СЕРВЕР НЕ ДАЛ БАН ЗА СПАМ
            print("💤 Ждем 4 сек...")
            await asyncio.sleep(4)
            
        print("😭 Ни один вариант не прошел.")

if __name__ == "__main__":
    asyncio.run(main())
    
