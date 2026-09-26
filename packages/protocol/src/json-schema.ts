import { z } from "zod";

import { commandSchema, telemetrySchema } from "./schema";
import { PROTOCOL_VERSION } from "./version";

/**
 * ROS tarafındaki Python ajanı için makine okunur sözleşme.
 *
 * İki depo arasındaki tek bağ budur: site dalı sözleşmeyi üretir, ROS dalındaki
 * ajan kendi testinde bu şemaya karşı doğrular. Sözleşmeyi Python'da elle
 * kopyalamak, bir süre sonra sessizce ayrışan iki gerçek demekti.
 *
 * zod 4 JSON Schema üretimini kendi içinde taşıyor; ayrı bir dönüştürücü paket
 * hem bir bağımlılık hem de güncel tutulması gereken başka bir kopyaydı.
 */
export function protocolJsonSchema(): Record<string, unknown> {
  return {
    $schema: "https://json-schema.org/draft/2020-12/schema",
    $id: `https://astro.example/schema/protocol-${PROTOCOL_VERSION}.json`,
    $defs: {
      Telemetry: z.toJSONSchema(telemetrySchema),
      Command: z.toJSONSchema(commandSchema),
    },
  };
}
