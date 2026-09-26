"use client";

import { useEffect, useRef, useState } from "react";

import { HEAD_YAW_LIMIT_DEG, type Command, type Telemetry } from "@astro/protocol";

import { KafaGostergesi } from "./KafaGostergesi";
import { SesPusulasi } from "./SesPusulasi";

const SAHIP_ADI: Record<string, string> = {
  visual: "görüntü",
  audio: "ses",
  none: "yok",
};

/**
 * Kontrol konsolu.
 *
 * İki kipte çalışır:
 *  - "demo": tarayıcı içi senaryo. Komut yolu **hiç kurulmaz** — genel bir
 *    sayfada düğmeleri devre dışı bırakmak yetmez, yolun var olmaması gerekir.
 *  - "canli": ağ geçidine bağlanır ve komut gönderebilir.
 *
 * Telemetri istemcisi ve 3B sahne çerçeveden bağımsız modüller; burada yalnızca
 * `useEffect` içinde sürülüyorlar.
 */
export function Konsol({ mod }: { mod: "demo" | "canli" }) {
  const stageRef = useRef<HTMLDivElement>(null);
  const gonderRef = useRef<((komut: Command) => void) | null>(null);

  const [telemetri, setTelemetri] = useState<Telemetry | null>(null);
  const [kaynak, setKaynak] = useState<"baglaniyor" | "websocket" | "browser">("baglaniyor");
  const [hedefAci, setHedefAci] = useState(0);
  const [eStop, setEStop] = useState(false);

  useEffect(() => {
    const stage = stageRef.current;
    let iptal = false;
    let sahne: { stop(): void } | null = null;
    let kaynakRef: { stop(): void } | null = null;
    let uygula:
      | ((d: { headYawDeg: number; doaDeg: number | null; vad: boolean; faceVisible: boolean }) => void)
      | null = null;

    /*
     * Sahne ile telemetri birbirini beklemez: sahne yüklenemese de sayısal
     * değerler akmaya devam eder, telemetri gelmese de sahne boşta durur.
     */
    if (stage) {
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
          uygula = s.apply;
        } catch (hata) {
          console.error("Konsol sahnesi yüklenemedi:", hata);
        }
      })();
    }

    void (async () => {
      const { connectTelemetry } = await import("@/console/telemetry");
      if (iptal) return;

      connectTelemetry((source) => {
        /*
         * Bileşen kaynak kurulmadan sökülmüş olabilir (kullanıcı hemen başka
         * sayfaya gittiyse). O durumda kaynağı açıp bırakmak yerine hemen
         * kapatıyoruz; yoksa açık bir WebSocket geride kalıyor.
         */
        if (iptal) {
          source.stop();
          return;
        }
        kaynakRef = source;
        setKaynak(source.kind);

        // Demo kipinde komut yolu hiç bağlanmaz.
        gonderRef.current = mod === "canli" ? (k) => source.send(k) : null;

        source.onTelemetry((t) => {
          setTelemetri(t);
          uygula?.({
            // Sahne encoder gerçeğini gösterir, istenen açıyı değil.
            headYawDeg: t.head.actualYawDeg,
            doaDeg: t.audio.doaDeg,
            vad: t.audio.vad,
            faceVisible: t.gaze.visualValid,
          });
          setEStop(t.safety.eStop);
        });
      });
    })();

    return () => {
      iptal = true;
      kaynakRef?.stop();
      sahne?.stop();
    };
  }, [mod]);

  const komut = (k: Command): void => gonderRef.current?.(k);

  return (
    <div className="konsol">
      <div className="konsol__head">
        <div>
          <p className="eyebrow">Kontrol</p>
          <h1 className="page-title">
            {mod === "demo" ? "Konsol demosu" : "Kontrol konsolu"}
          </h1>
          <p className="section__lead">
            {mod === "demo"
              ? "Senaryo tarayıcınızda çalışıyor. Buradaki hiçbir değer gerçek bir robottan gelmiyor."
              : "Robotun anlık durumu ve kafa hareketi."}
          </p>
        </div>
        <span className={`badge ${kaynak === "websocket" ? "badge--live" : "badge--mock"}`}>
          {kaynak === "baglaniyor"
            ? "bağlanıyor…"
            : kaynak === "websocket"
              ? "sunucuya bağlı"
              : "SİMÜLASYON"}
        </span>
      </div>

      <div className="console__grid">
        <div className="panel panel--stage">
          {/* Sahne mutlak konumlu ayrı bir katman; kart yalnızca çerçeve. */}
          <div className="console__stage" ref={stageRef} />
        </div>

        <div className="panel">
          <p className="panel__title">Durum</p>
          <dl className="readouts">
            <Okuma ad="İstenen açı" deger={telemetri ? `${telemetri.head.desiredYawDeg.toFixed(1)}°` : "—"} />
            <Okuma
              ad="Ölçülen açı"
              deger={
                !telemetri
                  ? "—"
                  : telemetri.head.encoderOk
                    ? `${telemetri.head.actualYawDeg.toFixed(1)}°`
                    : "geri besleme yok"
              }
            />
            <Okuma ad="Dikkat" deger={telemetri ? (SAHIP_ADI[telemetri.gaze.attentionOwner] ?? "—") : "—"} />
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
          </dl>
        </div>

        <div className="panel">
          <p className="panel__title">Kafa açısı</p>
          <KafaGostergesi
            istenen={telemetri?.head.desiredYawDeg ?? 0}
            olculen={telemetri?.head.actualYawDeg ?? 0}
          />
        </div>

        <div className="panel">
          <p className="panel__title">Ses yönü</p>
          <SesPusulasi aci={telemetri?.audio.doaDeg ?? null} vad={telemetri?.audio.vad ?? false} />
        </div>

        {/*
          Komut paneli yalnızca canlı kipte çizilir. Demo sayfası genel erişime
          açık; orada komut arayüzünün hiç bulunmaması gerekir.
        */}
        {mod === "canli" && (
          <div className="panel panel--wide">
            <p className="panel__title">Komut</p>
            <div className="controls">
              <div className="controls__slider">
                <input
                  type="range"
                  className="slider"
                  min={-HEAD_YAW_LIMIT_DEG}
                  max={HEAD_YAW_LIMIT_DEG}
                  step={1}
                  value={hedefAci}
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
            <p className="controls__note">
              Hedef açı ±{HEAD_YAW_LIMIT_DEG}° aralığına kaynakta kırpılır; arayüzdeki
              sınır yalnızca geri bildirimdir. Acil durdurma ek bir katmandır —
              hareket sınırlarını zorlayan katman firmware'dir.
            </p>
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
