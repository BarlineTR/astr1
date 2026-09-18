import * as THREE from "three";
import { OrbitControls } from "three/examples/jsm/controls/OrbitControls.js";

import { CAMERA_HFOV_DEG, CAMERA_VFOV_DEG, AUDIO_REACHABLE_DEG } from "../../../shared/limits";
import { createBearingRing } from "./bearing-ring";
import { createFovFrustum } from "./fov-frustum";
import { HERO_MODEL, loadScanRobot, type RobotModel } from "./robot-model";
import { IDLE_STATE, type SceneDriver, type SceneState } from "../../../shared/scene-state";

const ACCENT = 0xc8a15a;
const ACCENT_ACTIVE = 0xe0bd7c;

export interface RobotScene {
  setDriver(driver: SceneDriver | null): void;
  /**
   * Modelin çerçevedeki yatay yerini ayarlar: 0 ortalı, 1 tamamen sağda.
   *
   * Açılış animasyonu bunu 0'dan 1'e sürer — model ortada büyük başlar, sonra
   * sağa kayar ve solda metne yer açar.
   */
  setComposition(amount: number): void;
  /** Sürücü yokken sahneyi doğrudan sürmek için — konsol bunu kullanır. */
  apply(state: SceneState): void;
  start(): void;
  stop(): void;
  dispose(): void;
}

export interface RobotSceneOptions {
  /** Kamera kendi kendine dönsün mü. Azaltılmış hareket tercihinde kapatılır. */
  autoOrbit?: boolean;
  /** Kullanıcı fareyle döndürebilsin mi. */
  interactive?: boolean;
  /**
   * Model çerçevenin sağına kaydırılsın mı.
   *
   * Girişte solda metin olduğu için gerekir. Konsolda sahne kendi panelinde tek
   * başına durur; orada kaydırma modeli sebepsiz yere kenara iter.
   */
  offsetSubject?: boolean;
}

