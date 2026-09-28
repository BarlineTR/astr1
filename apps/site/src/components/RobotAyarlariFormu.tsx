"use client";

import { useActionState, useState } from "react";
import { ayarlarKaydet, type AyarlarSonuc } from "@/app/panel/ayarlar/actions";

interface Ayarlar {
  deviceId: string;
  persona?: string;
  voiceSpeed: number;
  voicePitch: number;
  ttsVoice: string;
  llmPrompt: string;
  greetingMessage: string;
  alertOnUnknown: boolean;
  alertEmail: string | null;
}

const PERSONA_PROMPTS: Record<string, string> = {
  kufurbaz: "Sen Astro'sun! Aşırı zeki, sivri dilli, acımasız sokak mizahı ve dobra sokak dili kullanan, lafı gediğine koyan bir robotsun. Asla kendini Küfürbaz Haydo vb. başka bir isimle tanıtma. Dobra, esprili ve hazırcevapsın. Karşındaki kişi Baran olduğunda onun baş mühendisin olduğunu bilerek sokak dobralığıyla konuş ama asla teyp gibi tek bir ezber cümleye sıkışma.",
  playful: "Sen neşeli, enerjik, meraklı, esprili, sempatik ve samimi bir sosyal robot asistansın. Karşındakine neşeyle ve samimiyetle yaklaşır, esprili ve yardımcı bir dil kullanırsın.",
  witty: "Sen yetişkin animasyonlarındaki (Deadpool / Rick Sanchez gibi) aşırı zeki, sivri dilli, alaycı, absürt ve hazırcevap bir robot dehasısın. Espri ve kıvrak zekanla lafı gediğine koyarsın. Temiz, zekice ve eğlenceli esprilerle konuşturursun.",
  flirt: "Sen aşırı özgüvenli, karizmatik, kıvrak zekalı, flörtöz, çapkın, tatlı dilli ve oyunbaz bir sosyal robotsun. Keskin zekanla, yerinde takılmalarınla, dikkatli gözlemlerinle, hafif meydan okumalarınla eğlenceli konuşursun.",
  formal: "Sen yüksek devlet protokolü ve kurumsal saygı kurallarına tam riayet eden, saygın, ölçülü, kibar ve profesyonel bir sosyal robotsun.",
  concierge: "Sen kurumsal bir danışma, karşılama ve ofis asistanı robotsun. Ziyaretçileri nazikçe karşılar, toplantı odalarını tarif eder ve sorularını yanıtlarsın.",
};

export function RobotAyarlariFormu({ ayarlar }: { ayarlar: Ayarlar }) {
  const [durum, eylem, bekliyor] = useActionState<AyarlarSonuc | null, FormData>(
    ayarlarKaydet,
    null,
  );

  const [seciliPersona, setSeciliPersona] = useState(ayarlar.persona ?? "kufurbaz");
  const [promptMetni, setPromptMetni] = useState(ayarlar.llmPrompt);
  const [hiz, setHiz] = useState(ayarlar.voiceSpeed);
  const [ton, setTon] = useState(ayarlar.voicePitch);

  const handlePersonaChange = (yeni: string) => {
    setSeciliPersona(yeni);
    if (PERSONA_PROMPTS[yeni]) {
      setPromptMetni(PERSONA_PROMPTS[yeni]);
    }
  };

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

      {/* Yapay Zeka & Kişilik Modu */}
      <fieldset className="panel" style={{ border: "1px solid var(--color-border, #333)", padding: "1.25rem", borderRadius: "8px" }}>
        <legend style={{ padding: "0 0.5rem", fontWeight: "bold" }}>🧠 Robot Kişiliği & Karakter Modu</legend>

        <div className="form__alan" style={{ marginTop: "0.5rem" }}>
          <label htmlFor="persona">Aktif Karakter / Persona</label>
          <select
            id="persona"
            name="persona"
            value={seciliPersona}
            onChange={(e) => handlePersonaChange(e.target.value)}
          >
            <option value="kufurbaz">🔥 Sokak Dobralığı (Küfürbaz Haydo Raconu — Sivri Dilli & Zeki)</option>
            <option value="playful">✨ Neşeli & Samimi Asistan (Dostane, Sempatik, Sıcak)</option>
            <option value="witty">⚡ Witty / Absürt Zeka (Deadpool / Rick Sanchez Tarzı İronik)</option>
            <option value="flirt">🌹 Karizmatik & Çapkın (Flörtöz, Oyunbaz, Özgüvenli)</option>
            <option value="formal">👔 Resmi & Kurumsal (Devlet Protokolü, Saygılı, Ölçülü)</option>
            <option value="concierge">🏢 Ofis & Karşılama Asistanı (Rehberlik & Misafir Ağırlama)</option>
            <option value="custom">🛠️ Özel Sistem Promptu (Tamamen Serbest Tanım)</option>
          </select>
        </div>

        <div className="form__alan">
          <label htmlFor="llmPrompt">Canlı Sistem Promptu (Karakter ve Davranış)</label>
          <textarea
            id="llmPrompt"
            name="llmPrompt"
            rows={4}
            value={promptMetni}
            onChange={(e) => setPromptMetni(e.target.value)}
            placeholder="Robotun konuşma üslubunu, kurumsal kurallarını ve hitap tarzını belirleyin..."
          />
          <small style={{ color: "var(--color-muted, #a1a1aa)", display: "block", marginTop: "0.25rem" }}>
            Seçtiğiniz kişilik modu ve prompt, robotun OpenAI GPT-4o / Realtime bilişsel zekasına doğrudan iletilir.
          </small>
        </div>
      </fieldset>

      {/* Ses & Konuşma */}
      <fieldset className="panel" style={{ border: "1px solid var(--color-border, #333)", padding: "1.25rem", borderRadius: "8px", marginTop: "1rem" }}>
        <legend style={{ padding: "0 0.5rem", fontWeight: "bold" }}>🎙️ Ses & Konuşma Yönetimi (OpenAI Realtime / Edge-TTS)</legend>

        <div className="form__alan" style={{ marginTop: "0.5rem" }}>
          <label htmlFor="ttsVoice">Ses Modeli / Karakter</label>
          <select id="ttsVoice" name="ttsVoice" defaultValue={ayarlar.ttsVoice}>
            <optgroup label="OpenAI Realtime Doğal Sesler (Önerilen)">
              <option value="echo">Echo (Tok, Doğal Erkek — Sokak & Karizmatik Mod)</option>
              <option value="alloy">Alloy (Dengeli, Nötr & Modern)</option>
              <option value="onyx">Onyx (Derin, Otoriter Erkek)</option>
              <option value="nova">Nova (Canlı, Enerjik & Neşeli Kadın)</option>
              <option value="shimmer">Shimmer (Sıcak, Nazik Kadın)</option>
              <option value="fable">Fable (İngiliz Aksanlı / Masalsı)</option>
            </optgroup>
            <optgroup label="Edge-TTS Türkçe Sesler (Yedek)">
              <option value="tr-TR-AhmetNeural">Ahmet (Türkçe Doğal Erkek)</option>
              <option value="tr-TR-EmelNeural">Emel (Türkçe Doğal Kadın)</option>
            </optgroup>
            <optgroup label="Özel Ses Klonlama">
              <option value="astro">Astro Custom Clone (XTTS v2)</option>
            </optgroup>
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
            placeholder="Örn: Selam, ne var ne yok?"
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
