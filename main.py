from fastapi import FastAPI, HTTPException
from typing import List, Dict, Optional
import os
from dotenv import load_dotenv
from supabase import create_client, Client
from recommendation import get_recommendations, get_popular_products_by_category, get_bought_together_products, get_user_popular_products, get_popular_products
from fastapi.middleware.cors import CORSMiddleware

# .env dosyasını yükle
load_dotenv()

app = FastAPI(title="Öneri Sistemi API")

# CORS ayarlarını ekleyin
app.add_middleware(
    CORSMiddleware,
    allow_origins=["http://localhost:3000"],  # Web uygulamanızın URL'si
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# Supabase bağlantısı
supabase: Client = create_client(
    os.getenv("SUPABASE_URL", "https://tcjxcwazybrenfkydjwb.supabase.co"),
    os.getenv("SUPABASE_KEY", "eyJhbGciOiJIUzI1NiIsInR5cCI6IkpXVCJ9.eyJpc3MiOiJzdXBhYmFzZSIsInJlZiI6InRjanhjd2F6eWJyZW5ma3lkandiIiwicm9sZSI6InNlcnZpY2Vfcm9sZSIsImlhdCI6MTc0MjI0NjI5MSwiZXhwIjoyMDU3ODIyMjkxfQ.6TPJhP3C54lvuERR4OyoPwJeiEcyxVHRw8zULoeGKwU")
)

@app.get("/")
async def root():
    return {"message": "Öneri Sistemi API'sine Hoş Geldiniz"}

@app.get("/reco_api/{user_id}")
async def recommend(user_id: str, limit: Optional[int] = 15):
    print(f"[MAIN_RECO_API] İstek alındı: user_id={user_id}, limit={limit}")
    try:
        recommended = get_recommendations(user_id=user_id, limit=limit)
        print(f"[MAIN_RECO_API] get_recommendations sonucu: {len(recommended) if recommended is not None else 'None'} adet ürün")

        if not recommended:
            print(f"[MAIN_RECO_API] get_recommendations boş döndü, genel popüler ürünler denenecek.")
            recommended = get_popular_products(limit=limit)
            print(f"[MAIN_RECO_API] get_popular_products sonucu: {len(recommended) if recommended is not None else 'None'} adet ürün")

        if not recommended:
            response_data = {
                "user_id": user_id,
                "recommendations": [],
                "message": "Sizin için uygun bir öneri bulunamadı.",
                "status": "success_no_recommendation"
            }
            print(f"[MAIN_RECO_API] Sonuç: Uygun öneri yok. Yanıt: {response_data}")
            return response_data
            
        response_data = {
            "user_id": user_id,
            "recommendations": recommended,
            "status": "success"
        }
        print(f"[MAIN_RECO_API] Sonuç: Öneriler başarıyla oluşturuldu. Yanıt: {response_data['status']}, {len(response_data['recommendations'])} adet ürün")
        return response_data
    except HTTPException as http_exc:
        print(f"[MAIN_RECO_API] HTTPException oluştu: {http_exc.status_code} - {http_exc.detail}")
        raise http_exc
    except Exception as e:
        print(f"[MAIN_RECO_API] /reco_api/{user_id} endpointinde beklenmedik bir hata: {str(e)}")
        raise HTTPException(status_code=500, detail=f"Öneriler alınırken bir sunucu hatası oluştu: {str(e)}")

@app.get("/popular/{category_name}")
async def popular_products(category_name: str):
    try:
        products = get_popular_products_by_category(category_name, limit=15)
        return {"category": category_name, "products": products, "status": "success"}
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))

@app.get("/bought_together/{user_id}")
async def bought_together(user_id: str):
    try:
        products = get_bought_together_products(user_id)
        return {"user_id": user_id, "products": products, "status": "success"}
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))

@app.get("/user_popular/{user_id}")
async def user_popular(user_id: str):
    try:
        products = get_user_popular_products(user_id, limit=15)
        return {"user_id": user_id, "products": products, "status": "success"}
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))

if __name__ == "__main__":
    import uvicorn
    uvicorn.run(app, host="127.0.0.1", port=8000) 