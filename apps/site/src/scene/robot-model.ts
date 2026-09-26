import * as THREE from "three";
import { GLTFLoader } from "three/examples/jsm/loaders/GLTFLoader.js";
import type { GLTF } from "three/examples/jsm/loaders/GLTFLoader.js";

/**
 * Sahnedeki robot modelinin, sahnenin geri kalanına gösterdiği yüz.
 *
 * Sahne bu arayüzün ötesini bilmez: modelin fotogrametri taraması mı yoksa
 * modellenmiş bir montaj mı olduğu burada biter. Model değiştiğinde değişecek
 * tek dosya bu modülün uygulamasıdır.
 */
export interface RobotModel {
  /** Sahneye eklenecek kök. Tabanı y=0'a oturur, yatayda ortalanmıştır. */
  root: THREE.Group;
  /** Kafa yaw ekseninin taban düzleminden yüksekliği (metre). */
  headAxisHeight: number;
  /** Modelin yatay yarıçapı (metre) — koni ve halka ölçeklemesi buna dayanır. */
  radius: number;
  /** Modelin toplam yüksekliği (metre). */
  height: number;
  /** Kafayı verilen açıya döndürür. Sınır uygulanmaz; çağıran kırpar. */
  setHeadYaw(deg: number): void;
  dispose(): void;
}

export interface ScanModelConfig {
  url: string;
  /**
   * Gövde ile kubbenin ayrıldığı yükseklik (modelin kendi koordinatlarında, metre).
   *
   * ÖLÇÜM: `scripts/measure-model-seam.py` modelin dikey profilini 36 dilime böler
   * ve her dilimin 95. yüzdelik yatay yarıçapını çıkarır. Bu modelde yarıçap
   * y=0,509'da 0,2167'den 0,1721'e düşüyor — %21'lik süreksizlik, yani dikiş.
   * Diğer dilimler arasındaki değişim %5'in altında.
   *
   * Model değiştirilirse bu değer yeniden ölçülmelidir; tahmin edilmemelidir.
   */
  domeSeamY: number;
}

/**
 * Bu depoya konan tarama modelinin ölçülmüş yapılandırması.
 *
 * **GEÇİCİ** — `docs/RISKLER.md` R1. Bu dosya ASTRO'nun kendisi değil, bir
 * R2-D2 oyuncağının taraması ve R2-D2 Lucasfilm markası. Gerçek ASTRO taraması
 * henüz yapılmadığı için yerinde duruyor; site para almaya başlamadan önce
 * değişmek zorunda.
 *
 * Model değiştiğinde değişecek tek yer burasıdır — ama `domeSeamY` tahmin
 * edilmez, yeniden ölçülür:
 *   python3 scripts/measure-model-seam.py apps/site/public/models/<yeni>.glb
 */
export const HERO_MODEL: ScanModelConfig = {
  url: "/models/astro-hero.glb",
  domeSeamY: 0.5094,
};

/**
 * Tek parça bir taramayı, kubbesi ayrı dönebilen bir modele çevirir.
 *
 * Tarama tek mesh, tek düğüm ve hiyerarşisizdir; kubbe ayrı bir nesne değildir.
 * Üçgenler ağırlık merkezlerinin yüksekliğine göre iki indeks kümesine ayrılır.
 * Köşe tamponları paylaşılır — kopyalanan tek şey indeks dizisidir.
 */
/**
 * Çözümlenmiş dosyanın paylaşılan önbelleği.
 *
 * Sayfada iki sahne var — giriş ve özellik gösterisi — ve ikisi de aynı modeli
 * kullanıyor. Önbellek olmasaydı 2,7 MB'lık dosya iki kez indirilip iki kez
 * çözümlenirdi; çözümleme, 95 bin üçgenlik bir taramada ana iş parçacığını
 * gözle görülür süre meşgul eder.
 *
 * Paylaşılan tek şey çözümleme sonucudur. Her sahne kendi geometrisini kopyalar,
 * çünkü kubbe ayrımı ve dünya dönüşümü sahneye özgüdür.
 */
let parsed: Promise<GLTF> | null = null;

function loadOnce(url: string): Promise<GLTF> {
  parsed ??= new GLTFLoader().loadAsync(url);
  return parsed;
}

export async function loadScanRobot(config: ScanModelConfig): Promise<RobotModel> {
  const gltf = await loadOnce(config.url);

  const source = findFirstMesh(gltf.scene);
  if (!source) throw new Error("Model içinde mesh bulunamadı");

  source.updateWorldMatrix(true, false);
  const geometry = source.geometry.clone();
  geometry.applyMatrix4(source.matrixWorld);

  // Tarama NORMAL taşımıyor; ışıklandırma için gerekli.
  if (!geometry.getAttribute("normal")) geometry.computeVertexNormals();

  const material = normalizeMaterial(source.material);
  const { body, dome, domeCenter } = splitAtSeam(geometry, config.domeSeamY);

  geometry.computeBoundingBox();
  const box = geometry.boundingBox!;
  const size = new THREE.Vector3();
  const center = new THREE.Vector3();
  box.getSize(size);
  box.getCenter(center);

  // Kök: taban y=0'a otursun, model yatayda ortalansın.
  const root = new THREE.Group();
  root.name = "robot";

  const offset = new THREE.Vector3(-center.x, -box.min.y, -center.z);

  const bodyMesh = new THREE.Mesh(body, material);
  bodyMesh.name = "robot.body";
  bodyMesh.position.copy(offset);
  bodyMesh.castShadow = true;
  bodyMesh.receiveShadow = true;
  root.add(bodyMesh);

  // Kubbe kendi dikey ekseni etrafında dönmeli: pivot, kubbenin yatay
  // ağırlık merkezine ve dikiş yüksekliğine konur.
  const headPivot = new THREE.Group();
  headPivot.name = "robot.headPivot";
  headPivot.position.set(
    domeCenter.x + offset.x,
    config.domeSeamY + offset.y,
    domeCenter.z + offset.z,
  );
  root.add(headPivot);

  const domeMesh = new THREE.Mesh(dome, material);
  domeMesh.name = "robot.dome";
  domeMesh.position.set(-domeCenter.x, -config.domeSeamY, -domeCenter.z);
  domeMesh.castShadow = true;
  headPivot.add(domeMesh);

  const radius = Math.max(size.x, size.z) / 2;

  return {
    root,
    headAxisHeight: config.domeSeamY + offset.y,
    radius,
    height: size.y,
    setHeadYaw(deg: number) {
      headPivot.rotation.y = THREE.MathUtils.degToRad(deg);
    },
    dispose() {
      body.dispose();
      dome.dispose();
      disposeMaterial(material);
    },
  };
}

