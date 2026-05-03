import aiohttp
import asyncio
import json
import os

# Render сам подтянет твой токен из переменных окружения (Environment Variables)
API_TOKEN = os.environ.get("GIFT_SATELLITE_TOKEN")
BASE_URL = "https://gift-satellite.dev/api"

async def main():
    url = f"{BASE_URL}/search/tg/Durov's Cap?limit=1"
    headers = {"Authorization": f"Token {API_TOKEN}"}
    
    print("🚀 Запускаем тестовый запрос к API...")
    
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
    
