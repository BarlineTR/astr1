"use client";

import { useCallback, useEffect, useRef, useState } from "react";

import { HEAD_YAW_LIMIT_DEG, type Command, type Telemetry } from "@astro/protocol";

import {
  GECIKME_ESIGI_MS,
  gecideBaglan,
  type BaglantiDurumu,
  type CerceveKaydi,
  type GecitBaglantisi,
} from "@/console/gecit-baglantisi";
import { BaglantiSeridi } from "./BaglantiSeridi";
import { CerceveGunlugu } from "./CerceveGunlugu";
import { KafaGostergesi } from "./KafaGostergesi";
import { SesPusulasi } from "./SesPusulasi";

const SAHIP_ADI: Record<string, string> = {
  visual: "görüntü",
  audio: "ses",
  none: "yok",
};

/** Günlükte tutulan en fazla çerçeve. Eskiler düşer. */
const GUNLUK_SINIRI = 40;

/**
 * Kontrol konsolu.
 *
 * İki kip:
 *  - **demo**: tarayıcı içi senaryo, robota bağlanmaz. Komut yolu hiç kurulmaz
 *    — genel bir sayfada düğmeyi kapatmak yetmez, yolun var olmaması gerekir.
 *  - **canli**: ağ geçidine bağlanır, gerçek telemetriyi gösterir ve komut
 *    gönderir.
 *
 * 3B sahne ve telemetri birbirini beklemez: sahne yüklenemese de sayısal
 * değerler akar, telemetri gelmese de sahne boşta durur.
 */
