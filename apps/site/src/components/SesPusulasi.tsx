/**
 * Gövde çerçevesinde ses yönü pusulası.
 *
 * Kafa çerçevesine göre değil gövdeye göre: kafa dönerken işaretin yerinden
 * oynamaması, sesin gerçekten nereden geldiğini gösteriyor.
 */
export function SesPusulasi({ aci, vad }: { aci: number | null; vad: boolean }) {
  const rad = aci === null ? 0 : ((aci - 90) * Math.PI) / 180;
  const cx = 80 + Math.cos(rad) * 62;
  const cy = 80 + Math.sin(rad) * 62;

  return (
    <svg
      viewBox="0 0 160 160"
      className="compass"
      role="img"
      aria-label={aci === null ? "Ses yönü algılanmadı" : `Ses yönü ${aci.toFixed(0)} derece`}
    >
      <circle cx={80} cy={80} r={62} className="compass__ring" />
      {/* Gövdenin önü: işaretin hangi yöne göre okunduğunu gösterir. */}
      <line x1={80} y1={18} x2={80} y2={30} className="compass__front" />
      <circle
        r={7}
        className="compass__marker"
        cx={cx}
        cy={cy}
        /* Yön yokken tamamen gizli; ses etkinliği yokken soluk. */
        opacity={aci === null ? 0 : vad ? 1 : 0.35}
      />
    </svg>
  );
}
