import * as THREE from "three";

/**
 * Gövdeye sabit kerteriz halkası: yön işaretleri ve sesin geldiği yönü gösteren imleç.
 *
 * Halka kafayla dönmez — gövde çerçevesindedir. Bu ayrım kozmetik değil: ReSpeaker
 * kafaya bağlı olduğu için ham yön kafaya göredir ve gövde açısıyla bileşilmeden
 * anlam taşımaz (`docs/hardware.md §2`). Halkanın sabit durması, telemetrideki
 * açının hangi çerçevede olduğunu görsel olarak da doğru anlatır.
 */
export function createBearingRing(options: {
  radius: number;
  color: THREE.ColorRepresentation;
  /** Bu açıların ötesi kadraja giremez; halkada soluk çizilir. */
  reachableDeg: number;
}): {
  group: THREE.Group;
  setBearing(deg: number | null, intensity: number): void;
  dispose(): void;
} {
  const group = new THREE.Group();
  const disposables: Array<{ dispose(): void }> = [];
  const color = new THREE.Color(options.color);

  // Taban halkası
  const ringGeometry = new THREE.RingGeometry(options.radius * 0.985, options.radius, 128);
  ringGeometry.rotateX(-Math.PI / 2);
  const ringMaterial = new THREE.MeshBasicMaterial({
    color,
    transparent: true,
    opacity: 0.22,
    side: THREE.DoubleSide,
    depthWrite: false,
  });
  group.add(new THREE.Mesh(ringGeometry, ringMaterial));
  disposables.push(ringGeometry, ringMaterial);

  // Her 30°'de bir kerteriz çizgisi; erişilemeyen sektörde daha soluk.
  const tickPositions: number[] = [];
  const tickAlphas: number[] = [];
  for (let deg = -180; deg < 180; deg += 30) {
    const reachable = Math.abs(deg) <= options.reachableDeg;
    const inner = options.radius * (deg % 90 === 0 ? 0.93 : 0.96);
    const rad = THREE.MathUtils.degToRad(deg);
    const alpha = reachable ? 0.45 : 0.14;
    tickPositions.push(
      Math.sin(rad) * inner, 0, Math.cos(rad) * inner,
      Math.sin(rad) * options.radius, 0, Math.cos(rad) * options.radius,
    );
    tickAlphas.push(alpha, alpha);
  }

  const tickGeometry = new THREE.BufferGeometry();
  tickGeometry.setAttribute("position", new THREE.Float32BufferAttribute(tickPositions, 3));
  tickGeometry.setAttribute("aAlpha", new THREE.Float32BufferAttribute(tickAlphas, 1));
  const tickMaterial = new THREE.ShaderMaterial({
    uniforms: { uColor: { value: color } },
    transparent: true,
    depthWrite: false,
    vertexShader: /* glsl */ `
      attribute float aAlpha;
      varying float vAlpha;
      void main() {
        vAlpha = aAlpha;
        gl_Position = projectionMatrix * modelViewMatrix * vec4(position, 1.0);
      }
    `,
    fragmentShader: /* glsl */ `
      uniform vec3 uColor;
      varying float vAlpha;
      void main() { gl_FragColor = vec4(uColor, vAlpha); }
    `,
  });
  group.add(new THREE.LineSegments(tickGeometry, tickMaterial));
  disposables.push(tickGeometry, tickMaterial);

  // Sesin geldiği yönü gösteren imleç.
  const markerGeometry = new THREE.CircleGeometry(options.radius * 0.045, 24);
  markerGeometry.rotateX(-Math.PI / 2);
  const markerMaterial = new THREE.MeshBasicMaterial({
    color,
    transparent: true,
    opacity: 0,
    depthWrite: false,
  });
  const marker = new THREE.Mesh(markerGeometry, markerMaterial);
  marker.visible = false;
  group.add(marker);
  disposables.push(markerGeometry, markerMaterial);

  return {
    group,
    setBearing(deg: number | null, intensity: number) {
      if (deg === null) {
        marker.visible = false;
        return;
      }
      const rad = THREE.MathUtils.degToRad(deg);
      marker.position.set(Math.sin(rad) * options.radius, 0, Math.cos(rad) * options.radius);
      marker.visible = true;
      markerMaterial.opacity = THREE.MathUtils.clamp(intensity, 0, 1) * 0.9;
      const scale = 1 + intensity * 0.6;
      marker.scale.setScalar(scale);
    },
    dispose() {
      for (const item of disposables) item.dispose();
    },
  };
}
