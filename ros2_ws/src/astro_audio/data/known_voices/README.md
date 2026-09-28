# ASTRO V1 — Bilinen Ses İzi Dizini (Known Voices)

Bu dizin, robotun akustik ses izi (Speaker Voiceprint) tanıma sistemi için ses veri tabanıdır.

## 📁 Çalışma Şekli
- Kullanıcı konuştuğunda sesin temel frekansı ($F_0$ Pitch), MFCC'leri ve spektral öznitelikleri çıkarılır.
- Tanımlı profiller (`baran.npy`, `erol_karaomeroglu.npy` vb.) ile eşleştirilerek kişi **yalnızca sesinden** tanınabilir.
- Kullanıcı *"Benim adım Selim, sesimi kaydet"* dediğinde anlık ses izi buraya otomatik kaydedilir.
