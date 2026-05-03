import aiohttp
import asyncio
import json
import os
import urllib.parse # <-- Добавили парсер ссылок

API_TOKEN = os.environ.get("GIFT_SATELLITE_TOKEN")
BASE_URL = "https://gift-satellite.dev/api"

async def main():
    # Правильно кодируем название коллекции для URL
    collection_name = urllib.parse.quote("Durov's Cap")
    url = f"{BASE_URL}/search/tg/{collection_name}?limit=1"
    
    headers = {"Authorization": f"Token {API_TOKEN}"}
    
    print(f"🚀 Стучимся по ссылке: {url}")
    
    async with aiohttp.ClientSession() as session:
        try:
            async with session.get(url, headers=headers) as r:
                data = await r.json()
                print("================ JSON СТАРТ ================")
                print(json.dumps(data, indent=4, ensure_ascii=False))
                print("================ JSON КОНЕЦ ================")
        except Exception as e:
            print(f"❌ Ошибка: {e}")

if __name__ == "__main__":
    asyncio.run(main())
