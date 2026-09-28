import React from "react";

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

export function BiliselHafizaKutusu({ hafiza }: { hafiza: HafizaVerisi | null }) {
  if (!hafiza) return null;

  const peopleEntries = Object.entries(hafiza.known_people ?? {});
  const reminders = hafiza.active_reminders ?? [];
  const facts = hafiza.verified_facts ?? [];

  return (
    <div style={{ marginTop: "2rem", maxWidth: "680px" }}>
      <h2 style={{ fontSize: "1.25rem", marginBottom: "0.5rem" }}>
        🧠 Astro Canlı Bilişsel Hafıza & Konuşma Günlüğü
      </h2>
      <p style={{ color: "var(--color-muted, #a1a1aa)", fontSize: "0.9rem", marginBottom: "1rem" }}>
        Robotun fiziksel dünyada insanlarla girdiği diyaloglardan öğrendiği gerçek zamanlı hafıza kayıtları (<code>astro_memory.json</code>).
      </p>

      {/* Son Konuşmalar ve Sohbet Özetleri */}
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

        {peopleEntries.length === 0 ? (
          <p style={{ color: "var(--color-muted, #71717a)", fontSize: "0.85rem", margin: 0 }}>
            Henüz kaydedilmiş bir görüşme bulunmuyor.
          </p>
        ) : (
          <div style={{ display: "flex", flexDirection: "column", gap: "0.75rem" }}>
            {peopleEntries.map(([key, person]) => {
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

      {/* Aktif Hatırlatmalar & Bilgiler */}
      <div style={{ display: "grid", gridTemplateColumns: "1fr 1fr", gap: "1rem" }}>
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
          {reminders.length === 0 ? (
            <p style={{ color: "var(--color-muted, #71717a)", fontSize: "0.85rem", margin: 0 }}>
              Kayıtlı alarm veya hatırlatma yok.
            </p>
          ) : (
            <ul style={{ margin: 0, paddingLeft: "1.2rem", fontSize: "0.85rem" }}>
              {reminders.map((r, i) => (
                <li key={i} style={{ marginBottom: "0.3rem" }}>
                  <strong>{r.user_name}:</strong> {r.reminder_text}
                </li>
              ))}
            </ul>
          )}
        </div>

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
          {facts.length === 0 ? (
            <p style={{ color: "var(--color-muted, #71717a)", fontSize: "0.85rem", margin: 0 }}>
              Henüz özel gerçek öğrenilmedi.
            </p>
          ) : (
            <ul style={{ margin: 0, paddingLeft: "1.2rem", fontSize: "0.85rem" }}>
              {facts.map((f, i) => (
                <li key={i} style={{ marginBottom: "0.3rem" }}>
                  {f}
                </li>
              ))}
            </ul>
          )}
        </div>
      </div>
    </div>
  );
}
