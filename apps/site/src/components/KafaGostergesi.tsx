import { HEAD_YAW_LIMIT_DEG } from "@astro/protocol";

/**
 * İstenen ve ölçülen açıyı aynı yay üzerinde iki iğne olarak gösterir.
 *
 * İki iğne bilerek aynı yayda: aradaki fark takip gecikmesinin kendisi ve ayrı
 * göstergelerde bu fark görünmüyordu.
 */
export function KafaGostergesi({ istenen, olculen }: { istenen: number; olculen: number }) {
  const ucNoktasi = (derece: number, uzunluk: number) => {
    const rad = ((derece - 90) * Math.PI) / 180;
    return { x: 100 + Math.cos(rad) * uzunluk, y: 100 + Math.sin(rad) * uzunluk };
  };

  const istenenUc = ucNoktasi(istenen, 76);
  const olculenUc = ucNoktasi(olculen, 62);

  return (
    <svg viewBox="0 0 200 116" className="gauge" role="img" aria-label={`Kafa açısı: istenen ${istenen.toFixed(0)} derece, ölçülen ${olculen.toFixed(0)} derece`}>
      <path d={yayCiz(100, 100, 82, -HEAD_YAW_LIMIT_DEG, HEAD_YAW_LIMIT_DEG)} className="gauge__arc" />
      <line
        className="gauge__needle gauge__needle--desired"
        x1={100}
        y1={100}
        x2={istenenUc.x}
        y2={istenenUc.y}
      />
      <line
        className="gauge__needle gauge__needle--actual"
        x1={100}
        y1={100}
        x2={olculenUc.x}
        y2={olculenUc.y}
      />
    </svg>
  );
}

function yayCiz(cx: number, cy: number, r: number, baslangic: number, bitis: number): string {
  const nokta = (derece: number): [number, number] => {
    const rad = ((derece - 90) * Math.PI) / 180;
    return [cx + Math.cos(rad) * r, cy + Math.sin(rad) * r];
  };
  const [x1, y1] = nokta(baslangic);
  const [x2, y2] = nokta(bitis);
  const genisYay = Math.abs(bitis - baslangic) > 180 ? 1 : 0;
  return `M ${x1} ${y1} A ${r} ${r} 0 ${genisYay} 1 ${x2} ${y2}`;
}
