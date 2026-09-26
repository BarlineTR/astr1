# Açık riskler

Yayına çıkmadan kapatılması gereken maddeler. Her madde bir çıkış koşuluna bağlıdır;
koşul sağlanmadan o faz yayına alınmaz.

## R1 — Giriş sahnesindeki model marka ihlali riski taşıyor

**Durum:** açık
**Çıkış koşulu:** Faz 3 (ödeme) yayına çıkmadan önce kapatılmalı
**Dosya:** `apps/site/public/models/astro-hero.glb`
**Kod:** `apps/site/src/scene/robot-model.ts` → `HERO_MODEL`

`astro-hero.glb` ASTRO'nun kendisi değil, bir R2-D2 oyuncağının fotogrametri
taramasıdır. R2-D2 Lucasfilm'in tescilli markasıdır. Tanıtım amaçlı bir geliştirme
sitesinde durması kabul edilmiş bir risktir; **para alan, herkese açık bir ticari
sitede durması değildir.**

Gerçek ASTRO taraması henüz yapılmadığı için model geliştirme boyunca yerinde kalıyor
(tasarım belgesi D12). Tarama geldiğinde değiştirilecek yer tek dosyadır:
`apps/site/src/scene/robot-model.ts` içindeki `HERO_MODEL` sabiti.

Model değişirse kubbe dikiş yüksekliği yeniden ölçülmelidir — tek parça taranmış bir
modelde kubbe ayrı bir nesne değildir ve `robot-model.ts` üçgenleri ölçülmüş bir
yükseklikte ikiye ayırır:

```bash
python3 scripts/measure-model-seam.py apps/site/public/models/astro-hero.glb
```

## R2 — Hukuki metinler yer tutucudur

**Durum:** açık
**Çıkış koşulu:** Faz 3 (ödeme) yayına çıkmadan önce kapatılmalı

KVKK aydınlatma metni, gizlilik politikası, çerez politikası, kullanım koşulları,
mesafeli satış sözleşmesi ve iade koşulları kodda yer tutucu olarak duruyor ve
sayfada yer tutucu olduğu açıkça yazıyor. **Hukukçu onayından geçmeden para alınamaz.**

## R3 — Kurum bilgileri yer tutucudur

**Durum:** açık
**Çıkış koşulu:** Faz 3 (ödeme) yayına çıkmadan önce kapatılmalı
**Dosya:** `apps/site/src/data/kurum.ts` (ayrıca `kurumsal.ts` — yönetim ve basın listeleri boş)

Ticari unvan, vergi numarası, adres, telefon ve ETBİS kaydı gerçek değil. iyzico
başvurusu ve hukuki sayfalar bunlar olmadan tamamlanamaz. Bütün yer tutucular tek
modülde ve `YER_TUTUCU` sabitiyle işaretli.

## R4 — Fiyatlar uydurmadır

**Durum:** açık
**Çıkış koşulu:** Faz 3a yayına çıkmadan önce kapatılmalı

Destek paketi tutarları ve abonelik planları geliştirme için uydurulmuş değerlerdir,
kodda `GELISTIRME_FIYATI` ile işaretlidir. Gerçek fiyat listesi gelmeden ödeme akışı
yayına alınmaz.

---

## Durum özeti (2026-09-26)

| Risk | Durum | Neyi engelliyor |
|---|---|---|
| R1 — model marka riski | açık | Ödeme fazının yayına çıkması |
| R2 — hukuki metinler taslak | açık | Ödeme fazının yayına çıkması |
| R3 — kurum bilgileri yer tutucu | açık | iyzico başvurusu, hukuki sayfalar |
| R4 — fiyatlar uydurma | açık | Ödeme akışının yayına çıkması |

Dördü de **kod tarafında hazır**: değişecek yerler tek modüllerde toplandı ve
sayfalar yer tutucu olduklarını kendileri söylüyor. Gerçek bilgi geldiğinde
yapılacak iş, bu dosyaları doldurup bayrakları kapatmaktan ibaret.
