from typing import List, Dict, Set
from collections import defaultdict
import os
from supabase import create_client, Client
from dotenv import load_dotenv
import json

load_dotenv()

# Supabase bağlantısı
supabase: Client = create_client(
    os.getenv("SUPABASE_URL", "https://tcjxcwazybrenfkydjwb.supabase.co"),
    os.getenv("SUPABASE_KEY", "eyJhbGciOiJIUzI1NiIsInR5cCI6IkpXVCJ9.eyJpc3MiOiJzdXBhYmFzZSIsInJlZiI6InRjanhjd2F6eWJyZW5ma3lkandiIiwicm9sZSI6InNlcnZpY2Vfcm9sZSIsImlhdCI6MTc0MjI0NjI5MSwiZXhwIjoyMDU3ODIyMjkxfQ.6TPJhP3C54lvuERR4OyoPwJeiEcyxVHRw8zULoeGKwU")
)

# Yardımcı fonksiyonlar

def safe_json_loads(json_str, default_value):
    """Güvenli şekilde JSON parse eder"""
    if not json_str:
        return default_value
    try:
        return json.loads(json_str)
    except (json.JSONDecodeError, TypeError):
        print(f"Geçersiz JSON formatı: {json_str[:50]}...")
        return default_value

def validate_limit(limit: int, min_limit: int = 1, max_limit: int = 50) -> int:
    """Limit parametresini geçerli bir aralığa sınırlar"""
    if limit is None:
        return 15  # Varsayılan değer
    return max(min_limit, min(limit, max_limit))

def get_fallback_recommendations(user_id: str, clicked_products: Set[str], purchased_products: Set[str], limit: int) -> List[Dict]:
    print(f"[FALLBACK] Kullanıcı {user_id} için fallback önerileri oluşturuluyor.")
    user_categories = get_user_categories(user_id, clicked_products, purchased_products)
    if user_categories:
        print(f"[FALLBACK] Kullanıcının kategorileri ({user_categories[0]}) için popüler ürünler deneniyor.")
        # Birden fazla kategori varsa, hepsinden karışık veya en popüler kategoriden alınabilir. Şimdilik ilk kategori.
        return get_popular_products_by_category(user_categories[0], limit)
    print(f"[FALLBACK] Genel popüler ürünler deneniyor.")
    return get_popular_products(limit)

def calculate_recommendation_score(purchase_reco, click_reco, purchase_weight=0.7, click_weight=0.3, 
                                  user_activity_threshold=5):
    """Dengeli öneri skoru hesaplama"""
    product_scores = {}
    
    # Yeterli aktivite yoksa ağırlıkları dengele
    if len(purchase_reco) + len(click_reco) < user_activity_threshold:
        purchase_weight = 0.5
        click_weight = 0.5
    
    for pid in purchase_reco:
        product_scores[pid] = product_scores.get(pid, 0) + purchase_weight
    
    for pid in click_reco:
        product_scores[pid] = product_scores.get(pid, 0) + click_weight
    
    return product_scores

def has_sufficient_user_data(user_data, min_click=1, min_purchase=0):
    """Kullanıcının yeterli verisi olup olmadığını kontrol eder"""
    if not user_data:
        return False
    
    events_json = user_data.get("events_json", "{}")
    purchased_json = user_data.get("purchased_json", "[]")
    
    events = safe_json_loads(events_json, {})
    purchased = safe_json_loads(purchased_json, [])
    
    clicked_products = set(events.get("click", []))
    purchased_products = set([item["product_id"] for item in purchased if "product_id" in item])
    
    return len(clicked_products) >= min_click or len(purchased_products) >= min_purchase

def get_efficient_similar_users(user_id, product_ids, limit=50):
    """Büyük ürün listelerinde verimli benzer kullanıcı bulma"""
    if not product_ids:
        return set()
    
    # Tüm ürünler için tek seferde sorgu yap
    # Çok fazla ürün varsa, gruplar halinde yap
    max_batch_size = 20
    similar_users = set()
    
    for i in range(0, len(product_ids), max_batch_size):
        batch = list(product_ids)[i:i+max_batch_size]
        try:
            # Bu ürünlerin herhangi birini içeren kullanıcıları bul
            users = supabase.table("users_table").select("user_id").filter("events_json->click", "cs", batch).execute().data
            similar_users.update([u["user_id"] for u in users if u["user_id"] != user_id])
            
            if len(similar_users) >= limit:
                break
        except Exception as e:
            print(f"Benzer kullanıcılar bulunurken hata: {str(e)}")
    
    return similar_users

