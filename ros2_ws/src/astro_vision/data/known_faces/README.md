# ASTRO V1 — Bilinen Yüzler Dizini (Known Faces)

Bu dizin, robotun yüz tanıma (Face ID) sistemi için fotoğraf veri tabanıdır.

## 📁 Klasör Yapısı ve Fotoğraf Ekleme

Her kişi için bir alt klasör oluşturup içine o kişinin fotoğraflarını (.jpg, .jpeg, .png) ekleyebilirsiniz:

```
known_faces/
├── erol_karaomeroglu/          # Bitlis Valisi
│   ├── vali_1.jpg
│   └── vali_2.jpg
├── nesrullah_tanglay/          # Bitlis Belediye Başkanı
│   ├── baskan_1.jpg
│   └── baskan_2.jpg
├── batuhan_bingol/             # Ahlat Kaymakamı
│   └── kaymakam_1.jpg
├── yavuz_gulmez/               # Ahlat Belediye Başkanı
│   └── baskan_ahlat_1.jpg
├── recep_tayyip_erdogan/       # Cumhurbaşkanı
│   └── erdogan_1.jpg
└── baran/                      # Robotun Geliştiricisi / Baş Mühendisi
    ├── baran_1.jpg
    └── baran_2.jpg
```

Veya doğrudan ana klasöre `Erol_Karaomeroglu.jpg`, `Baran.jpg` şeklinde tekil fotoğraf da koyabilirsiniz.

## ⚡ Çalışma Şekli
- Robot açıldığında bu klasördeki tüm fotoğrafları tarar ve yüz özniteliklerini (112x112 spatial embedding) önbelleğe alır.
- Kamera karşısına bu kişilerden biri geçtiğinde robot kişiyi **adıyla ve resmi makam unvanıyla** (*"Sayın Valim"*, *"Sayın Başkanım"*) tanır ve protokol kurallarına göre karşılar.
- Ayrıca konuşma esnasında *"Benim adım Ahmet, beni tanı"* dediğinizde o anki kamera görüntüsü bu klasöre otomatik kaydedilir.