export async function createRobotScene(
  container: HTMLElement,
  options: RobotSceneOptions = {},
): Promise<RobotScene> {
  const reducedMotion = window.matchMedia("(prefers-reduced-motion: reduce)").matches;
  const autoOrbit = (options.autoOrbit ?? true) && !reducedMotion;
  const interactive = options.interactive ?? true;
  let compositionAmount = options.offsetSubject === false ? 0 : 1;

  /**
   * Dokunmatik cihazlarda döndürme kapalıdır.
   *
   * Tuval giriş bölümünün tamamını kapladığı için, OrbitControls dokunuşu
   * yakaladığında sayfa dikey olarak kaydırılamaz hale geliyordu: ziyaretçi
   * ilk ekranda kilitli kalırdı. Masaüstünde fare ile döndürme açık kalır.
   */
  const coarsePointer = window.matchMedia("(pointer: coarse)").matches;

  /**
   * Yan yana yerleşim yalnızca geniş ekranda vardır.
   *
   * Kaydırma, solda metin olduğu için gerekli — yani kararı veren şey sayfa
   * düzenidir, tuvalin biçimi değil. Önce tuvalin en-boy oranına bakılıyordu ve
   * bu, dar ekranda yanlış cevap veriyordu: mobilde sahne geniş ve kısa bir
   * şerit (yaklaşık 375×225, oran 1,67) olduğu için eşiği geçiyor, model yanında
   * hiç metin yokken sağa itiliyordu. Eşik artık CSS'teki 60rem kırılma
   * noktasının aynısı.
   */
  const wideLayout = window.matchMedia("(min-width: 60rem)");

  const renderer = new THREE.WebGLRenderer({
    antialias: true,
    alpha: true,
    powerPreference: "high-performance",
  });
  renderer.setPixelRatio(Math.min(window.devicePixelRatio, 2));
  renderer.outputColorSpace = THREE.SRGBColorSpace;
  renderer.toneMapping = THREE.ACESFilmicToneMapping;
  renderer.toneMappingExposure = 1.05;
  renderer.shadowMap.enabled = true;
  renderer.shadowMap.type = THREE.PCFSoftShadowMap;
  renderer.domElement.style.display = "block";
  renderer.domElement.style.width = "100%";
  renderer.domElement.style.height = "100%";
  container.appendChild(renderer.domElement);

  const scene = new THREE.Scene();
  const camera = new THREE.PerspectiveCamera(32, 1, 0.05, 40);

  const robot = await loadScanRobot(HERO_MODEL);
  scene.add(robot.root);

  addLighting(scene, robot);
  const ground = createGroundShadow(robot.radius * 4.2);
  scene.add(ground.mesh);

  // Görüş hacmi kafayla döner; kerteriz halkası gövdede sabit kalır.
  const frustum = createFovFrustum({
    hfovDeg: CAMERA_HFOV_DEG,
    vfovDeg: CAMERA_VFOV_DEG,
    length: robot.radius * 1.7,
    color: ACCENT,
  });
  const frustumCarrier = new THREE.Group();
  frustumCarrier.position.y = robot.headAxisHeight + robot.height * 0.14;
  frustumCarrier.add(frustum.group);
  robot.root.add(frustumCarrier);

  const ring = createBearingRing({
    radius: robot.radius * 1.75,
    color: ACCENT,
    reachableDeg: AUDIO_REACHABLE_DEG,
  });
  ring.group.position.y = 0.004;
  robot.root.add(ring.group);

  const controls = new OrbitControls(camera, renderer.domElement);
  controls.enableDamping = true;
  controls.dampingFactor = 0.06;
  controls.enableZoom = false;
  controls.enablePan = false;
  controls.enabled = interactive && !coarsePointer;
  controls.autoRotate = autoOrbit;
  controls.autoRotateSpeed = 0.42;
  controls.minPolarAngle = THREE.MathUtils.degToRad(56);
  controls.maxPolarAngle = THREE.MathUtils.degToRad(86);
  controls.target.set(0, robot.height * 0.52, 0);

  camera.position.set(robot.radius * 4.6, robot.height * 1.15, robot.radius * 6.4);
  controls.update();

  let driver: SceneDriver | null = null;
  let running = false;
  let frame = 0;
  let lastTime = 0;
  let visible = true;

  // Sekme arkadayken ya da bölüm ekranda değilken çizmenin anlamı yok.
  const intersection = new IntersectionObserver(
    ([entry]) => {
      visible = entry?.isIntersecting ?? true;
    },
    { threshold: 0.01 },
  );
  intersection.observe(container);

  /**
   * Modeli çerçevenin sağına kaydırır.
   *
   * Yörünge merkezi modelin kendisinde kalmalı — modeli dünyada yana taşımak,
   * kamera döndükçe onu çerçevede gezdirirdi. Bunun yerine izdüşüm kaydırılıyor:
   * model kendi ekseninde dönmeye devam ediyor, yalnızca çerçevedeki yeri
   * değişiyor. Dar ekranda kaydırma yok; orada sahne metnin üstünde değil,
   * altında durur.
   */
  function applyComposition(width: number, height: number): void {
    if (compositionAmount <= 0.001 || !wideLayout.matches) {
      camera.clearViewOffset();
      return;
    }
    const shift = width * 0.17 * compositionAmount;
    camera.setViewOffset(width, height, -shift, 0, width, height);
  }

  /**
   * Kamerayı modelin kadraja sığacağı uzaklığa çeker.
   *
   * Sabit bir uzaklık yazılamaz: aynı sahne hem geniş bir giriş bölümünde hem de
   * konsolun dar ve uzun panelinde çalışıyor. Dar çerçevede yatay sığdırma
   * belirleyici olur, geniş çerçevede dikey. İkisinin gerektirdiği uzaklıktan
   * büyüğü seçilir; yön OrbitControls'ün getirdiği yerde kalır, yalnızca
   * uzunluk değişir.
   */
  function frameSubject(aspect: number): void {
    const halfFov = THREE.MathUtils.degToRad(camera.fov) / 2;
    // Çarpanlar modelin çerçeveyi ne kadar dolduracağını belirler. 0.85 ve 3.2,
    // giriş bölümünün geniş çerçevesinde modeli rakam şeridinin üstünde tutan,
    // konsolun dar panelinde ise taşırmayan değerler.
    const forHeight = (robot.height * 0.85) / Math.tan(halfFov);
    const forWidth = (robot.radius * 3.2) / (Math.tan(halfFov) * Math.max(aspect, 0.4));
    const distance = Math.max(forHeight, forWidth);

    const direction = camera.position.clone().sub(controls.target).normalize();
    camera.position.copy(controls.target).addScaledVector(direction, distance);
    controls.update();
  }

  const resize = new ResizeObserver(() => {
    const { clientWidth, clientHeight } = container;
    if (clientWidth === 0 || clientHeight === 0) return;
    renderer.setSize(clientWidth, clientHeight, false);
    camera.aspect = clientWidth / clientHeight;
    applyComposition(clientWidth, clientHeight);
    camera.updateProjectionMatrix();
    frameSubject(camera.aspect);

    // Yeni ölçüyle hemen bir kare çiz. Çizim döngüsüne bırakılırsa, sekme arka
    // plandayken `requestAnimationFrame` durduğu için tuval eski çerçeveleme ile
    // asılı kalır ve boyut değişikliği görünmez.
    renderer.render(scene, camera);
  });
  resize.observe(container);

  function apply(state: SceneState): void {
    robot.setHeadYaw(state.headYawDeg);
    frustumCarrier.rotation.y = THREE.MathUtils.degToRad(state.headYawDeg);
    frustum.setActive(state.faceVisible);
    frustum.setColor(state.faceVisible ? ACCENT_ACTIVE : ACCENT);
    ring.setBearing(state.doaDeg, state.vad ? 1 : 0.25);

    // Döngü durmuşken çağıran tek bir durum uygulayabilmeli ve sonucu görebilmeli:
    // duraklatılmış konsol, azaltılmış hareket tercihi ve statik poz bunu gerektirir.
    if (!running) renderer.render(scene, camera);
  }

  function tick(now: number): void {
    if (!running) return;
    frame = requestAnimationFrame(tick);

    const dt = lastTime === 0 ? 0 : Math.min((now - lastTime) / 1000, 0.1);
    lastTime = now;

    if (!visible) return;

    if (driver) apply(driver.update(dt));
    controls.update();
    renderer.render(scene, camera);
  }

  apply(IDLE_STATE);
  const width0 = container.clientWidth || 1;
  const height0 = container.clientHeight || 1;
  renderer.setSize(width0, height0, false);
  camera.aspect = width0 / height0;
  applyComposition(width0, height0);
  camera.updateProjectionMatrix();
  frameSubject(camera.aspect);
  renderer.render(scene, camera);

  return {
    setDriver(next) {
      driver = next;
    },
    setComposition(amount) {
      compositionAmount = Math.min(1, Math.max(0, amount));
      const { clientWidth, clientHeight } = container;
      if (clientWidth === 0 || clientHeight === 0) return;
      applyComposition(clientWidth, clientHeight);
      camera.updateProjectionMatrix();
      if (!running) renderer.render(scene, camera);
    },
    apply,
    start() {
      if (running) return;
      running = true;
      lastTime = 0;
      frame = requestAnimationFrame(tick);
    },
    stop() {
      running = false;
      cancelAnimationFrame(frame);
    },
    dispose() {
      running = false;
      cancelAnimationFrame(frame);
      intersection.disconnect();
      resize.disconnect();
      controls.dispose();
      frustum.dispose();
      ring.dispose();
      ground.dispose();
      robot.dispose();
      renderer.dispose();
      renderer.domElement.remove();
    },
  };
}