def get_users_products(user_ids, event_type, exclude_products=None):
    """Benzer kullanıcıların ürünlerini verimli şekilde toplar"""
    exclude_products = exclude_products or set()
    result_products = set()
    
    batch_size = 10
    for i in range(0, len(user_ids), batch_size):
        batch_user_ids = list(user_ids)[i:i+batch_size]
        
        try:
            if event_type == "click":
                u_data = supabase.table("users_table").select("events_json").in_("user_id", batch_user_ids).execute().data
                for data in u_data:
                    u_events = safe_json_loads(data.get("events_json", "{}"), {})
                    u_products = set(u_events.get("click", []))
                    result_products.update(u_products - exclude_products)
            else:
                u_data = supabase.table("users_table").select("purchased_json").in_("user_id", batch_user_ids).execute().data
                for data in u_data:
                    u_purchased = safe_json_loads(data.get("purchased_json", "[]"), [])
                    u_products = set([item["product_id"] for item in u_purchased if "product_id" in item])
                    result_products.update(u_products - exclude_products)
        except Exception as e:
            print(f"Kullanıcı ürünleri alınırken hata: {str(e)}")
    
    return result_products

def get_user_categories(user_id, clicked_products: Set[str], purchased_products: Set[str]):
    """Kullanıcının ilgilendiği kategorileri bulur"""
    product_ids = list(clicked_products.union(purchased_products))
    if not product_ids:
        print(f"[get_user_categories] Kullanıcı {user_id} için ürün ID bulunamadı."); return []
    try:
        print(f"[get_user_categories] {len(product_ids)} ürün için kategori aranıyor.")
        # Supabase sorgusunda IN listesi çok uzun olmamalı, gerekirse batch'le
        response = supabase.table("product_table").select("category_name").in_("product_id", product_ids[:50]).execute()
        products_data = response.data
        if not products_data: print(f"[get_user_categories] Ürünler için kategori bilgisi bulunamadı."); return []
        categories = list({p["category_name"] for p in products_data if p.get("category_name")})
        print(f"[get_user_categories] Bulunan kategoriler: {categories}")
        return categories
    except Exception as e: print(f"[get_user_categories] Kategori alınırken hata: {str(e)}"); return []

