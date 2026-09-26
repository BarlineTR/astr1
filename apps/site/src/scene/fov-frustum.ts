import * as THREE from "three";

/**
 * Kameranın görüş hacmini üç boyutlu bir piramit olarak çizer.
 *
 * Önceki deneme bunu yatay bir dilim olarak çiziyordu; sahne neredeyse yatay
 * bakıldığı için dilim tam kenarından görünüyor ve kayboluyordu. Görüş alanının
 * iki açısı da (yatay 72°, dikey 53° — `docs/hardware.md §3`) hacim olarak
 * çizilince her bakış açısından okunur, üstelik daha doğru bilgi verir.
 */
export function createFovFrustum(options: {
  hfovDeg: number;
  vfovDeg: number;
  /** Piramidin uzunluğu (metre). Gerçek menzil değil, okunur bir gösterim uzunluğu. */
  length: number;
  color: THREE.ColorRepresentation;
}): {
  group: THREE.Group;
  setActive(active: boolean): void;
  setColor(color: THREE.ColorRepresentation): void;
  dispose(): void;
} {
  const { length } = options;
  const halfWidth = Math.tan(THREE.MathUtils.degToRad(options.hfovDeg) / 2) * length;
  const halfHeight = Math.tan(THREE.MathUtils.degToRad(options.vfovDeg) / 2) * length;

  // Uç nokta başta, taban +Z yönünde.
  const apex = new THREE.Vector3(0, 0, 0);
  const corners = [
    new THREE.Vector3(-halfWidth, halfHeight, length),
    new THREE.Vector3(halfWidth, halfHeight, length),
    new THREE.Vector3(halfWidth, -halfHeight, length),
    new THREE.Vector3(-halfWidth, -halfHeight, length),
  ];

  const group = new THREE.Group();
  const color = new THREE.Color(options.color);
  const disposables: Array<{ dispose(): void }> = [];

  // Yan yüzler: uçtan tabana doğru sönümlenen dolgu.
  const positions: number[] = [];
  const fades: number[] = [];
  for (let i = 0; i < 4; i++) {
    const a = corners[i]!;
    const b = corners[(i + 1) % 4]!;
    positions.push(apex.x, apex.y, apex.z, a.x, a.y, a.z, b.x, b.y, b.z);
    fades.push(0, 1, 1);
  }

  const fillGeometry = new THREE.BufferGeometry();
  fillGeometry.setAttribute("position", new THREE.Float32BufferAttribute(positions, 3));
  fillGeometry.setAttribute("aFade", new THREE.Float32BufferAttribute(fades, 1));

  const uniforms = {
    uColor: { value: color },
    uStrength: { value: 0.11 },
  };

  const fillMaterial = new THREE.ShaderMaterial({
    uniforms,
    transparent: true,
    depthWrite: false,
    side: THREE.DoubleSide,
    blending: THREE.AdditiveBlending,
    vertexShader: /* glsl */ `
      attribute float aFade;
      varying float vFade;
      void main() {
        vFade = aFade;
        gl_Position = projectionMatrix * modelViewMatrix * vec4(position, 1.0);
      }
    `,
    fragmentShader: /* glsl */ `
      uniform vec3 uColor;
      uniform float uStrength;
      varying float vFade;
      void main() {
        gl_FragColor = vec4(uColor, uStrength * (1.0 - vFade * 0.86));
      }
    `,
  });

  const fill = new THREE.Mesh(fillGeometry, fillMaterial);
  fill.renderOrder = 2;
  group.add(fill);
  disposables.push(fillGeometry, fillMaterial);

  // Kenarlar: hacmi tanımlayan çizgiler. Dolgudan daha belirgin.
  const edgePoints: number[] = [];
  for (const corner of corners) edgePoints.push(apex.x, apex.y, apex.z, corner.x, corner.y, corner.z);
  for (let i = 0; i < 4; i++) {
    const a = corners[i]!;
    const b = corners[(i + 1) % 4]!;
    edgePoints.push(a.x, a.y, a.z, b.x, b.y, b.z);
  }

  const edgeGeometry = new THREE.BufferGeometry();
  edgeGeometry.setAttribute("position", new THREE.Float32BufferAttribute(edgePoints, 3));
  const edgeMaterial = new THREE.LineBasicMaterial({
    color,
    transparent: true,
    opacity: 0.28,
    depthWrite: false,
  });
  const edges = new THREE.LineSegments(edgeGeometry, edgeMaterial);
  edges.renderOrder = 3;
  group.add(edges);
  disposables.push(edgeGeometry, edgeMaterial);

  return {
    group,
    setActive(active: boolean) {
      uniforms.uStrength.value = active ? 0.22 : 0.1;
      edgeMaterial.opacity = active ? 0.5 : 0.24;
    },
    setColor(next: THREE.ColorRepresentation) {
      color.set(next);
      edgeMaterial.color.set(next);
    },
    dispose() {
      for (const item of disposables) item.dispose();
    },
  };
}