export function Konsol({
  mod,
  cihazId,
  komutVerebilir: baslangicYetkisi = true,
}: {
  mod: "demo" | "canli";
  cihazId?: string;
  komutVerebilir?: boolean;
}) {
  const stageRef = useRef<HTMLDivElement>(null);
  const uygulaRef = useRef<
    | ((d: { headYawDeg: number; doaDeg: number | null; vad: boolean; faceVisible: boolean }) => void)
    | null
  >(null);
  const gecitRef = useRef<GecitBaglantisi | null>(null);
  const demoGonderRef = useRef<((k: Command) => void) | null>(null);

  const [telemetri, setTelemetri] = useState<Telemetry | null>(null);
  const [durum, setDurum] = useState<BaglantiDurumu>(mod === "demo" ? "bagli" : "yetkileniyor");
  const [ayrinti, setAyrinti] = useState<string | undefined>();
  const [gecikme, setGecikme] = useState<number | null>(null);
  const [robotBagli, setRobotBagli] = useState(mod === "demo");
  const [sonGorulme, setSonGorulme] = useState<number | null>(null);
  const [firmware, setFirmware] = useState<string | null>(null);
  const [kayitlar, setKayitlar] = useState<readonly CerceveKaydi[]>([]);
  const [komutVerebilir, setKomutVerebilir] = useState(baslangicYetkisi);
  const [hedefAci, setHedefAci] = useState(0);
  const [eStop, setEStop] = useState(false);
  const [sonOnay, setSonOnay] = useState<string | null>(null);

  const cerceveEkle = useCallback((kayit: CerceveKaydi) => {
    setKayitlar((oncekiler) => [kayit, ...oncekiler].slice(0, GUNLUK_SINIRI));
  }, []);

  const sahneyeUygula = useCallback((t: Telemetry) => {
    uygulaRef.current?.({
      // Sahne encoder gerçeğini gösterir, istenen açıyı değil.
      headYawDeg: t.head.actualYawDeg,
      doaDeg: t.audio.doaDeg,
      vad: t.audio.vad,
      faceVisible: t.gaze.visualValid,
    });
  }, []);

  /* ── 3B sahne ── */
  useEffect(() => {
    const stage = stageRef.current;
    if (!stage) return;

    let iptal = false;
    let sahne: { stop(): void } | null = null;

    void (async () => {
      try {
        const { createRobotScene } = await import("@/scene/robot-scene");
        if (iptal) return;
        const s = await createRobotScene(stage, { autoOrbit: false, offsetSubject: false });
        if (iptal) {
          s.stop();
          return;
        }
        s.start();
        sahne = s;
        uygulaRef.current = s.apply;
      } catch (hata) {
        console.error("Konsol sahnesi yüklenemedi:", hata);
      }
    })();

    return () => {
      iptal = true;
      uygulaRef.current = null;
      sahne?.stop();
    };
  }, []);

  /* ── Telemetri kaynağı ── */
  useEffect(() => {
    let iptal = false;

    if (mod === "demo") {
      let kaynak: { stop(): void } | null = null;
      void (async () => {
        const { connectTelemetry } = await import("@/console/telemetry");
        if (iptal) return;
        connectTelemetry((source) => {
          if (iptal) {
            source.stop();
            return;
          }
          kaynak = source;
          demoGonderRef.current = null; // Demoda komut yolu kurulmaz.
          source.onTelemetry((t) => {
            setTelemetri(t);
            sahneyeUygula(t);
          });
        });
      })();
      return () => {
        iptal = true;
        kaynak?.stop();
      };
    }

    if (!cihazId) return;

    const gecit = gecideBaglan(cihazId, {
      durum: (d, a) => {
        setDurum(d);
        setAyrinti(a);
      },
      telemetri: (t, g) => {
        setTelemetri(t);
        setGecikme(g);
        setEStop(t.safety.eStop);
        sahneyeUygula(t);
      },
      cihazDurumu: (bagli, gorulme, fw) => {
        setRobotBagli(bagli);
        setSonGorulme(gorulme);
        setFirmware(fw);
      },
      onay: (_komutId, kabul, neden) => {
        setSonOnay(kabul ? "Komut uygulandı." : `Komut reddedildi: ${neden ?? "—"}`);
      },
      cerceve: cerceveEkle,
      yetki: setKomutVerebilir,
    });

    gecitRef.current = gecit;

    return () => {
      iptal = true;
      gecit.kapat();
      gecitRef.current = null;
    };
  }, [mod, cihazId, cerceveEkle, sahneyeUygula]);

  const gecikmeYuksek = gecikme !== null && gecikme > GECIKME_ESIGI_MS;
  /*
   * Hareket komutları robot bağlı değilken ya da gecikme eşiği aşıldığında
   * gönderilmez. Acil durdurma bu kısıttan muaf: durdurmayı geciktirmek,
   * geciken bir hareket komutundan çok daha kötü.
   */
  const hareketKapali = !robotBagli || gecikmeYuksek;

  const komut = (k: Command): void => {
    gecitRef.current?.komutGonder(k);
    demoGonderRef.current?.(k);
  };

  return (
    <div className="konsol">
      {mod === "demo" ? (
        <div className="konsol__head">
          <div>
            <p className="eyebrow">Kontrol</p>
            <h1 className="page-title">Konsol demosu</h1>
            <p className="section__lead">
              Senaryo tarayıcınızda çalışıyor. Buradaki hiçbir değer gerçek bir
              robottan gelmiyor.
            </p>
          </div>
          <span className="badge badge--mock">SİMÜLASYON</span>
        </div>
      ) : (
        <BaglantiSeridi
          durum={durum}
          ayrinti={ayrinti}
          gecikmeMs={gecikme}
          sonGorulme={sonGorulme}
          firmware={firmware}
        />
      )}

      <div className="console__grid">
        <div className="panel panel--stage">
          {/* Sahne mutlak konumlu ayrı bir katman; kart yalnızca çerçeve. */}
          <div className="console__stage" ref={stageRef} />
        </div>

        <div className="panel">
          <p className="panel__title">Gelen veri</p>
          <dl className="readouts">
            <Okuma
              ad="İstenen açı"
              deger={telemetri ? `${telemetri.head.desiredYawDeg.toFixed(1)}°` : "—"}
            />
            <Okuma
              ad="Bakılan açı"
              deger={
                !telemetri
                  ? "—"
                  : telemetri.head.encoderOk
                    ? `${telemetri.head.actualYawDeg.toFixed(1)}°`
                    : "geri besleme yok"
              }
            />
            <Okuma
              ad="Dikkat"
              deger={telemetri ? (SAHIP_ADI[telemetri.gaze.attentionOwner] ?? "—") : "—"}
            />
            <Okuma ad="Durum" deger={telemetri?.gaze.state ?? "—"} />
            <Okuma
              ad="Ses yönü"
              deger={
                !telemetri || telemetri.audio.doaDeg === null
                  ? "—"
                  : `${telemetri.audio.doaDeg.toFixed(0)}° · güven ${telemetri.audio.confidence.toFixed(2)}`
              }
            />
            <Okuma ad="Görülen yüz" deger={telemetri ? String(telemetri.faces.length) : "—"} />
            <Okuma
              ad="Acil durdurma"
              deger={!telemetri ? "—" : telemetri.safety.eStop ? "ETKİN" : "kapalı"}
            />
            <Okuma
              ad="Watchdog"
              deger={!telemetri ? "—" : telemetri.safety.watchdogOk ? "sağlam" : "YENİLENMEDİ"}
            />
          </dl>
        </div>

        <div className="panel">
          <p className="panel__title">Bakılan açı</p>
          <KafaGostergesi
            istenen={telemetri?.head.desiredYawDeg ?? 0}
            olculen={telemetri?.head.actualYawDeg ?? 0}
          />
        </div>

        <div className="panel">
          <p className="panel__title">Ses yönü</p>
          <SesPusulasi
            aci={telemetri?.audio.doaDeg ?? null}
            vad={telemetri?.audio.vad ?? false}
          />
        </div>

        {mod === "canli" && komutVerebilir && (
          <div className="panel panel--wide">
            <p className="panel__title">Giden komut — manuel açı</p>

            <div className="controls">
              <div className="controls__slider">
                <input
                  type="range"
                  className="slider"
                  min={-HEAD_YAW_LIMIT_DEG}
                  max={HEAD_YAW_LIMIT_DEG}
                  step={1}
                  value={hedefAci}
                  disabled={hareketKapali}
                  aria-label="Kafa hedef açısı"
                  onChange={(e) => {
                    const yaw = Number(e.target.value);
                    setHedefAci(yaw);
                    komut({ kind: "head.target", yawDeg: yaw });
                  }}
                />
                <span className="slider__value mono">{hedefAci}°</span>
              </div>

              <div className="controls__buttons">
                <button
                  className="btn"
                  type="button"
                  disabled={hareketKapali}
                  onClick={() => {
                    setHedefAci(0);
                    komut({ kind: "head.center" });
                  }}
                >
                  Merkeze al
                </button>
                <button
                  className={eStop ? "btn btn--alarm is-engaged" : "btn btn--alarm"}
                  type="button"
                  onClick={() => {
                    const yeni = !eStop;
                    setEStop(yeni);
                    komut({ kind: "estop", engaged: yeni });
                  }}
                >
                  {eStop ? "DURDURMAYI KALDIR" : "ACİL DURDURMA"}
                </button>
              </div>
            </div>

            {sonOnay && <p className="controls__onay">{sonOnay}</p>}

            <p className="controls__note">
              {hareketKapali
                ? robotBagli
                  ? `Gecikme ${GECIKME_ESIGI_MS} ms üstünde: hareket komutları kapalı. Acil durdurma her zaman açık.`
                  : "Robot bağlı değil: hareket komutları kapalı. Acil durdurma her zaman açık."
                : `Hedef açı ±${HEAD_YAW_LIMIT_DEG}° aralığına kaynakta kırpılır; arayüzdeki sınır yalnızca geri bildirimdir. Acil durdurma ek bir katmandır — hareket sınırlarını zorlayan katman firmware'dir.`}
            </p>
          </div>
        )}

        {mod === "canli" && (
          <div className="panel panel--wide">
            <p className="panel__title">Çerçeve günlüğü</p>
            <CerceveGunlugu kayitlar={kayitlar} />
          </div>
        )}
      </div>
    </div>
  );
}

function Okuma({ ad, deger }: { ad: string; deger: string }) {
  return (
    <>
      <dt className="readouts__label">{ad}</dt>
      <dd className="readouts__value mono">{deger}</dd>
    </>
  );
}
