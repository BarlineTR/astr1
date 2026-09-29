"use client";

import React, { useMemo, useState } from "react";

interface HafizaVerisi {
  robot_name?: string;
  owner_name?: string;
  current_persona?: string;
  verified_facts?: string[];
  active_reminders?: Array<{
    reminder_text: string;
    target_time: number;
    user_name: string;
  }>;
  known_people?: Record<
    string,
    {
      name: string;
      title?: string;
      notes?: string;
      session_summaries?: Array<{
        time_str: string;
        summary: string;
      }>;
    }
  >;
}

type Kategori = "tumu" | "gorusmeler" | "hatirlatmalar" | "gercekler";

export function BiliselHafizaKutusu({ hafiza }: { hafiza: HafizaVerisi | null }) {
  const [arama, setArama] = useState("");
  const [kategori, setKategori] = useState<Kategori>("tumu");

  const peopleEntries = useMemo(() => Object.entries(hafiza?.known_people ?? {}), [hafiza]);
  const reminders = useMemo(() => hafiza?.active_reminders ?? [], [hafiza]);
  const facts = useMemo(() => hafiza?.verified_facts ?? [], [hafiza]);

  // Filtrelenmiş kayıtlar
  const aramaKucuk = arama.trim().toLowerCase();

  const filtrelenmisKisiler = useMemo(() => {
    if (!aramaKucuk) return peopleEntries;
    return peopleEntries.filter(([_, p]) => {
      const matchName = p.name?.toLowerCase().includes(aramaKucuk);
      const matchTitle = p.title?.toLowerCase().includes(aramaKucuk);
      const matchNotes = p.notes?.toLowerCase().includes(aramaKucuk);
      const matchSummary = p.session_summaries?.some((s) => s.summary.toLowerCase().includes(aramaKucuk));
      return matchName || matchTitle || matchNotes || matchSummary;
    });
  }, [peopleEntries, aramaKucuk]);

  const filtrelenmisHatirlatmalar = useMemo(() => {
    if (!aramaKucuk) return reminders;
    return reminders.filter(
      (r) =>
        r.user_name.toLowerCase().includes(aramaKucuk) ||
        r.reminder_text.toLowerCase().includes(aramaKucuk),
    );
  }, [reminders, aramaKucuk]);

  const filtrelenmisGercekler = useMemo(() => {
    if (!aramaKucuk) return facts;
    return facts.filter((f) => f.toLowerCase().includes(aramaKucuk));
  }, [facts, aramaKucuk]);

  if (!hafiza) return null;

  return (
    <div style={{ marginTop: "2rem", maxWidth: "680px" }}>
      <div style={{ display: "flex", justifyContent: "space-between", alignItems: "baseline", flexWrap: "wrap", gap: "0.5rem" }}>
        <h2 style={{ fontSize: "1.25rem", margin: 0 }}>
          🧠 Astro Canlı Bilişsel Hafıza & Konuşma Günlüğü
        </h2>
        <span className="badge badge--mock" style={{ fontSize: "0.7rem" }}>
          JSON AKTİF
        </span>
      </div>
      <p style={{ color: "var(--color-muted, #a1a1aa)", fontSize: "0.9rem", margin: "0.35rem 0 1rem" }}>
        Robotun fiziksel dünyada insanlarla girdiği diyaloglardan öğrendiği gerçek zamanlı hafıza kayıtları (<code>astro_memory.json</code>).
      </p>

      {/* Arama ve Filtreleme Kontrolleri */}
      <div style={{ display: "flex", flexDirection: "column", gap: "0.75rem", marginBottom: "1.25rem" }}>
        <div style={{ position: "relative" }}>
          <input
            type="search"
            placeholder="🔍 Hafızada veya geçmiş konuşmalarda ara…"
            value={arama}
            onChange={(e) => setArama(e.target.value)}
            style={{
              width: "100%",
              padding: "0.6rem 0.85rem",
              background: "rgba(255, 255, 255, 0.04)",
              border: "1px solid var(--rule)",
              borderRadius: "6px",
              color: "var(--ink)",
              fontSize: "0.9rem",
            }}
          />
        </div>

        <div style={{ display: "flex", gap: "0.5rem", flexWrap: "wrap" }}>
          <button
            type="button"
            onClick={() => setKategori("tumu")}
            className="btn btn--ghost"
            style={{
              fontSize: "0.78rem",
              padding: "0.25rem 0.65rem",
              borderColor: kategori === "tumu" ? "var(--accent)" : "transparent",
              color: kategori === "tumu" ? "var(--accent)" : "var(--ink-muted)",
              background: kategori === "tumu" ? "var(--accent-sunken)" : "rgba(255,255,255,0.03)",
            }}
          >
            Tümü ({peopleEntries.length + reminders.length + facts.length})
          </button>
          <button
            type="button"
            onClick={() => setKategori("gorusmeler")}
            className="btn btn--ghost"
            style={{
              fontSize: "0.78rem",
              padding: "0.25rem 0.65rem",
              borderColor: kategori === "gorusmeler" ? "var(--accent)" : "transparent",
              color: kategori === "gorusmeler" ? "var(--accent)" : "var(--ink-muted)",
              background: kategori === "gorusmeler" ? "var(--accent-sunken)" : "rgba(255,255,255,0.03)",
            }}
          >
            💬 Görüşmeler ({peopleEntries.length})
          </button>
          <button
            type="button"
            onClick={() => setKategori("hatirlatmalar")}
            className="btn btn--ghost"
            style={{
              fontSize: "0.78rem",
              padding: "0.25rem 0.65rem",
              borderColor: kategori === "hatirlatmalar" ? "var(--accent)" : "transparent",
              color: kategori === "hatirlatmalar" ? "var(--accent)" : "var(--ink-muted)",
              background: kategori === "hatirlatmalar" ? "var(--accent-sunken)" : "rgba(255,255,255,0.03)",
            }}
          >
            ⏰ Hatırlatmalar ({reminders.length})
          </button>
          <button
            type="button"
            onClick={() => setKategori("gercekler")}
            className="btn btn--ghost"
            style={{
              fontSize: "0.78rem",
              padding: "0.25rem 0.65rem",
              borderColor: kategori === "gercekler" ? "var(--accent)" : "transparent",
              color: kategori === "gercekler" ? "var(--accent)" : "var(--ink-muted)",
              background: kategori === "gercekler" ? "var(--accent-sunken)" : "rgba(255,255,255,0.03)",
            }}
          >
            ⭐ Gerçekler ({facts.length})
          </button>
        </div>
      </div>

      {/* Son Konuşmalar ve Sohbet Özetleri */}
      {(kategori === "tumu" || kategori === "gorusmeler") && (
        <div
          className="panel"
          style={{
            border: "1px solid var(--color-border, #333)",
            borderRadius: "8px",
            padding: "1rem",
            marginBottom: "1rem",
            backgroundColor: "rgba(255, 255, 255, 0.02)",
          }}
        >
          <h3 style={{ fontSize: "1rem", marginTop: 0, marginBottom: "0.75rem", display: "flex", alignItems: "center", gap: "0.5rem" }}>
            <span>💬</span> Son Görüşmeler & Diyalog Özetleri
          </h3>

          {filtrelenmisKisiler.length === 0 ? (
            <p style={{ color: "var(--color-muted, #71717a)", fontSize: "0.85rem", margin: 0 }}>
              {arama ? "Aramaya uygun görüşme bulunamadı." : "Henüz kaydedilmiş bir görüşme bulunmuyor."}
            </p>
          ) : (
            <div style={{ display: "flex", flexDirection: "column", gap: "0.75rem" }}>
              {filtrelenmisKisiler.map(([key, person]) => {
                const summaries = person.session_summaries ?? [];
                if (summaries.length === 0) return null;
                return (
                  <div
                    key={key}
                    style={{
                      borderLeft: "3px solid var(--color-primary, #3b82f6)",
                      paddingLeft: "0.75rem",
                    }}
                  >
                    <strong style={{ fontSize: "0.9rem", display: "block" }}>
                      {person.name} {person.title ? `(${person.title})` : ""}
                    </strong>
                    <ul style={{ margin: "0.25rem 0 0", paddingLeft: "1.2rem", fontSize: "0.85rem", color: "var(--color-text-secondary, #d4d4d8)" }}>
                      {summaries.slice(-3).map((s, idx) => (
                        <li key={idx} style={{ marginBottom: "0.2rem" }}>
                          <span style={{ color: "var(--color-muted, #a1a1aa)", marginRight: "0.5rem" }}>
                            [{s.time_str}]
                          </span>
                          {s.summary}
                        </li>
                      ))}
                    </ul>
                  </div>
                );
              })}
            </div>
          )}
        </div>
      )}

      {/* Aktif Hatırlatmalar & Bilgiler */}
      <div style={{ display: "grid", gridTemplateColumns: (kategori === "tumu" ? "1fr 1fr" : "1fr"), gap: "1rem" }}>
        {(kategori === "tumu" || kategori === "hatirlatmalar") && (
          <div
            className="panel"
            style={{
              border: "1px solid var(--color-border, #333)",
              borderRadius: "8px",
              padding: "1rem",
              backgroundColor: "rgba(255, 255, 255, 0.02)",
            }}
          >
            <h3 style={{ fontSize: "0.95rem", marginTop: 0, marginBottom: "0.5rem", display: "flex", alignItems: "center", gap: "0.4rem" }}>
              <span>⏰</span> Aktif Hatırlatmalar
            </h3>
            {filtrelenmisHatirlatmalar.length === 0 ? (
              <p style={{ color: "var(--color-muted, #71717a)", fontSize: "0.85rem", margin: 0 }}>
                {arama ? "Aramaya uygun hatırlatma yok." : "Kayıtlı alarm veya hatırlatma yok."}
              </p>
            ) : (
              <ul style={{ margin: 0, paddingLeft: "1.2rem", fontSize: "0.85rem" }}>
                {filtrelenmisHatirlatmalar.map((r, i) => (
                  <li key={i} style={{ marginBottom: "0.3rem" }}>
                    <strong>{r.user_name}:</strong> {r.reminder_text}
                  </li>
                ))}
              </ul>
            )}
          </div>
        )}

        {(kategori === "tumu" || kategori === "gercekler") && (
          <div
            className="panel"
            style={{
              border: "1px solid var(--color-border, #333)",
              borderRadius: "8px",
              padding: "1rem",
              backgroundColor: "rgba(255, 255, 255, 0.02)",
            }}
          >
            <h3 style={{ fontSize: "0.95rem", marginTop: 0, marginBottom: "0.5rem", display: "flex", alignItems: "center", gap: "0.4rem" }}>
              <span>⭐</span> Doğrulanmış Gerçekler
            </h3>
            {filtrelenmisGercekler.length === 0 ? (
              <p style={{ color: "var(--color-muted, #71717a)", fontSize: "0.85rem", margin: 0 }}>
                {arama ? "Aramaya uygun gerçek bulunamadı." : "Henüz özel gerçek öğrenilmedi."}
              </p>
            ) : (
              <ul style={{ margin: 0, paddingLeft: "1.2rem", fontSize: "0.85rem" }}>
                {filtrelenmisGercekler.map((f, i) => (
                  <li key={i} style={{ marginBottom: "0.3rem" }}>
                    {f}
                  </li>
                ))}
              </ul>
            )}
          </div>
        )}
      </div>
    </div>
  );
}
