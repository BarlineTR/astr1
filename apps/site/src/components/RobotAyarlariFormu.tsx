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
  speechOrientation?: string;
  quietMode?: boolean;
  sleepMode?: boolean;
  proactiveGreeting?: boolean;
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
  const [konusuyor, setKonusuyor] = useState(false);

  const handlePersonaChange = (yeni: string) => {
    setSeciliPersona(yeni);
    if (PERSONA_PROMPTS[yeni]) {
      setPromptMetni(PERSONA_PROMPTS[yeni]);
    }
  };

  const sesTestEt = () => {
    if (typeof window === "undefined" || !("speechSynthesis" in window)) {
      alert("Tarayıcınız Web Speech ses sentezini desteklemiyor.");
      return;
    }

    if (konusuyor) {
      window.speechSynthesis.cancel();
      setKonusuyor(false);
      return;
    }

    window.speechSynthesis.cancel();

    const testCumlesi =
      ayarlar.greetingMessage ||
      "Merhaba! Ben Astro. Sistemlerimi yapılandırdığınız için teşekkür ederim.";
    const utterance = new SpeechSynthesisUtterance(testCumlesi);

    utterance.rate = Math.max(0.5, Math.min(2.0, hiz / 100));
    utterance.pitch = Math.max(0.5, Math.min(2.0, ton / 100));
    utterance.lang = "tr-TR";

    const sesler = window.speechSynthesis.getVoices();
    const trSes = sesler.find((v) => v.lang.startsWith("tr")) || sesler[0];
    if (trSes) {
      utterance.voice = trSes;
    }

    utterance.onstart = () => setKonusuyor(true);
    utterance.onend = () => setKonusuyor(false);
    utterance.onerror = () => setKonusuyor(false);

    window.speechSynthesis.speak(utterance);
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

        <div style={{ marginTop: "0.75rem", display: "flex", alignItems: "center", gap: "0.75rem" }}>
          <button
            type="button"
            className="btn btn--secondary"
            onClick={sesTestEt}
            style={{ display: "inline-flex", alignItems: "center", gap: "0.5rem" }}
          >
            {konusuyor ? "⏹️ Sesi Durdur" : "🔊 Seçili Sesi ve Hızı Canlı Dinle"}
          </button>
          <small style={{ color: "var(--color-muted, #a1a1aa)" }}>
            (Tarayıcınızın konuşma sentezleyicisi ile anlık hız & ton önizlemesi)
          </small>
        </div>
      </fieldset>

      {/* Konuşma Yönelimi & Kafa Takibi */}
      <fieldset className="panel" style={{ border: "1px solid var(--color-border, #333)", padding: "1.25rem", borderRadius: "8px", marginTop: "1rem" }}>
        <legend style={{ padding: "0 0.5rem", fontWeight: "bold" }}>🎯 Konuşma Yönelimi & Kafa Takip Modu</legend>

        <div className="form__alan" style={{ marginTop: "0.5rem" }}>
          <label htmlFor="speechOrientation">Ses & Kafa Yönelim Stratejisi</label>
          <select
            id="speechOrientation"
            name="speechOrientation"
            defaultValue={ayarlar.speechOrientation ?? "autonomous"}
          >
            <option value="autonomous">🎯 Otonom Çok Modlu Yönelim (Ses DOA + Kamera Yüz Füzyonu — Önerilen)</option>
            <option value="face_only">👁️ Yalnızca Görsel Yüz Takibi (Sese dönmez, kameradaki yüze odaklanır)</option>
            <option value="sound_only">🎤 Yalnızca Ses Yönü / DOA Takibi (Mikrofon dizisinin tespit ettiği açıya yönelir)</option>
            <option value="fixed">🛑 Sabit Kafa (Otonom takip devre dışı, yalnızca manuel kontrolde kalır)</option>
          </select>
          <small style={{ color: "var(--color-muted, #a1a1aa)", display: "block", marginTop: "0.25rem" }}>
            Astro'nun konuşan kişiye veya çevredeki seslere göre kafasını nasıl çevireceğini belirler.
          </small>
        </div>

        <div className="form__alan" style={{ marginTop: "0.75rem" }}>
          <label style={{ display: "flex", alignItems: "center", gap: "0.5rem", cursor: "pointer" }}>
            <input
              type="checkbox"
              name="proactiveGreeting"
              defaultChecked={ayarlar.proactiveGreeting ?? true}
            />
            Biri odaya girdiğinde veya yaklaştığında proaktif olarak söze başla (Lobi / Karşılama)
          </label>
        </div>

        <div className="form__alan" style={{ marginTop: "0.5rem" }}>
          <label style={{ display: "flex", alignItems: "center", gap: "0.5rem", cursor: "pointer" }}>
            <input
              type="checkbox"
              name="quietMode"
              defaultChecked={ayarlar.quietMode ?? false}
            />
            Sessiz Dinleme Modu (Robot ses çıkarmaz, yalnızca dinler ve not alır)
          </label>
        </div>

        <div className="form__alan" style={{ marginTop: "0.5rem" }}>
          <label style={{ display: "flex", alignItems: "center", gap: "0.5rem", cursor: "pointer" }}>
            <input
              type="checkbox"
              name="sleepMode"
              defaultChecked={ayarlar.sleepMode ?? false}
            />
            Uyku / Bekleme Modu (Motorlar ve konuşma uykuya alınır)
          </label>
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
