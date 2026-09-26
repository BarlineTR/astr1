/**
 * `iyzipay` paketi için yerel tip bildirimi.
 *
 * `@types/iyzipay` kullanılmıyor çünkü Checkout Form'u yanlış tanımlıyor:
 * `checkoutFormInitialize.create` için 3D Secure isteği tipi (`paymentCard`,
 * `shippingAddress`, `installments` zorunlu) bekliyor. Oysa Checkout Form'un
 * bütün anlamı kart bilgisinin bize hiç uğramaması — o alanları göndermek
 * yanlış olurdu.
 *
 * Burada yalnızca gerçekten kullandığımız yüzey bildirildi. Paket büyüyünce bu
 * dosya da büyümemeli: kullanılmayan uçları tiplemek, doğruluğunu kimsenin
 * denetlemediği bir yük demek.
 */
declare module "iyzipay" {
  interface IyzipayAyar {
    apiKey: string;
    secretKey: string;
    uri: string;
  }

  interface CheckoutFormBaslatIstek {
    locale: string;
    conversationId: string;
    price: string;
    paidPrice: string;
    currency: string;
    basketId: string;
    paymentGroup: string;
    callbackUrl: string;
    enabledInstallments: number[];
    buyer: Record<string, string>;
    billingAddress: Record<string, string>;
    shippingAddress?: Record<string, string>;
    basketItems: Array<Record<string, string>>;
  }

  /**
   * Yanıt alanları isteğe bağlı bırakıldı: iyzico hata durumunda çoğunu hiç
   * göndermiyor ve zorunlu tiplemek, olmayan alana güvenmek demek.
   *
   * `paidPrice` hem dizgi hem sayı gelebiliyor; ikisini de karşılamak zorundayız.
   */
  interface IyzicoYanit {
    status?: string;
    errorMessage?: string;
    errorCode?: string;
    token?: string;
    paymentPageUrl?: string;
    paymentStatus?: string;
    paymentId?: string;
    price?: string | number;
    paidPrice?: string | number;
    currency?: string;
    conversationId?: string;
    cardFamily?: string;
    lastFourDigits?: string;
    fraudStatus?: number;
    [alan: string]: unknown;
  }

  type GeriCagir = (hata: Error | null, sonuc: IyzicoYanit) => void;

  class Iyzipay {
    constructor(ayar: IyzipayAyar);

    checkoutFormInitialize: {
      create(istek: CheckoutFormBaslatIstek, geriCagir: GeriCagir): void;
    };

    checkoutForm: {
      retrieve(istek: { locale: string; token: string }, geriCagir: GeriCagir): void;
    };

    static LOCALE: { TR: string; EN: string };
    static CURRENCY: { TRY: string; EUR: string; USD: string };
    static PAYMENT_GROUP: { PRODUCT: string; LISTING: string; SUBSCRIPTION: string };
    static BASKET_ITEM_TYPE: { PHYSICAL: string; VIRTUAL: string };
  }

  namespace Iyzipay {
    export type Yanit = IyzicoYanit;
  }

  export = Iyzipay;
}