def get_recommendations(user_id: str, limit: int = 10) -> List[Dict]:
    print(f"[GET_RECO] Başlangıç: user_id={user_id}, limit={limit}")
    limit = validate_limit(limit)

    try:
        user_data_response = supabase.table("users_table").select("events_json, purchased_json").eq("user_id", user_id).execute()
        if not user_data_response.data:
            print(f"[GET_RECO] Kullanıcı {user_id} bulunamadı. Fallback'e geçiliyor (veri yok).")
            return get_fallback_recommendations(user_id, set(), set(), limit)
        
        user_profile = user_data_response.data[0]

        if not has_sufficient_user_data(user_profile):
            print(f"[GET_RECO] Kullanıcı {user_id} için yeterli etkileşim verisi yok. Fallback'e geçiliyor.")
            # Yetersiz veri durumunda da `get_fallback_recommendations` tıklama/satın alma kümelerini boş alır.
            raw_events = safe_json_loads(user_profile.get("events_json", "{}"), {})
            raw_purchases = safe_json_loads(user_profile.get("purchased_json", "[]"), [])
            temp_clicks = set(raw_events.get("click", []))
            temp_purchases = set(item["product_id"] for item in raw_purchases if "product_id" in item)
            return get_fallback_recommendations(user_id, temp_clicks, temp_purchases, limit)

        target_user_clicks_set: Set[str] = set(safe_json_loads(user_profile.get("events_json", "{}"), {}).get("click", []))
        target_user_purchases_list = safe_json_loads(user_profile.get("purchased_json", "[]"), [])
        target_user_purchases_set: Set[str] = {item["product_id"] for item in target_user_purchases_list if "product_id" in item}
        
        print(f"[GET_RECO] Kullanıcı {user_id}: {len(target_user_clicks_set)} tıklama, {len(target_user_purchases_set)} satın alma.")

        # Adım 1: Potansiyel işbirlikçilerin TÜM etkileşim verilerini çek
        # Bu adım, performansı en çok etkileyen adımdır ve optimize edilmelidir.
        # Basitlik adına, tüm kullanıcıların verilerini çekip filtreleyeceğiz (KÜÇÜK VERİ SETLERİ İÇİN UYGUN).
        # Büyük veri setleri için, hedef kullanıcıyla en az bir ortak ürünü olanları filtreleyip
        # sadece onların tam verilerini çekmek daha mantıklıdır.
        
        all_users_raw_data_response = supabase.table("users_table").select("user_id, events_json, purchased_json").neq("user_id", user_id).limit(500).execute() # Diğer kullanıcıları al (limitli)
        if not all_users_raw_data_response.data:
            print(f"[GET_RECO] Başka kullanıcı bulunamadı. Fallback.")
            return get_fallback_recommendations(user_id, target_user_clicks_set, target_user_purchases_set, limit)

        all_users_clicks_map: Dict[str, Set[str]] = {}
        all_users_purchases_map: Dict[str, Set[str]] = {}

        for u_data in all_users_raw_data_response.data:
            uid = u_data["user_id"]
            events = safe_json_loads(u_data.get("events_json", "{}"), {})
            purchases_list = safe_json_loads(u_data.get("purchased_json", "[]"), [])
            all_users_clicks_map[uid] = set(events.get("click", []))
            all_users_purchases_map[uid] = {item["product_id"] for item in purchases_list if "product_id" in item}
        
        print(f"[GET_RECO] {len(all_users_clicks_map)} diğer kullanıcının tıklama/satın alma verisi işlendi.")

        # Adım 2: Benzerlik Skorlarını Hesapla
        click_similar_users = _calculate_similarity_scores(target_user_clicks_set, all_users_clicks_map, user_id, top_n=30)
        purchase_similar_users = _calculate_similarity_scores(target_user_purchases_set, all_users_purchases_map, user_id, top_n=30)
        
        print(f"[GET_RECO] Benzer kullanıcılar: {len(click_similar_users)} tıklama bazlı, {len(purchase_similar_users)} satın alma bazlı.")

        # Adım 3: Aday Ürün Skorlarını Oluştur
        # Hedef kullanıcının zaten etkileşimde bulunduğu tüm ürünleri dışla
        exclude_products = target_user_clicks_set.union(target_user_purchases_set)

        click_candidate_scores = _generate_candidate_item_scores(click_similar_users, all_users_clicks_map, exclude_products)
        purchase_candidate_scores = _generate_candidate_item_scores(purchase_similar_users, all_users_purchases_map, exclude_products)

        # Adım 4: Skorları Birleştir
        final_product_scores: Dict[str, float] = defaultdict(float)
        CLICK_WEIGHT = 0.4
        PURCHASE_WEIGHT = 0.6

        for item, score in click_candidate_scores.items():
            final_product_scores[item] += score * CLICK_WEIGHT
        for item, score in purchase_candidate_scores.items():
            final_product_scores[item] += score * PURCHASE_WEIGHT
        
        print(f"[GET_RECO] {len(final_product_scores)} ürün için nihai skor hesaplandı.")

        if not final_product_scores:
            print(f"[GET_RECO] İşbirlikçi filtrelemeden sonuç çıkmadı. Fallback.")
            return get_fallback_recommendations(user_id, target_user_clicks_set, target_user_purchases_set, limit)

        # Adım 5: Sırala ve Ürün Detaylarını Çek
        sorted_candidate_ids = [pid for pid, score in sorted(final_product_scores.items(), key=lambda item: item[1], reverse=True)]
        
        # Stokta olmayanları ve zaten önerilmiş olabilecekleri filtrele (burada stok kontrolü daha iyi)
        # Şimdilik sadece ilk N tanesini alıyoruz, sonra detay çekip stok kontrolü yapabiliriz.
        reco_product_ids = sorted_candidate_ids[:limit * 2] # Detay çekmeden önce daha fazla al, sonra filtrele
        
        print(f"[GET_RECO] Önerilecek potansiyel ID'ler (filtrelenmeden önce): {reco_product_ids}")

        if not reco_product_ids:
            print(f"[GET_RECO] Skorlamadan sonra önerilecek ID kalmadı. Fallback.")
            return get_fallback_recommendations(user_id, target_user_clicks_set, target_user_purchases_set, limit)

        products_response = supabase.table("product_table").select("*").in_("product_id", reco_product_ids).execute()
        
        if not products_response.data:
            print(f"[GET_RECO] Ürün detayları (stokta olan) bulunamadı. Fallback.")
            return get_fallback_recommendations(user_id, target_user_clicks_set, target_user_purchases_set, limit)

        # Gelen ürünleri orijinal skor sıralamasına göre tekrar sırala (Supabase IN sorgusu sırayı korumayabilir)
        # ve limiti uygula
        detailed_products = products_response.data
        product_map = {p["product_id"]: p for p in detailed_products}
        
        final_recommendations = []
        for pid in reco_product_ids: # sorted_candidate_ids kullanılmalıydı ama reco_product_ids zaten ondan türedi
            if pid in product_map:
                final_recommendations.append(product_map[pid])
            if len(final_recommendations) >= limit:
                break
        
        print(f"[GET_RECO] Nihai {len(final_recommendations)} öneri oluşturuldu.")
        
        if not final_recommendations:
             print(f"[GET_RECO] Filtreleme sonrası öneri kalmadı. Fallback.")
             return get_fallback_recommendations(user_id, target_user_clicks_set, target_user_purchases_set, limit)

        return final_recommendations

    except Exception as e:
        print(f"[GET_RECO] BEKLENMEDİK HATA: {str(e)}. Fallback'e geçiliyor.")
        # Hata durumunda bile fallback denemesi için kullanıcının temel verilerini al
        try:
            user_data_resp_fallback = supabase.table("users_table").select("events_json, purchased_json").eq("user_id", user_id).execute()
            if user_data_resp_fallback.data:
                profile_fallback = user_data_resp_fallback.data[0]
                clicks_fb = set(safe_json_loads(profile_fallback.get("events_json", "{}"), {}).get("click", []))
                purchases_fb_list = safe_json_loads(profile_fallback.get("purchased_json", "[]"), [])
                purchases_fb = {item["product_id"] for item in purchases_fb_list if "product_id" in item}
                return get_fallback_recommendations(user_id, clicks_fb, purchases_fb, limit)
        except Exception as fallback_e:
             print(f"[GET_RECO] Fallback sırasında da hata: {fallback_e}")
        
        return get_popular_products(limit) # En son çare