/**
 * Işıklandırma: koyu bir stüdyo.
 *
 * Tarama dokusu üzerinde pişmiş aydınlatma taşır, bu yüzden sahne ışığı modeli
 * yeniden aydınlatmaz — yalnızca biçimi ayırır. Arkadan gelen pirinç kenar ışığı
 * modeli siyah zeminden koparan asıl unsurdur.
 */
function addLighting(scene: THREE.Scene, robot: RobotModel): void {
  scene.add(new THREE.HemisphereLight(0x222833, 0x08080a, 0.55));

  const key = new THREE.DirectionalLight(0xf2efe8, 1.15);
  key.position.set(robot.radius * 5, robot.height * 3.4, robot.radius * 4.2);
  key.castShadow = true;
  key.shadow.mapSize.set(1024, 1024);
  key.shadow.camera.near = 0.1;
  key.shadow.camera.far = 8;
  key.shadow.bias = -0.0015;
  const extent = robot.radius * 3;
  key.shadow.camera.left = -extent;
  key.shadow.camera.right = extent;
  key.shadow.camera.top = extent;
  key.shadow.camera.bottom = -extent;
  scene.add(key);

  const rim = new THREE.DirectionalLight(ACCENT, 1.7);
  rim.position.set(-robot.radius * 5.5, robot.height * 1.5, -robot.radius * 6);
  scene.add(rim);

  const fill = new THREE.DirectionalLight(0x7f9bbd, 0.38);
  fill.position.set(-robot.radius * 4, robot.height * 0.7, robot.radius * 3.5);
  scene.add(fill);
}

/** Zemine oturmuş hissi veren yumuşak temas gölgesi. */
function createGroundShadow(size: number): { mesh: THREE.Mesh; dispose(): void } {
  const canvas = document.createElement("canvas");
  canvas.width = canvas.height = 256;
  const context = canvas.getContext("2d")!;
  const gradient = context.createRadialGradient(128, 128, 0, 128, 128, 128);
  gradient.addColorStop(0, "rgba(0,0,0,0.62)");
  gradient.addColorStop(0.45, "rgba(0,0,0,0.26)");
  gradient.addColorStop(1, "rgba(0,0,0,0)");
  context.fillStyle = gradient;
  context.fillRect(0, 0, 256, 256);

  const texture = new THREE.CanvasTexture(canvas);
  texture.colorSpace = THREE.SRGBColorSpace;

  const geometry = new THREE.PlaneGeometry(size, size);
  geometry.rotateX(-Math.PI / 2);
  const material = new THREE.MeshBasicMaterial({
    map: texture,
    transparent: true,
    depthWrite: false,
  });

  const mesh = new THREE.Mesh(geometry, material);
  mesh.position.y = 0.001;
  mesh.renderOrder = 1;

  return {
    mesh,
    dispose() {
      geometry.dispose();
      material.dispose();
      texture.dispose();
    },
  };
}
