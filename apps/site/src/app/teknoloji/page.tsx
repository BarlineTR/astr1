import { SayfaKabuk } from "@/components/SayfaKabuk";
import { TeknikTablo } from "@/components/TeknikTablo";

export const metadata = {
  title: "Teknoloji",
  description:
    "Algı, sosyal bakış ve güvenlik katmanları — her iddianın ölçüm kaynağıyla birlikte.",
};

/**
 * Teknoloji sayfası.
 *
 * Her bölümün yanında değerin nereden geldiği yazılı. Bu depoda kural bu:
 * bir performans ya da davranış iddiası yapılırken sayının kaynağı da yazılır.
 */
const BOLUMLER = [
  {
    id: "algi",
    baslik: "Algı",
    govde: [
      "Derinlik kamerası kafanın önünde durur ve kafayla birlikte döner. Yüz tespiti kameranın kendi işlemcisinde çalışır; ana bilgisayara yalnızca sonuç ulaşır.",
      "Dört mikrofon dairesel bir dizi oluşturur ve sesin geliş yönü mikrofon kartının kendi işlemcisinde hesaplanır. Yön, kafanın o anki açısıyla birleştirilerek gövde çerçevesine taşınır.",
    ],
    olcum:
      "Algı 30 Hz, kontrol 50 Hz. Yüklü karenin işlenmesi ~13 ms; 30 Hz bütçesi 33 ms.",
  },
  {
    id: "bakis",
    baslik: "Sosyal bakış",
    govde: [
      "Kafa nereye bakacağına görüntü ile sesi birlikte değerlendirerek karar verir. Yüz görünürken kerteriz yalnızca görüntüden gelir.",
      "Füzyon iki kaynağı ortalamıyor: ortalama alındığında ses yönündeki gürültü hedefi ölü bandın ötesine itiyor ve kafa boşuna oynuyordu. Ses kime bakılacağına karar verir, nereye bakılacağına değil.",
    ],
    olcum:
      "Ortalama alan füzyonun ürettiği sapma ölçüldü: 5,1°. Hedef edinme eşiği 0,75, kilidi koruma eşiği 0,40.",
  },
  {
    id: "guvenlik",
    baslik: "Güvenlik katmanları",
    govde: [
      "Hareket sınırları firmware katmanında zorlanır. Üst katmanların hepsi aynı sınırı ayrıca uygular ama güvenliği sağlayan katman en alttakidir.",
      "Bağlantı koptuğunda motor çıkışları donanım zamanlayıcısıyla durur; bunun için üst katmanın çalışıyor olması gerekmez.",
    ],
    olcum: "Firmware heartbeat penceresi 500 ms. Kafa ölü bandı 3 tick (1,16°), dişli boşluğu 0,85°.",
  },
  {
    id: "mimari",
    baslik: "Açık mimari",
    govde: [
      "ROS 2 üzerine kurulu modüler yapı; bileşenler tek tek değiştirilebilir ve yeni yetenekler eklenebilir.",
      "Kalibrasyon değerleri, ölçüm yöntemleri ve kaynak kodun tamamı genel depoda açık olarak yayımlanır.",
    ],
    olcum: "Telemetri sözleşmesi tek bir modülde tanımlı ve sürümlü.",
  },
] as const;

export default function TeknolojiSayfasi() {
  return (
    <SayfaKabuk
      current="teknoloji"
      ustBaslik="Nasıl çalışıyor"
      baslik="Teknoloji"
      lead="Algıdan harekete kadar her katman — ve her sayının nereden geldiği."
    >
      {BOLUMLER.map((b, i) => (
        <section className="section" id={b.id} key={b.id}>
          <div className="page">
            <div className="section__head">
              <div className="section__index">{String(i + 1).padStart(2, "0")}</div>
              <div>
                <h2>{b.baslik}</h2>
                {b.govde.map((p) => (
                  <p className="section__lead" key={p}>
                    {p}
                  </p>
                ))}
                <p className="olcum-notu">
                  <span className="eyebrow">Ölçüm</span>
                  {b.olcum}
                </p>
              </div>
            </div>
          </div>
        </section>
      ))}

      <section className="section">
        <div className="page">
          <div className="section__head">
            <div>
              <h2>Çalışma değerleri</h2>
            </div>
          </div>
          <TeknikTablo />
        </div>
      </section>
    </SayfaKabuk>
  );
}
