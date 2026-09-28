#!/usr/bin/env python3
import os
import sys
import ssl
import re
import urllib.request

try:
    sys.stdout.reconfigure(encoding='utf-8')
except Exception:
    pass

ctx = ssl._create_unverified_context()
HEADERS = {
    'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/122.0.0.0 Safari/537.36',
    'Accept': 'text/html,application/xhtml+xml,application/xml;q=0.9,image/avif,image/webp,image/apng,*/*;q=0.8',
    'Accept-Language': 'tr,en-US;q=0.7,en;q=0.3'
}

KNOWN_FACES_DIR = os.path.abspath(os.path.join(os.path.dirname(__file__), "..", "data", "known_faces"))

PAGES = [
    ("recep_tayyip_erdogan", [
        "https://upload.wikimedia.org/wikipedia/commons/b/bc/Recep_Tayyip_Erdo%C4%9Fan_2025_%28cropped%29.jpg"
    ]),
    ("nesrullah_tanglay", [
        "https://www.haberler.com/nesrullah-tanglay/biyografisi/",
        "https://www.bitlis.bel.tr/baskan/ozgecmis/"
    ]),
    ("erol_karaomeroglu", [
        "https://www.haberler.com/erol-karaomeroglu/biyografisi/"
    ]),
    ("ahmet_karakaya", [
        "https://www.haberler.com/ahmet-karakaya/biyografisi/"
    ]),
    ("batuhan_bingol", [
        "https://www.haberler.com/batuhan-bingol/"
    ]),
    ("yavuz_gulmez", [
        "https://www.haberler.com/yavuz-gulmez/"
    ])
]

def extract_image_url_from_html(page_url: str) -> list[str]:
    img_candidates = []
    try:
        req = urllib.request.Request(page_url, headers=HEADERS)
        with urllib.request.urlopen(req, context=ctx, timeout=8) as resp:
            html = resp.read().decode('utf-8', errors='ignore')
            # 1. og:image or twitter:image
            for pattern in [
                r'property=["\']og:image["\']\s+content=["\']([^"\']+)["\']',
                r'name=["\']twitter:image["\']\s+content=["\']([^"\']+)["\']',
                r'content=["\']([^"\']+)["\']\s+property=["\']og:image["\']',
                r'<img[^>]+src=["\']([^"\']+\.(?:jpg|jpeg|png))["\']'
            ]:
                for match in re.findall(pattern, html, re.IGNORECASE):
                    if match.startswith("//"):
                        match = "https:" + match
                    elif match.startswith("/"):
                        match = urllib.parse.urljoin(page_url, match)
                    if match.startswith("http") and not any(x in match.lower() for x in ["logo", "icon", "blank", "svg"]):
                        img_candidates.append(match)
    except Exception as e:
        print(f"⚠️ Sayfa okuma hatası ({page_url}): {e}")
    return img_candidates

def main():
    os.makedirs(KNOWN_FACES_DIR, exist_ok=True)
    print("🚀 Yetkili portre fotoğrafları taranıyor ve bilinen yüzler dizinine kaydediliyor...\n")

    for slug, sources in PAGES:
        person_dir = os.path.join(KNOWN_FACES_DIR, slug)
        os.makedirs(person_dir, exist_ok=True)
        dest_path = os.path.join(person_dir, f"{slug}.jpg")

        print(f"🔍 [{slug}] için taranıyor...")
        direct_images = []
        for src in sources:
            if src.endswith(".jpg") or src.endswith(".png"):
                direct_images.append(src)
            else:
                found = extract_image_url_from_html(src)
                direct_images.extend(found)

        saved = False
        for img_url in direct_images:
            try:
                print(f"   📥 İndiriliyor: {img_url[:70]}...")
                req = urllib.request.Request(img_url, headers=HEADERS)
                with urllib.request.urlopen(req, context=ctx, timeout=8) as r:
                    content = r.read()
                    if len(content) > 3000:
                        with open(dest_path, "wb") as f:
                            f.write(content)
                        print(f"   ✅ Başarıyla kaydedildi: {dest_path} ({len(content)//1024} KB)")
                        saved = True
                        break
            except Exception as e:
                print(f"   ⚠️ İndirme başarısız ({img_url[:40]}...): {e}")

        if not saved:
            print(f"   ❌ {slug} için uygun fotoğraf bulunamadı.")
        print("-" * 50)

if __name__ == "__main__":
    main()
