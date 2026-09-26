import { getTableColumns } from "drizzle-orm";
import { describe, expect, it } from "vitest";

import { auditEvents, consents, deviceGrants, devices, users } from "./schema";

/*
 * Şemanın *şeklini* doğrular; veritabanı gerektirmez, bu yüzden CI'da da koşar.
 */

describe("users", () => {
  it("rol alanı taşır", () => {
    expect(getTableColumns(users)).toHaveProperty("role");
  });

  it("e-posta tekildir", () => {
    expect(getTableColumns(users).email.isUnique).toBe(true);
  });

  it("parolanın kendisini tutmaz", () => {
    expect(getTableColumns(users)).not.toHaveProperty("password");
  });
});

describe("consents", () => {
  /*
   * KVKK: kimin neyi hangi metin sürümünde onayladığı sonradan gösterilebilmeli.
   * Metin sürümü tutulmazsa onay ispatlanamaz.
   */
  it("onaylanan metnin sürümünü tutar", () => {
    expect(getTableColumns(consents)).toHaveProperty("textVersion");
  });

  it("girişten önce verilen onayı da tutabilir", () => {
    expect(getTableColumns(consents).userId.notNull).toBe(false);
  });
});

describe("devices", () => {
  it("jetonun kendisini değil özetini tutar", () => {
    const kolonlar = getTableColumns(devices);
    expect(kolonlar).toHaveProperty("tokenHash");
    expect(kolonlar).not.toHaveProperty("token");
  });

  it("iptal edilebilir", () => {
    expect(getTableColumns(devices)).toHaveProperty("revokedAt");
  });
});

describe("deviceGrants", () => {
  it("cihaz yetkisini kullanıcı rolünden ayrı tutar", () => {
    expect(getTableColumns(deviceGrants)).toHaveProperty("role");
  });
});

describe("auditEvents", () => {
  it("aktör ve cihaz alanları boş olabilir", () => {
    const kolonlar = getTableColumns(auditEvents);
    expect(kolonlar.actorUserId.notNull).toBe(false);
    expect(kolonlar.deviceId.notNull).toBe(false);
  });

  /*
   * Denetim kaydı yalnızca eklenir. updatedAt kolonu olsaydı güncellenmesini
   * davet ederdi; kaydın değeri değiştirilememesinden geliyor.
   */
  it("güncelleme zamanı tutmaz", () => {
    expect(getTableColumns(auditEvents)).not.toHaveProperty("updatedAt");
  });
});
