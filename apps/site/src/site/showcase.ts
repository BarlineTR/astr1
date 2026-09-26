import * as THREE from "three";

import { SHOWCASE } from "../data/icerik";
import type { FocusTarget, RobotScene } from "../scene/robot-scene";

/**
 * Özellikleri modelin üzerinde tek tek gösteren kaydırma anlatısı.
 *
 * Sahne yapışkan olarak ekranda kalır, metin adımları onun üzerinden akar.
 * Etkin adımı belirleyen şey adım kutusunun nerede olduğu değil, **metnin
 * okuma alanına varıp varmadığıdır**.
 *
 * Bu ayrım kritik: adımlar tam ekran yüksekliğinde olduğu için kutuya bakan bir
 * ölçüt, metin daha ekranın altındayken adımı etkinleştiriyordu — animasyon,
 * okuyucu o bölüme varmadan başlıyordu. Metin ölçüsüne bakınca tetikleme,
 * yazının gerçekten okunabilir hale geldiği ana denk gelir.
 *
 * İki adım arasında, öncekinin metni yukarı çıkmış ama sonrakininki henüz
 * gelmemişken bir boşluk vardır. Orada kamera yerinde bırakılır ve yalnızca
 * işaret gizlenir; kamerayı genel görünüme döndürmek, her adım arasında
 * gidip gelen bir sarsıntı üretirdi.
 */
export interface ShowcaseController {
  stop(): void;
}

/** Dar ekran eşiği — CSS'teki kırılma noktasının aynısı. */
const COMPACT_QUERY = "(max-width: 60rem)";

/**
 * Dar ekranda bütün adımlar aynı çerçeveyi paylaşır.
 *
 * Küçük ekranda her parçaya ayrı ayrı yaklaşmak modeli tanınmaz hale getiriyor:
 * ekranda yalnızca bir kubbe parçası ya da bir teker kalıyor. Bunun yerine model
 * sabit ölçekte ve sabit yükseklikte durur, adımlar arasında yalnızca hafifçe
 * döner; hangi parçadan söz edildiğini işaret gösterir.
 */
const COMPACT_VIEW = {
  pointHeightRatio: 0.52,
  distanceScale: 2.6,
  polarDeg: 82,
  /** Adımlar arasındaki toplam dönüş genişliği (derece). */
  azimuthSpreadDeg: 10,
};

