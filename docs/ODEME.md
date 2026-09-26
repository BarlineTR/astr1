# Ödeme altyapısı

Sağlayıcıdan bağımsız bir katman ve onun arkasında iyzico. Kod hiçbir yerde
`iyzipay`i doğrudan çağırmaz; yalnızca `OdemeSaglayici` arayüzünü çağırır
(tasarım belgesi §9). Uluslararası tahsilat kararı ertelendiği için — Stripe
Türkiye'ye merchant hesabı vermiyor — ikinci bir sağlayıcı eklemek tek dosya
olmalı.

## Akış

```
panel ──satinAl()──> siparis (bekliyor) ──> saglayici.odemeBaslat()
                                                    │
                          kullanıcı iyzico sayfasında öder (3D Secure orada)
                                                    │
  iyzico ──POST token──> /api/odeme/geri-donus ──> saglayici.sonucuAl()
                                                    │
                                     sipariş: odendi | basarisiz
```

**Güvenin dayandığı yer sonucu alma adımı.** Geri dönüşte iyzico bize yalnızca
`token` gönderiyor; sonucu kendi API anahtarlarımızla ayrıca soruyoruz. Bu
yüzden sahte bir geri dönüş isteği başarılı bir ödeme uyduramaz.

**Kart bilgisi hiçbir zaman bizim sunucumuza uğramaz.** Checkout Form akışında
kartı iyzico kendi sayfasında topluyor.

## Kararlar

- **Tutarlar tam sayı kuruş.** iyzico ondalık *dizgi* istiyor (`"199.90"`) ve
  sepet kalemlerinin toplamı beyan edilen tutara **birebir** eşit olmak zorunda;
  bir kuruşluk fark isteği tamamen reddettiriyor. Dönüşüm ve eşitlik kontrolü
  `lib/odeme/tutar.ts` içinde, testleriyle birlikte. `Intl` kullanılmıyor:
  Türkçe yerelde virgül üretip isteği bozardı.
- **Ürünler tabloda değil kodda** (`data/fiyatlar.ts`). Sabit ve kısa bir liste;
  tablo olsaydı kimsenin kullanmayacağı bir yönetim ekranı gerekirdi. Ama ad ve
  fiyat siparişe **kopyalanıyor**: fiyat sonradan değişince eski siparişin
  tutarı değişmemeli.
- **Fiyat istemciden gelmiyor.** Forma yalnızca ürün slug'ı konuyor; tutar
  sunucudaki listeden okunuyor. Fiyatı istemcinin göndermesi, tutarı değiştirip
  bir kuruşa satın almaya izin verirdi.
- **Sipariş sağlayıcıya gitmeden önce yazılıyor.** Sağlayıcı çağrısı başarılı
  olup yanıtı bize ulaşmadan koparsa, kullanıcı ödemiş ama bizde hiçbir kayıt
  yok olurdu. Önce `bekliyor` yazmak, en kötü durumda ödenmemiş bir sipariş
  satırı bırakır — onarılabilir bir durum.
- **Sonuç işleme idempotent.** Aynı sonuç iki kez gelebilir: geri dönüş,
  kullanıcının sayfayı yenilemesi, ileride webhook. Tekillik veritabanında
  zorlanıyor (`payments.provider_payment_id`), kodda "önce bak sonra yaz" ile
  değil: iki istek aynı anda geldiğinde o kontrol ikisini de geçiriyordu.
- **Tutar doğrulanıyor.** Sağlayıcının söylediği tutar siparişinkiyle tutmuyorsa
  ödeme başarılı sayılmıyor. Farkı sessizce kabul etmek, eksik ödenmiş bir
  siparişi tamamlanmış göstermek demek.
- **Ödenmiş sipariş geri alınmıyor.** Geç gelen bir "başarısız" bildirimi
  tamamlanmış siparişi bozmamalı.
- **Durum tarayıcının dönüşüne bağlı değil.** Kullanıcı ödeme sonrası sekmeyi
  kapatsa da sipariş tamamlanır.

## Anahtarsız çalışma

`IYZICO_API_KEY` ve `IYZICO_SECRET_KEY` boşken **sahte sağlayıcı** kullanılır:
bütün sipariş yaşam döngüsü (oluşturma, yönlendirme, sonuç, idempotensi) uçtan
uca koşar ama para hareket etmez. Anahtar gerektiren bir akış CI'da hiç
sınanamazdı.

Sahteye düşme **sessiz değil**: panelde hangi sağlayıcının bağlı olduğu
yazıyor. Yanlışlıkla sahte sağlayıcıyla yayına çıkmak, paranın hiç tahsil
edilmemesi demek.

Sahte sağlayıcı gerçeğiyle **aynı doğrulamaları** yapar (sepet toplamı dahil) ki
sahtede geçip gerçekte patlayan bir hata olmasın.

## iyzico'yu bağlamak

1. https://sandbox-merchant.iyzipay.com/auth/register adresinden sandbox hesabı
   açın (herkese açık sandbox anahtarı yok, her satıcı kendi hesabını alır).
2. Ayarlar → Merchant Ayarları → API Anahtarları.
3. `apps/site/.env.local` içine yazın:

```
IYZICO_API_KEY=sandbox-...
IYZICO_SECRET_KEY=sandbox-...
IYZICO_URI=https://sandbox-api.iyzipay.com
```

Sunucuyu yeniden başlatın; panel artık "iyzico üzerinden" diyecek ve satın alma
iyzico'nun kendi sayfasına yönlendirecek. Sandbox'ta OTP sabit: **123456**.
Test kartları: https://docs.iyzico.com/en/add-ons/test-cards

Canlıya geçerken `IYZICO_URI` `https://api.iyzipay.com` olur. **Canlı hesap
tüzel kişilik ister** — kurum bilgileri (`docs/RISKLER.md` R3) tamamlanmadan
canlı başvuru yapılamaz.

## Henüz yapılmayanlar

- **Tekrarlayan tahsilat.** Abonelik planı şu an tek seferlik ödeme olarak
  alınıyor. iyzico'nun Abonelik API'si ayrı bir ürün ve hesapta ayrıca
  etkinleştirilmesi gerekiyor.
- **Webhook.** Geri dönüş yeterli çalışıyor; webhook ikinci bir güvence olarak
  eklenecek. `webhook_events` tablosu ve idempotensi anahtarı hazır.
- **İade.** `OdemeSaglayici` arayüzüne eklenecek.
- **Resmî fatura.** e-Fatura/e-Arşiv entegrasyonu kurum bilgileri geldikten
  sonra.