def filter_in_stock_products(products: List[Dict]) -> List[Dict]:
    """Stokta olan ürünleri filtreler"""
    if not products:
        return []
    return [p for p in products if p.get("in_stock", False)]

def get_popular_products(limit: int) -> List[Dict]:
    print(f"[POPULAR_PRODUCTS] İstek: limit={limit}")
    limit = validate_limit(limit)
    try:
        response = supabase.table("product_table").select("*").order("total_sales", desc=True).limit(limit).execute()
        products = response.data
        print(f"[POPULAR_PRODUCTS] Sonuç: {len(products) if products else 0} ürün.")
        return products if products else []
    except Exception as e: print(f"[POPULAR_PRODUCTS] Hata: {str(e)}"); return []

def get_popular_products_by_category(category_name: str, limit: int = 15) -> List[Dict]:
    print(f"[POPULAR_BY_CATEGORY] İstek: category_name={category_name}, limit={limit}")
    limit = validate_limit(limit)
    if not category_name: return get_popular_products(limit)
    try:
        response = supabase.table("product_table").select("*").eq("category_name", category_name).order("total_sales", desc=True).limit(limit).execute()
        products = response.data
        print(f"[POPULAR_BY_CATEGORY] Kategori '{category_name}' için {len(products) if products else 0} ürün.")
        if not products: return get_popular_products(limit) # Fallback
        return products
    except Exception as e: print(f"[POPULAR_BY_CATEGORY] Hata: {str(e)}"); return get_popular_products(limit)

