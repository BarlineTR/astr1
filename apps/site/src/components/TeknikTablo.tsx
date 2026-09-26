import {
  AUDIO_CHAT_CONE_DEG,
  AUDIO_REACHABLE_DEG,
  CAMERA_HFOV_DEG,
  CAMERA_VFOV_DEG,
  ENCODER_TICKS_PER_DEG,
  HEAD_DEADBAND_DEG,
  HEAD_YAW_LIMIT_DEG,
} from "@astro/protocol";

import { sayiBicimle } from "@/lib/para";

/**
 * Ölçülmüş çalışma değerleri.
 *
 * Gerçek bir `<table>`: üretken arama araçları ve ekran okuyucular satır/sütun
 * ilişkisini okur, ızgarayla çizilmiş kutu yığınını okuyamaz.
 *
 * Değerlerin hepsi `@astro/protocol` sabitlerinden gelir. Elle yazılmış bir
 * ölçüm, kalibrasyon değiştiğinde sessizce yanlış kalıyordu — bu depoda kural
 * zaten "iddianın sayısı nereden geldiği belli olsun".
 */
export function TeknikTablo() {
  const satirlar: ReadonlyArray<readonly [string, string, string]> = [
    [
      "Kafa dönüş aralığı",
      `±${HEAD_YAW_LIMIT_DEG}°`,
      "Encoder 440 tick / 170° ile karakterize edildi; ölçülmemiş aralığa çıkılmaz.",
    ],
    [
      "Encoder çözünürlüğü",
      `${sayiBicimle(ENCODER_TICKS_PER_DEG, 4)} tick/°`,
      "440 tick / 170° ölçümünden.",
    ],
    [
      "Kafa ölü bandı",
      `${sayiBicimle(HEAD_DEADBAND_DEG)}°`,
      "Firmware'de 3 tick; dişli boşluğu 0,85° olduğu için altına inilmez.",
    ],
    [
      "Kamera yatay görüş açısı",
      `${CAMERA_HFOV_DEG}°`,
      "OAK-D Lite derinlik kamerası.",
    ],
    [
      "Kamera dikey görüş açısı",
      `${CAMERA_VFOV_DEG}°`,
      "OAK-D Lite derinlik kamerası.",
    ],
    [
      "Sohbet konisi",
      `${AUDIO_CHAT_CONE_DEG}°`,
      "Bu açı içindeki ses anında kabul edilir; dışı ısrar ister.",
    ],
    [
      "Ulaşılabilir ses açısı",
      `${AUDIO_REACHABLE_DEG}°`,
      `Kafa limiti ${HEAD_YAW_LIMIT_DEG}° + kamera yarı-FOV ${sayiBicimle(CAMERA_HFOV_DEG / 2, 0)}°; ötesi kadraja giremez.`,
    ],
    ["Etkileşim mesafesi", "0,4 – 2,5 m", "Derinlik ölçümünün güvenilir olduğu aralık."],
  ];

  return (
    <table className="teknik-tablo">
      <caption>ASTRO V1 ölçülmüş çalışma değerleri</caption>
      <thead>
        <tr>
          <th scope="col">Değer</th>
          <th scope="col">Ölçüm</th>
          <th scope="col">Kaynak</th>
        </tr>
      </thead>
      <tbody>
        {satirlar.map(([ad, olcum, kaynak]) => (
          <tr key={ad}>
            <th scope="row">{ad}</th>
            <td className="mono">{olcum}</td>
            <td>{kaynak}</td>
          </tr>
        ))}
      </tbody>
    </table>
  );
}