export function startShowcase(options: {
  scene: RobotScene;
  steps: HTMLElement[];
  markEl: HTMLElement;
  markLabelEl: HTMLElement;
  stageEl: HTMLElement;
}): ShowcaseController {
  const { scene, steps, markEl, markLabelEl, stageEl } = options;
  const { height, radius } = scene.metrics;

  /** Oransal çapaları modelin gerçek ölçülerine çevirir. */
  const anchors = SHOWCASE.map(
    (step) =>
      new THREE.Vector3(step.anchor.x * radius, step.anchor.y * height, step.anchor.z * radius),
  );

  const compact = window.matchMedia(COMPACT_QUERY);

  let active = -1;
  /**
   * Sahneye en son verilen adım ve o sıradaki yerleşim kipi.
   *
   * `-1` ile başlar, çünkü sahne zaten genel görünümdedir: hiçbir adım etkin
   * değilken açılışta gereksiz bir "genel görünüme dön" komutu gitmemeli.
   *
   * Kip de saklanır, çünkü dar ve geniş ekran aynı adım için farklı çerçeve
   * kullanır. Yalnızca indekse bakılsaydı, kırılma noktası aşıldığında adım
   * değişmediği için kamera eski çerçevede kalırdı.
   */
  let applied = -1;
  let appliedCompact = compact.matches;
  let pendingFrame = 0;
  let stopped = false;

  /**
   * Okuma alanının üst sınırı: başlık şeridinin altı.
   *
   * Şerit yapışkan olduğu için metnin onun arkasına girmesi okumayı bozar;
   * "geldi" sayılması için metnin şeridin altında kalması gerekir.
   */
  function readingTop(): number {
    const header = document.querySelector(".site-header");
    const top = header ? header.getBoundingClientRect().bottom : 0;

    if (!compact.matches) return top;

    /*
     * Telefonda sahne ekranın üstüne sabitlenir ve metin onun altından akar.
     * Okuma alanı da orada başlar: sahnenin arkasına girmiş bir yazı, başlık
     * şeridinin altında olsa bile okunmuyordur.
     */
    const stage = document.querySelector(".showcase__sticky");
    return stage ? Math.max(top, stage.getBoundingClientRect().bottom) : top;
  }

  interface Placement {
    /** Metin tamamen ekrana girdi mi (alt kenarı görünür alanda). */
    arrived: boolean;
    /** Metin okuma alanının içinde mi — hem geldi hem henüz yukarı çıkmadı. */
    reading: boolean;
  }

  function placementOf(step: HTMLElement, viewportHeight: number, top: number): Placement {
    const content = step.querySelector<HTMLElement>(".step__inner");
    const rect = step.getBoundingClientRect();
    const contentTop = rect.top + (content?.offsetTop ?? 0);
    const contentBottom = contentTop + (content?.offsetHeight ?? 0);

    return {
      arrived: contentBottom <= viewportHeight,
      reading: contentBottom <= viewportHeight && contentTop >= top,
    };
  }

  /**
   * Konumdan etkin adımı hesaplar.
   *
   * Sonuç yalnızca o anki konuma bağlıdır, geçmişe değil: aynı yerde aşağı
   * inerken de yukarı çıkarken de aynı adım seçilir. Etkin adım, metni okuma
   * alanına ulaşmış **en son** adımdır; bir sonrakinin metni gelene kadar o
   * kalır.
   */
  function measure(): { index: number; reading: boolean } {
    const viewportHeight = window.innerHeight;
    const top = readingTop();

    const last = steps[steps.length - 1];
    if (last && last.getBoundingClientRect().bottom <= 0) {
      // Anlatı tamamen yukarıda kaldı.
      return { index: -1, reading: false };
    }

    let index = -1;
    let reading = false;
    for (const [i, step] of steps.entries()) {
      const placement = placementOf(step, viewportHeight, top);
      if (!placement.arrived) continue;
      index = i;
      reading = placement.reading;
      if (placement.reading) step.classList.add("is-seen");
    }

    return { index, reading };
  }

  function targetFor(index: number): FocusTarget {
    const step = SHOWCASE[index]!;

    if (compact.matches) {
      const spread = COMPACT_VIEW.azimuthSpreadDeg;
      const span = Math.max(SHOWCASE.length - 1, 1);
      return {
        point: new THREE.Vector3(0, height * COMPACT_VIEW.pointHeightRatio, 0),
        azimuthDeg: -spread / 2 + (spread * index) / span,
        polarDeg: COMPACT_VIEW.polarDeg,
        distance: height * COMPACT_VIEW.distanceScale,
      };
    }

    return {
      point: anchors[index]!.clone(),
      azimuthDeg: step.camera.azimuthDeg,
      polarDeg: step.camera.polarDeg,
      distance: step.camera.distanceScale * height,
    };
  }

  /** Kamera komutunu uygular. Adım değişmediyse hiçbir şey göndermez. */
  function applyFocus(): void {
    if (stopped) return;

    const nowCompact = compact.matches;
    if (applied === active && appliedCompact === nowCompact) return;

    applied = active;
    appliedCompact = nowCompact;
    scene.focus(active < 0 ? null : targetFor(active));
  }

  /**
   * Kamera komutu bir sonraki kareye ertelenir.
   *
   * Hızlı kaydırmada tek bir hareketle birkaç adım birden geçilebilir; her biri
   * için komut gönderilseydi kamera aradaki noktalara uğrayıp sarsılırdı.
   * Erteleme, yalnızca son hedefin uygulanmasını sağlar.
   */
  function scheduleFocus(): void {
    if (stopped || pendingFrame) return;
    pendingFrame = requestAnimationFrame(() => {
      pendingFrame = 0;
      applyFocus();
    });
  }

  /** Sınıfları, etiketi ve işareti hemen günceller; kamerayı erteler. */
  function update(immediate = false): void {
    if (stopped) return;

    const { index, reading } = measure();
    active = index;

    for (const [i, step] of steps.entries()) {
      step.classList.toggle("is-active", i === index);
    }

    if (index >= 0) markLabelEl.textContent = SHOWCASE[index]!.label;
    markEl.classList.toggle("is-visible", index >= 0 && reading);

    if (immediate) applyFocus();
    else scheduleFocus();
  }

  const onChange = (): void => update();

  window.addEventListener("scroll", onChange, { passive: true });
  window.addEventListener("resize", onChange);
  compact.addEventListener("change", onChange);

  /*
   * Metnin kendi yüksekliği değişince de yeniden ölçülmeli.
   *
   * Yazı tipi geç yüklendiğinde ya da satır sayısı değiştiğinde adım kutusunun
   * boyu aynı kalır ama metnin kutu içindeki yeri kayar; pencere ölçüsüne bakan
   * bir dinleyici bunu hiç görmez.
   */
  const reflow = new ResizeObserver(() => update());
  for (const step of steps) {
    const content = step.querySelector<HTMLElement>(".step__inner");
    if (content) reflow.observe(content);
  }

  /*
   * Adım metinleri yalnızca gösteri gerçekten çalışırken gizlenir.
   *
   * Gizleme CSS'te koşulsuz yapılsaydı ve gösteri hiç başlamasaydı — sahne
   * yüklenemediğinde ya da betik çalışmadığında — bütün özellik metinleri
   * kalıcı olarak görünmez kalırdı.
   */
  const list = steps[0]?.parentElement;
  list?.classList.add("is-driven");

  /*
   * Sayfa zaten kaydırılmış olabilir: model geç yüklendiğinde okuyucu çoktan
   * üçüncü adımda olabilir. Başlangıç durumu ertelenmeden uygulanır ki sahne
   * açıldığı anda doğru yere bakıyor olsun.
   */
  update(true);

  // İşaret her karede güncellenir: kamera hareket ettikçe çapanın ekrandaki yeri
  // de değişir, sabit bir konum bir kare sonra yanlış olurdu.
  scene.onFrame(() => {
    if (active < 0) return;
    const anchor = anchors[active];
    if (!anchor) return;

    const projected = scene.project(anchor);
    const inside =
      projected.inFront &&
      projected.x > 0 &&
      projected.y > 0 &&
      projected.x < stageEl.clientWidth &&
      projected.y < stageEl.clientHeight;

    markEl.classList.toggle("is-offscreen", !inside);
    markEl.style.transform = `translate3d(${projected.x}px, ${projected.y}px, 0)`;
  });

  return {
    stop() {
      stopped = true;
      if (pendingFrame) cancelAnimationFrame(pendingFrame);
      pendingFrame = 0;
      window.removeEventListener("scroll", onChange);
      window.removeEventListener("resize", onChange);
      compact.removeEventListener("change", onChange);
      reflow.disconnect();
      list?.classList.remove("is-driven");
      scene.onFrame(null);
      scene.focus(null);
      markEl.classList.remove("is-visible");
    },
  };
}