def get_bought_together_products(user_id: str, limit: int = 15) -> List[Dict]:
    print(f"[BOUGHT_TOGETHER] İstek: user_id={user_id}, limit={limit}")
    limit = validate_limit(limit)
    if not user_id: return get_popular_products(limit)
    try:
        user_data_resp = supabase.table("users_table").select("events_json").eq("user_id", user_id).execute()
        if not user_data_resp.data: print(f"[BOUGHT_TOGETHER] Kullanıcı {user_id} bulunamadı."); return get_popular_products(limit)
        
        events = safe_json_loads(user_data_resp.data[0].get("events_json", "{}"), {})
        clicked_products = set(events.get("click", []))
        if not clicked_products: print(f"[BOUGHT_TOGETHER] Kullanıcı {user_id} için tıklama verisi yok."); return get_popular_products(limit)
        
        bought_together_ids = set()
        for pid_idx, pid in enumerate(list(clicked_products)[:20]):
             if pid_idx > 0: print(f"[BOUGHT_TOGETHER] {pid_idx}. ürün için bought_together sorgusu (optimizasyon alanı)")
             product_data_resp = supabase.table("product_table").select("bought_together").eq("product_id", pid).execute()
             if product_data_resp.data and product_data_resp.data[0].get("bought_together"):
                 bt_data = product_data_resp.data[0]["bought_together"]
                 if isinstance(bt_data, str): current_bt_ids = safe_json_loads(bt_data, [])
                 elif isinstance(bt_data, list): current_bt_ids = bt_data
                 else: current_bt_ids = []
                 bought_together_ids.update(current_bt_ids)

        if not bought_together_ids: print(f"[BOUGHT_TOGETHER] Birlikte alınan ürün ID'si bulunamadı."); return get_popular_products(limit)
        
        final_bt_ids = list(bought_together_ids - clicked_products)

        if not final_bt_ids: print(f"[BOUGHT_TOGETHER] Filtreleme sonrası ID kalmadı."); return get_popular_products(limit)

        products_resp = supabase.table("product_table").select("*").in_("product_id", final_bt_ids).limit(limit).execute()
        products = products_resp.data
        print(f"[BOUGHT_TOGETHER] Sonuç: {len(products) if products else 0} ürün.")
        return products if products else get_popular_products(limit)
    except Exception as e: print(f"[BOUGHT_TOGETHER] Hata: {str(e)}"); return get_popular_products(limit)

def get_user_popular_products(user_id: str, limit: int = 15) -> List[Dict]:
    print(f"[USER_POPULAR] İstek: user_id={user_id}, limit={limit}")
    limit = validate_limit(limit)
    if not user_id: return get_popular_products(limit)
    try:
        user_data_resp = supabase.table("users_table").select("purchased_json, events_json").eq("user_id", user_id).execute()
        if not user_data_resp.data: print(f"[USER_POPULAR] Kullanıcı {user_id} bulunamadı."); return get_popular_products(limit)
        
        user_profile = user_data_resp.data[0]
        purchases = safe_json_loads(user_profile.get("purchased_json", "[]"), [])
        events = safe_json_loads(user_profile.get("events_json", "{}"), {})
        
        product_ids = {item["product_id"] for item in purchases if "product_id" in item}
        if not product_ids:
            product_ids = set(events.get("click", []))
        
        if not product_ids: print(f"[USER_POPULAR] Kullanıcı {user_id} için etkileşimli ürün ID'si yok."); return get_popular_products(limit)

        category_names = get_user_categories(user_id, set(), product_ids)
        
        if not category_names: print(f"[USER_POPULAR] Etkileşimli ürünler için kategori bulunamadı."); return get_popular_products(limit)
        
        response = supabase.table("product_table").select("*").in_("category_name", category_names).order("total_sales", desc=True).limit(limit).execute()
        products = response.data
        print(f"[USER_POPULAR] Sonuç: {len(products) if products else 0} ürün.")

        if not products: return get_popular_products(limit)
        return products
    except Exception as e: print(f"[USER_POPULAR] Hata: {str(e)}"); return get_popular_products(limit)

# --- Yeni Yardımcı Fonksiyonlar (İşbirlikçi Filtreleme için) ---

def _calculate_jaccard_similarity(set1: Set, set2: Set) -> float:
    """İki küme arasındaki Jaccard benzerliğini hesaplar."""
    if not set1 and not set2:
        return 0.0
    intersection = len(set1.intersection(set2))
    union = len(set1.union(set2))
    return intersection / union if union != 0 else 0.0