function findFirstMesh(root: THREE.Object3D): THREE.Mesh | null {
  let found: THREE.Mesh | null = null;
  root.traverse((child) => {
    if (!found && (child as THREE.Mesh).isMesh) found = child as THREE.Mesh;
  });
  return found;
}

/**
 * Üçgenleri dikişin altında ve üstünde kalanlar diye ayırır.
 *
 * Bir üçgen, ağırlık merkezinin yüksekliğine göre sınıflanır: dikişi kesen
 * üçgenler tek bir tarafa düşer, iki tarafa birden bölünmez. Tarama çözünürlüğünde
 * üçgen kenarı milimetre mertebesinde olduğu için kesik düzgün çıkar.
 */
function splitAtSeam(
  geometry: THREE.BufferGeometry,
  seamY: number,
): { body: THREE.BufferGeometry; dome: THREE.BufferGeometry; domeCenter: THREE.Vector3 } {
  const index = geometry.getIndex();
  if (!index) throw new Error("Model indekssiz; ayırma için indeks gerekli");

  const position = geometry.getAttribute("position");
  const indices = index.array;
  const below: number[] = [];
  const above: number[] = [];

  let domeSumX = 0;
  let domeSumZ = 0;
  let domeCount = 0;

  for (let i = 0; i < indices.length; i += 3) {
    const a = indices[i]!;
    const b = indices[i + 1]!;
    const c = indices[i + 2]!;
    const centroidY = (position.getY(a) + position.getY(b) + position.getY(c)) / 3;

    if (centroidY >= seamY) {
      above.push(a, b, c);
      domeSumX += position.getX(a) + position.getX(b) + position.getX(c);
      domeSumZ += position.getZ(a) + position.getZ(b) + position.getZ(c);
      domeCount += 3;
    } else {
      below.push(a, b, c);
    }
  }

  if (above.length === 0 || below.length === 0) {
    throw new Error(
      `Dikiş y=${seamY} modeli ayırmadı (üst ${above.length}, alt ${below.length} indeks). ` +
        "Dikiş yüksekliği yeniden ölçülmeli.",
    );
  }

  return {
    body: withIndex(geometry, below),
    dome: withIndex(geometry, above),
    domeCenter: new THREE.Vector3(
      domeCount > 0 ? domeSumX / domeCount : 0,
      0,
      domeCount > 0 ? domeSumZ / domeCount : 0,
    ),
  };
}

/** Köşe tamponlarını paylaşan, yalnızca indeksi farklı bir geometri üretir. */
function withIndex(source: THREE.BufferGeometry, indices: number[]): THREE.BufferGeometry {
  const geometry = new THREE.BufferGeometry();
  for (const [name, attribute] of Object.entries(source.attributes)) {
    geometry.setAttribute(name, attribute as THREE.BufferAttribute);
  }
  geometry.setIndex(indices);
  geometry.computeBoundingBox();
  geometry.computeBoundingSphere();
  return geometry;
}

/**
 * Malzemeyi sahnenin ışıklandırmasına uydurur.
 *
 * Taramanın metallicRoughness dokusu 4096² ve 2,26 MB, ama malzemenin
 * `metallicFactor` değeri zaten 0 — doku hiçbir işe yaramadan bellekte duruyor.
 * Kaldırılıyor; parlaklık sabit bir değerle veriliyor.
 */
function normalizeMaterial(input: THREE.Material | THREE.Material[]): THREE.MeshStandardMaterial {
  const first = Array.isArray(input) ? input[0] : input;
  const source = first as THREE.MeshStandardMaterial;

  const material = new THREE.MeshStandardMaterial({
    map: source.map ?? null,
    normalMap: source.normalMap ?? null,
    aoMap: source.aoMap ?? null,
    aoMapIntensity: 0.65,
    metalness: 0.05,
    roughness: 0.62,
  });

  source.metalnessMap?.dispose();
  source.roughnessMap?.dispose();

  return material;
}

/**
 * Malzemeyi bırakır, dokularını bırakmaz.
 *
 * Dokular çözümleme önbelleğinden gelir ve iki sahne tarafından paylaşılır;
 * biri kapanırken onları bırakırsa diğerinin modeli dokusuz kalır. Dokular
 * sayfa ömrü boyunca yaşar — iki küçük doku için bu, yanlış görüntüden iyidir.
 */
function disposeMaterial(material: THREE.MeshStandardMaterial): void {
  material.dispose();
}
