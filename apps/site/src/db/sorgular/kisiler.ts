import { randomUUID } from "node:crypto";
import { and, desc, eq } from "drizzle-orm";

import { db } from "@/db";
import { people, type KisiRol } from "@/db/schema";

export async function kullanicininKisileri(userId: string) {
  return db
    .select()
    .from(people)
    .where(eq(people.ownerUserId, userId))
    .orderBy(desc(people.createdAt));
}

export async function kisiEkle(girdi: {
  ownerUserId: string;
  deviceId?: string | null;
  name: string;
  role: KisiRol;
  notes?: string | null;
  photoBase64?: string | null;
}) {
  const id = randomUUID();
  await db.insert(people).values({
    id,
    ownerUserId: girdi.ownerUserId,
    deviceId: girdi.deviceId ?? null,
    name: girdi.name.trim(),
    role: girdi.role,
    notes: girdi.notes?.trim() ?? null,
    photoBase64: girdi.photoBase64 ?? null,
  });
  return id;
}

export async function kisiSil(id: string, ownerUserId: string) {
  await db
    .delete(people)
    .where(and(eq(people.id, id), eq(people.ownerUserId, ownerUserId)));
}