def _get_potential_collaborators_data(
    target_user_id: str,
    target_product_ids_set: Set[str],
    interaction_field_name: str, # 'events_json' or 'purchased_json'
    interaction_json_key: str,   # 'click' (for events) or 'product_id' (for purchases)
    is_purchase_field: bool = False
) -> Dict[str, Set[str]]:
    """
    Hedef kullanıcının etkileşimde bulunduğu ürünlerden herhangi biriyle
    etkileşimde bulunmuş potansiyel işbirlikçi kullanıcıların
    tam etkileşim verilerini (tıklama veya satın alma) toplu olarak çeker.
    """
    if not target_product_ids_set:
        return {}

    print(f"[_get_potential_collaborators_data] Kullanıcı: {target_user_id}, Alan: {interaction_field_name}, Hedef ürün sayısı: {len(target_product_ids_set)}")

    collaborators_interaction_map: Dict[str, Set[str]] = defaultdict(set)
    
    # Supabase sorgusu için filtre oluşturma
    # Tek bir büyük sorgu yerine, hedef ürünleri batch'lere bölerek sorgulamak daha iyi olabilir
    # Ancak Supabase Python kütüphanesinin `filter` metoduyla karmaşık OR koşulları veya `contains any`
    # gibi operasyonlar JSON alanları üzerinde doğrudan ve verimli olmayabilir.
    # Şimdilik, her bir hedef ürün için ayrı sorgu yapıp, sonuçları birleştireceğiz.
    # Bu, çok sayıda hedef ürün varsa yavaş olabilir. Optimize edilecek bir alan.
    
    # Alternatif: Önce hedef ürünlerle etkileşime giren kullanıcıları bul, sonra bu kullanıcıların tüm verilerini çek.
    # Bu da Supabase'in JSONB sorgu yeteneklerine bağlı.

    # Şimdilik basit bir yaklaşım: Tüm kullanıcıları çekip Python'da filtrelemek (küçük datasetler için).
    # Daha büyük datasetler için bu optimize edilmeli.
    # Bizim durumumuzda `get_efficient_similar_users` benzeri bir mantık daha iyiydi.
    # O mantığı buraya uyarlayalım: önce ilgili kullanıcıları bul, sonra onların verilerini çek.

    # Şimdilik bu fonksiyonu olduğu gibi bırakıp, `get_recommendations` içinde mantığı düzeltelim.
    # VEYA: Bu fonksiyonu kaldırıp, mantığı doğrudan `get_recommendations` içine gömelim. Bu daha temiz olabilir.
    # Şimdilik bu fonksiyonu kullanmayalım ve mantığı doğrudan `get_recommendations` içine entegre edelim.
    # Bu fonksiyonun konsepti doğruydu ancak Supabase ile verimli implementasyonu karmaşık.

def _calculate_similarity_scores(
    target_user_interactions_set: Set[str],
    all_users_interactions_map: Dict[str, Set[str]], # user_id -> set of their items
    target_user_id: str,
    top_n: int = 50
) -> Dict[str, float]:
    """
    Hedef kullanıcı ile diğer kullanıcılar arasındaki Jaccard benzerlik skorlarını hesaplar.
    """
    if not target_user_interactions_set:
        return {}

    similarity_scores: Dict[str, float] = {}
    for user_id, items_set in all_users_interactions_map.items():
        if user_id == target_user_id:
            continue
        similarity = _calculate_jaccard_similarity(target_user_interactions_set, items_set)
        if similarity > 0: # Sadece pozitif benzerliği olanları al
            similarity_scores[user_id] = similarity
    
    sorted_similar_users = sorted(similarity_scores.items(), key=lambda item: item[1], reverse=True)
    print(f"[_calculate_similarity_scores] En benzer {min(top_n, len(sorted_similar_users))} kullanıcı (max {len(all_users_interactions_map)-1}) arasından seçildi.")
    return dict(sorted_similar_users[:top_n])

def _generate_candidate_item_scores(
    similar_users_with_scores_map: Dict[str, float], # user_id -> jaccard_score
    all_users_interactions_map: Dict[str, Set[str]], # user_id -> set of their items
    exclude_products_set: Set[str]
) -> Dict[str, float]:
    """
    Benzer kullanıcılardan gelen ürün adaylarını, kullanıcıların benzerlik skorlarıyla ağırlıklandırarak puanlar.
    """
    candidate_item_scores: Dict[str, float] = defaultdict(float)
    
    if not similar_users_with_scores_map:
        return {}

    for s_user_id, similarity_score in similar_users_with_scores_map.items():
        s_user_items = all_users_interactions_map.get(s_user_id, set())
        for item_id in s_user_items:
            if item_id not in exclude_products_set:
                candidate_item_scores[item_id] += similarity_score # Benzerlik skoru ile ağırlıklandır

    print(f"[_generate_candidate_item_scores] {len(candidate_item_scores)} adet aday ürün skorlandı.")
    return candidate_item_scores 