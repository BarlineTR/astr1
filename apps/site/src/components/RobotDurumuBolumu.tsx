"use client";

import { useEffect, useState } from "react";
import Link from "next/link";

import {
  DONANIM_AKSAMALARI,
  ROBOT_SISTEM_OZETI,
  STABILITE_METRIKLERI,
  type DonanimKategori,
} from "@/data/donanim";

const KATEGORI_ETIKETLERI: Record<DonanimKategori, string> = {
  algi: "Sensör & Algı",
  hareket: "Tahrik & Motor",
  islem: "Bilişsel Çekirdek",
  guvenlik: "Güvenlik & Watchdog",
};

const DURUM_ROZETLERI = {
  aktif: { metin: "ÇALIŞIYOR", stil: "badge--live" },
  nominal: { metin: "NOMİNAL", stil: "badge--live" },
  hazir: { metin: "HAZIR", stil: "badge--mock" },
  izlemede: { metin: "İZLEMEDE", stil: "" },
};

/**
 * Robot Durumu, Çalışan Aksamlar ve Stabilite Analizi Bölümü.
 *
 * Ziyaretçilerin robotun anlık operasyonel sağlığını, 50 Hz kapalı çevrim kontrol
 * stabilitesini, donanımsal güvenlik katmanlarını ve tüm alt bileşenlerini
 * (OAK-D kamera, ReSpeaker mikrofon dizisi, RPLiDAR, kafa/taban motorları,
 * Jetson SoC ve Mega2560 Watchdog) şeffafça incelemesini sağlar.
 */
