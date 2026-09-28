import os
import sys
import ssl
import urllib.request
import urllib.error

try:
    sys.stdout.reconfigure(encoding='utf-8')
except Exception:
    pass

# Bypass local SSL verification
ssl_ctx = ssl._create_unverified_context()

KNOWN_FACES_DIR = os.path.abspath(os.path.join(os.path.dirname(__file__), "..", "data", "known_faces"))

OFFICIALS_IMAGES = {
    "recep_tayyip_erdogan": [
        "https://upload.wikimedia.org/wikipedia/commons/thumb/e/ef/Recep_Tayyip_Erdo%C4%9Fan_in_2023.jpg/600px-Recep_Tayyip_Erdo%C4%9Fan_in_2023.jpg",
        "https://upload.wikimedia.org/wikipedia/commons/e/ef/Recep_Tayyip_Erdo%C4%9Fan_in_2023.jpg"
    ],
    "ahmet_karakaya": [
        "https://img.internethaber.com/rcman/Cw1280h720q95gc/storage/files/images/2024/09/19/ahmet-karakaya-kimdir-kac-yasinda-nereli-bitlis-valisi-ahmet-karakaya-hangi-gorevlerde-bulundu-k2Z8_cover.jpg",
        "https://images.haberturk.com/2024/09/19/ver1726725287/ahmet-karakaya-kimdir-kac-yasinda-nereli-ve-hangi-gorevlerde-bulundu-bitlis-valisi-ahmet-karakaya-hayati-ve-biyografisi_3722744_640x360.jpg"
    ],
    "erol_karaomeroglu": [
        "https://img.internethaber.com/rcman/Cw1280h720q95gc/storage/files/images/2023/08/10/erol-karaomeroglu-bitlis-valisi-kimdir-kac-yasinda-nereli-evli-mi-ve-hangi-gorevlerde-bulundu-erol-karaomeroglu-biyografisi-ve-hayati-1z3g_cover.jpg",
        "https://images.haberturk.com/2023/08/10/ver1691650395/3613617_810x458.jpg"
    ],
    "nesrullah_tanglay": [
        "https://img.internethaber.com/rcman/Cw1280h720q95gc/storage/files/images/2024/02/09/nesrullah-tanglay-kimdir-ak-parti-bitlis-belediye-baskan-adayi-nesrullah-tanglay-kac-yasinda-nereli-ne-is-yapiyor-h6Wj_cover.jpg",
        "https://images.haberturk.com/2024/02/09/ver1707471206/3659223_810x458.jpg"
    ],
    "batuhan_bingol": [
        "https://img.internethaber.com/rcman/Cw1280h720q95gc/storage/files/images/2023/08/24/batuhan-bingol-kimdir-kac-yasinda-nereli-ahlat-kaymakami-batuhan-bingol-hangi-gorevlerde-bulundu-Uu0e_cover.jpg",
        "https://haberarastirma.com/wp-content/uploads/2023/08/batuhan-bingol-kimdir.jpg"
    ],
    "yavuz_gulmez": [
        "https://img.internethaber.com/rcman/Cw1280h720q95gc/storage/files/images/2024/04/01/ahlat-belediye-baskani-yavuz-gulmez-kimdir-kac-yasinda-nereli-yavuz-gulmez-biyografisi-ve-hayati-Yd1D_cover.jpg",
        "https://images.haberturk.com/2024/04/01/ver1711956108/3674681_810x458.jpg"
    ]
}

def download_portraits():
    os.makedirs(KNOWN_FACES_DIR, exist_ok=True)
    headers = {
        "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36",
        "Accept": "image/webp,image/apng,image/*,*/*;q=0.8"
    }

    success_count = 0
    for official_slug, urls in OFFICIALS_IMAGES.items():
        person_dir = os.path.join(KNOWN_FACES_DIR, official_slug)
        os.makedirs(person_dir, exist_ok=True)
        dest_path = os.path.join(person_dir, f"{official_slug}.jpg")

        downloaded = False
        for url in urls:
            try:
                print(f"📥 İndiriliyor: [{official_slug}] <- {url[:60]}...")
                req = urllib.request.Request(url, headers=headers)
                with urllib.request.urlopen(req, timeout=8.0, context=ssl_ctx) as resp:
                    if resp.status == 200:
                        content = resp.read()
                        if len(content) > 2048:  # valid image > 2KB
                            with open(dest_path, "wb") as f:
                                f.write(content)
                            print(f"✅ Başarılı: {dest_path} ({len(content) // 1024} KB)")
                            downloaded = True
                            success_count += 1
                            break
            except Exception as e:
                print(f"⚠️ Hata ({url[:45]}...): {e}")

        if not downloaded:
            print(f"❌ {official_slug} için fotoğraf indirilemedi.")

    print(f"\n🎉 Toplam {success_count}/{len(OFFICIALS_IMAGES)} yetkili fotoğrafı başarıyla kaydedildi!")

if __name__ == "__main__":
    download_portraits()
