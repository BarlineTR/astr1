import { randomUUID } from "node:crypto";
import { and, desc, eq } from "drizzle-orm";

import { db } from "@/db";
import { patrolWaypoints } from "@/db/schema";

export async function cihazinNoktalari(deviceId: string) {
  return db
    .select()
    .from(patrolWaypoints)
    .where(eq(patrolWaypoints.deviceId, deviceId))
    .orderBy(desc(patrolWaypoints.createdAt));
}

export async function noktaEkle(deviceId: string, name: string, x: number, y: number) {
  const id = randomUUID();
  await db.insert(patrolWaypoints).values({
    id,
    deviceId,
    name: name.trim(),
    x: Math.round(x),
    y: Math.round(y),
    yaw: 0,
  });
  return id;
}

export async function noktaSil(id: string, deviceId: string) {
  await db
    .delete(patrolWaypoints)
    .where(and(eq(patrolWaypoints.id, id), eq(patrolWaypoints.deviceId, deviceId)));
}