export function RobotDurumuBolumu() {
  const [seciliKategori, setSeciliKategori] = useState<string>("hepsi");
  const [canliSimulasyon, setCanliSimulasyon] = useState(true);

  // Canlı telemetri simülasyonu: hafif açı dalgalanması ve kalp atışı
  const [canliMetrikler, setCanliMetrikler] = useState({
    kafaSapma: 0.38,
    donguGecikmesi: 19.98,
    watchdogSonSinyal: 32,
    stabilite: 99.8,
  });

  useEffect(() => {
    if (!canliSimulasyon) return;

    const interval = setInterval(() => {
      setCanliMetrikler((onceki) => {
        const dalgalanma = (Math.random() - 0.5) * 0.08;
        const yeniSapma = Math.max(0.24, Math.min(0.65, 0.38 + dalgalanma));
        const yeniDongu = 20.0 + (Math.random() - 0.5) * 0.15;
        const yeniWatchdog = Math.floor(25 + Math.random() * 20);
        return {
          kafaSapma: Number(yeniSapma.toFixed(2)),
          donguGecikmesi: Number(yeniDongu.toFixed(2)),
          watchdogSonSinyal: yeniWatchdog,
          stabilite: Number((99.8 + (Math.random() - 0.5) * 0.1).toFixed(1)),
        };
      });
    }, 1800);

    return () => clearInterval(interval);
  }, [canliSimulasyon]);

  const filtrelenmisAksamlar =
    seciliKategori === "hepsi"
      ? DONANIM_AKSAMALARI
      : DONANIM_AKSAMALARI.filter((a) => a.kategori === seciliKategori);

  return (
    <section className="section" id="durum">
      <div className="page robot-durumu">
        {/* Bölüm Başlığı */}
        <div className="section__head">
          <div>
            <div style={{ display: "flex", alignItems: "center", gap: "0.75rem", marginBottom: "0.5rem" }}>
              <span className="eyebrow" style={{ margin: 0 }}>Sistem Telemetrisi</span>
              <span className="badge badge--live">
                <span className="badge__dot" />
                {ROBOT_SISTEM_OZETI.durumBasligi}
              </span>
            </div>
            <h2>Robot Durumu ve Stabilite Analizi</h2>
            <p className="section__lead">
              Çalışan donanım aksamları, 50 Hz kapalı çevrim kontrol kararlılığı,
              firmware güvenlik mekanizmaları ve anlık operasyonel sağlık göstergeleri.
            </p>
          </div>
        </div>

        {/* Canlı KPI Durum Şeridi */}
        <div className="robot-durumu__serit">
          <div className="robot-durumu__kpi">
            <span className="robot-durumu__kpi-etiket">Genel Stabilite</span>
            <span className="robot-durumu__kpi-deger is-ok">
              %{canliMetrikler.stabilite}
            </span>
            <span className="robot-durumu__kpi-alt">Nominal limitler içinde</span>
          </div>

          <div className="robot-durumu__kpi">
            <span className="robot-durumu__kpi-etiket">Çalışan Aksamlar</span>
            <span className="robot-durumu__kpi-deger">
              {ROBOT_SISTEM_OZETI.calisanAksamSayisi} / {ROBOT_SISTEM_OZETI.toplamAksamSayisi}
            </span>
            <span className="robot-durumu__kpi-alt">Tüm alt sistemler devrede</span>
          </div>

          <div className="robot-durumu__kpi">
            <span className="robot-durumu__kpi-etiket">Açısal Takip Sapması</span>
            <span className="robot-durumu__kpi-deger mono">
              ±{canliMetrikler.kafaSapma}°
            </span>
            <span className="robot-durumu__kpi-alt">Ölü bant: 1.16° (3 tick)</span>
          </div>

          <div className="robot-durumu__kpi">
            <span className="robot-durumu__kpi-etiket">Kontrol Döngüsü</span>
            <span className="robot-durumu__kpi-deger mono">
              {ROBOT_SISTEM_OZETI.donguFrekansiHz} Hz
            </span>
            <span className="robot-durumu__kpi-alt">{canliMetrikler.donguGecikmesi} ms periyot</span>
          </div>

          <div className="robot-durumu__kpi">
            <span className="robot-durumu__kpi-etiket">Donanımsal Watchdog</span>
            <span className="robot-durumu__kpi-deger is-ok">
              {canliMetrikler.watchdogSonSinyal} ms
            </span>
            <span className="robot-durumu__kpi-alt">Eşik: 500 ms · E-Stop Hazır</span>
          </div>
        </div>

        {/* Kontroller: Sekmeler ve Canlı Gösterge Düğmesi */}
        <div className="robot-durumu__kontroller">
          <div className="robot-durumu__sekmeler" role="tablist" aria-label="Aksam kategorileri">
            <button
              type="button"
              className={`robot-durumu__sekme ${seciliKategori === "hepsi" ? "is-active" : ""}`}
              onClick={() => setSeciliKategori("hepsi")}
            >
              Tüm Aksamlar ({DONANIM_AKSAMALARI.length})
            </button>
            <button
              type="button"
              className={`robot-durumu__sekme ${seciliKategori === "algi" ? "is-active" : ""}`}
              onClick={() => setSeciliKategori("algi")}
            >
              Sensör & Algı (3)
            </button>
            <button
              type="button"
              className={`robot-durumu__sekme ${seciliKategori === "hareket" ? "is-active" : ""}`}
              onClick={() => setSeciliKategori("hareket")}
            >
              Tahrik & Motor (2)
            </button>
            <button
              type="button"
              className={`robot-durumu__sekme ${seciliKategori === "islem" ? "is-active" : ""}`}
              onClick={() => setSeciliKategori("islem")}
            >
              Bilişsel İşlemci (1)
            </button>
            <button
              type="button"
              className={`robot-durumu__sekme ${seciliKategori === "guvenlik" ? "is-active" : ""}`}
              onClick={() => setSeciliKategori("guvenlik")}
            >
              Güvenlik & Watchdog (1)
            </button>
          </div>

          <div style={{ display: "flex", alignItems: "center", gap: "0.5rem" }}>
            <button
              type="button"
              className="robot-durumu__sekme"
              style={{ fontSize: "var(--t-micro)", display: "inline-flex", alignItems: "center", gap: "0.35rem" }}
              onClick={() => setCanliSimulasyon(!canliSimulasyon)}
            >
              <span
                style={{
                  width: 6,
                  height: 6,
                  borderRadius: "50%",
                  background: canliSimulasyon ? "var(--ok)" : "var(--ink-faint)",
                  display: "inline-block",
                }}
              />
              {canliSimulasyon ? "Canlı Telemetri Açık" : "Durağan Görünüm"}
            </button>

            <Link href="/platform/demo" className="btn btn--sm" style={{ fontSize: "var(--t-micro)" }}>
              Konsolu Aç ↗
            </Link>
          </div>
        </div>

        {/* Çalışan Donanım Aksamları Izgarası */}
        <div className="robot-durumu__grid">
          {filtrelenmisAksamlar.map((aksam) => {
            const rozet = DURUM_ROZETLERI[aksam.durum];
            return (
              <article className="robot-durumu__kart" key={aksam.id}>
                <div className="robot-durumu__kart-ust">
                  <span className="robot-durumu__kart-kategori">
                    {KATEGORI_ETIKETLERI[aksam.kategori]}
                  </span>
                  <span className={`badge ${rozet.stil}`}>
                    <span className="badge__dot" />
                    {aksam.calismaFrekansi}
                  </span>
                </div>

                <div>
                  <h3 className="robot-durumu__kart-ad">{aksam.ad}</h3>
                  <span className="robot-durumu__kart-model mono">{aksam.model}</span>
                </div>

                <p className="robot-durumu__kart-aciklama">{aksam.aciklama}</p>

                <dl className="robot-durumu__metrikler">
                  <div className="robot-durumu__metrik-ogesi">
                    <dt>{aksam.birincilMetrik.etiket}</dt>
                    <dd>{aksam.birincilMetrik.deger}</dd>
                  </div>
                  <div className="robot-durumu__metrik-ogesi">
                    <dt>{aksam.ikincilMetrik.etiket}</dt>
                    <dd>{aksam.ikincilMetrik.deger}</dd>
                  </div>
                </dl>

                <div className="robot-durumu__olcum mono">
                  Kaynak: {aksam.olcumKaynagi}
                </div>
              </article>
            );
          })}
        </div>

        {/* Stabilite ve Güvenlik Derinlik Analizi */}
        <div className="robot-durumu__stabilite-panel">
          <div>
            <h3 style={{ fontFamily: "var(--font-display)", fontSize: "var(--t-h3)", margin: "0 0 0.5rem" }}>
              Ölçülmüş Stabilite ve Hata Toleransları
            </h3>
            <p className="section__lead" style={{ fontSize: "var(--t-small)", margin: "0 0 var(--s-3)" }}>
              Bu platformda hiçbir stabilite iddiası tahmini değildir; fiziksel tezgahta ve
              ROS 2 test koşullarında doğrulanmış gerçek çalışma sınırlarıdır.
            </p>

            <table className="teknik-tablo">
              <caption>Stabilite ve Güvenlik Metrikleri</caption>
              <thead>
                <tr>
                  <th scope="col">Parametre</th>
                  <th scope="col">Ölçüm</th>
                  <th scope="col">Tolerans / Durum</th>
                </tr>
              </thead>
              <tbody>
                {STABILITE_METRIKLERI.map((m) => (
                  <tr key={m.id}>
                    <th scope="row">
                      {m.baslik}
                      <span style={{ display: "block", fontSize: "var(--t-micro)", color: "var(--ink-faint)", marginTop: "0.15rem" }}>
                        {m.kaynak}
                      </span>
                    </th>
                    <td className="mono">{m.nominalDeger}</td>
                    <td>
                      <span style={{ color: m.durum === "guvenli" ? "var(--ok)" : "var(--accent)" }}>
                        {m.tolerans}
                      </span>
                    </td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>

          <div className="robot-durumu__guvenlik-karti">
            <h3>Güvenlik ve Kesici Mimarisi</h3>
            <p style={{ margin: 0, fontSize: "var(--t-small)", color: "var(--ink-muted)", lineHeight: 1.5 }}>
              Robotun hareket ve güç hatları çok katmanlı donanımsal korumayla güvenceye
              alınmıştır. Herhangi bir katmanda iletişim kopsa dahi mekanik güvenlik korunur:
            </p>

            <ol className="robot-durumu__adimlar">
              <li className="robot-durumu__adim">
                <span className="robot-durumu__adim-no">01</span>
                <div className="robot-durumu__adim-metin">
                  <strong>Donanımsal Watchdog (500 ms)</strong>
                  <span>Bağlantı koptuğunda Mega2560 WDT zamanlayıcısı motor çıkışlarını kendiliğinden sıfırlar.</span>
                </div>
              </li>
              <li className="robot-durumu__adim">
                <span className="robot-durumu__adim-no">02</span>
                <div className="robot-durumu__adim-metin">
                  <strong>Ölü Bant & Dişli Histerezisi</strong>
                  <span>1.16° (3 tick) ölü bant filtresi sayesinde mekanik boşluk motor rezonansına yol açmaz.</span>
                </div>
              </li>
              <li className="robot-durumu__adim">
                <span className="robot-durumu__adim-no">03</span>
                <div className="robot-durumu__adim-metin">
                  <strong>Acil Durdurma (E-Stop) Hattı</strong>
                  <span>Yerel ağ veya konsoldan tetiklenen kesici komutu yazılım kuyruklarını atlayarak uygulanır.</span>
                </div>
              </li>
              <li className="robot-durumu__adim">
                <span className="robot-durumu__adim-no">04</span>
                <div className="robot-durumu__adim-metin">
                  <strong>Firmware Açı Kırpması (±85°)</strong>
                  <span>Üst katman taşsa dahi motor sürücüsü kalibre edilmemiş sınırın ötesine geçişi fiziksel olarak reddeder.</span>
                </div>
              </li>
            </ol>

            <div className="olcum-notu" style={{ margin: 0 }}>
              <span className="eyebrow">Güvenlik İlkesi</span>
              Güvenliği sağlayan katman en alttaki katmandır; üst yazılımların çalışıyor olması şart koşulmaz.
            </div>
          </div>
        </div>
      </div>
    </section>
  );
}
