"use client";

import { useActionState, useState } from "react";
import { ayarlarKaydet, type AyarlarSonuc } from "@/app/panel/ayarlar/actions";

interface Ayarlar {
  deviceId: string;
  voiceSpeed: number;
  voicePitch: number;
  ttsVoice: string;
  llmPrompt: string;
  greetingMessage: string;
  alertOnUnknown: boolean;
  alertEmail: string | null;
}

export function RobotAyarlariFormu({ ayarlar }: { ayarlar: Ayarlar }) {
  const [durum, eylem, bekliyor] = useActionState<AyarlarSonuc | null, FormData>(
    ayarlarKaydet,
    null,
  );

  const [hiz, setHiz] = useState(ayarlar.voiceSpeed);
  const [ton, setTon] = useState(ayarlar.voicePitch);

  return (
    <form action={eylem} className="form" style={{ maxWidth: "680px" }}>
      <input type="hidden" name="deviceId" value={ayarlar.deviceId} />

      {durum?.mesaj && (
        <p className="form__basari" role="status" style={{ color: "var(--color-success, #10b981)" }}>
          {durum.mesaj}
        </p>
      )}
      {durum?.hata && (
        <p className="form__hata" role="alert">
          {durum.hata}
        </p>
      )}

      {/* Ses & Konuşma */}
      <fieldset className="panel" style={{ border: "1px solid var(--color-border, #333)", padding: "1.25rem", borderRadius: "8px" }}>
        <legend style={{ padding: "0 0.5rem", fontWeight: "bold" }}>🎙️ Ses & Konuşma Yönetimi (TTS / XTTS)</legend>

        <div className="form__alan" style={{ marginTop: "0.5rem" }}>
          <label htmlFor="ttsVoice">Ses Modeli / Karakter</label>
          <select id="ttsVoice" name="ttsVoice" defaultValue={ayarlar.ttsVoice}>
            <option value="tr_tr_male">Türkçe — Erkek (Doğal / Tok)</option>
            <option value="tr_tr_female">Türkçe — Kadın (Nazik / Karşılama)</option>
            <option value="en_us_friendly">İngilizce — Dostane Asistan</option>
            <option value="robot_synth">Robotik Sentetik Efekt</option>
          </select>
        </div>

        <div className="form__alan">
          <label htmlFor="voiceSpeed">Konuşma Hızı: {hiz}%</label>
          <input
            id="voiceSpeed"
            name="voiceSpeed"
            type="range"
            min="60"
            max="160"
            value={hiz}
            onChange={(e) => setHiz(Number(e.target.value))}
          />
        </div>

        <div className="form__alan">
          <label htmlFor="voicePitch">Ses Tonu (Pitch): {ton}%</label>
          <input
            id="voicePitch"
            name="voicePitch"
            type="range"
            min="70"
            max="130"
            value={ton}
            onChange={(e) => setTon(Number(e.target.value))}
          />
        </div>

        <div className="form__alan">
          <label htmlFor="greetingMessage">Varsayılan Karşılama Cümlesi</label>
          <input
            id="greetingMessage"
            name="greetingMessage"
            defaultValue={ayarlar.greetingMessage}
            placeholder="Örn: Merhaba, hoş geldiniz! Size nasıl yardımcı olabilirim?"
          />
        </div>
      </fieldset>

      {/* Yapay Zeka & Kişilik */}
      <fieldset className="panel" style={{ border: "1px solid var(--color-border, #333)", padding: "1.25rem", borderRadius: "8px", marginTop: "1rem" }}>
        <legend style={{ padding: "0 0.5rem", fontWeight: "bold" }}>🧠 Robot Kişiliği & LLM Sistem Promptu</legend>
        <div className="form__alan" style={{ marginTop: "0.5rem" }}>
          <label htmlFor="llmPrompt">Sistem Promptu (Karakter ve Davranış)</label>
          <textarea
            id="llmPrompt"
            name="llmPrompt"
            rows={4}
            defaultValue={ayarlar.llmPrompt}
            placeholder="Robotun konuşma üslubunu, kurumsal kurallarını ve hitap tarzını belirleyin..."
          />
        </div>
      </fieldset>

      {/* Güvenlik & Anomali Alarmları */}
      <fieldset className="panel" style={{ border: "1px solid var(--color-border, #333)", padding: "1.25rem", borderRadius: "8px", marginTop: "1rem" }}>
        <legend style={{ padding: "0 0.5rem", fontWeight: "bold" }}>🚨 Güvenlik & Anomali Alarmları</legend>

        <div className="form__alan" style={{ marginTop: "0.5rem" }}>
          <label style={{ display: "flex", alignItems: "center", gap: "0.5rem", cursor: "pointer" }}>
            <input
              type="checkbox"
              name="alertOnUnknown"
              defaultChecked={ayarlar.alertOnUnknown}
            />
            Tanınmayan / yabancı kişi tespit edildiğinde e-posta bildirimi gönder
          </label>
        </div>

        <div className="form__alan">
          <label htmlFor="alertEmail">Alarm Bildirim E-postası</label>
          <input
            id="alertEmail"
            name="alertEmail"
            type="email"
            defaultValue={ayarlar.alertEmail ?? ""}
            placeholder="guvenlik@firma.com (Boş bırakılırsa hesap e-postası kullanılır)"
          />
        </div>
      </fieldset>

      <div style={{ marginTop: "1.5rem" }}>
        <button className="btn btn--primary" type="submit" disabled={bekliyor}>
          {bekliyor ? "Kaydediliyor…" : "Ayarları Kaydet ve Robota Gönder"}
        </button>
      </div>
    </form>
  );
}
