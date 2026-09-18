import "../styles/tokens.css";
import "../styles/base.css";
import "../styles/layout.css";
import "../styles/console.css";

import { connectTelemetry } from "../console/telemetry";
import { renderConsole } from "../pages/console";

const root = document.querySelector<HTMLElement>("#app");
if (!root) throw new Error("#app bulunamadı");

const view = renderConsole(root);

/**
 * Sahne ile telemetri birbirini beklemez: sahne yüklenemese de sayısal değerler
 * akmaya devam eder, telemetri gelmese de sahne boşta durumunda durur.
 */
let applyToScene: ((state: { headYawDeg: number; doaDeg: number | null; vad: boolean; faceVisible: boolean }) => void) | null = null;

void (async () => {
  try {
    const { createRobotScene } = await import("../scene/robot-scene");
    const scene = await createRobotScene(view.stageEl, { autoOrbit: false, offsetSubject: false });
    scene.start();
    applyToScene = scene.apply;
  } catch (error) {
    console.error("Konsol sahnesi yüklenemedi:", error);
  }
})();

connectTelemetry((source) => {
  view.bind((command) => source.send(command), source.kind);
  source.onTelemetry((telemetry) => {
    view.update(telemetry);
    applyToScene?.({
      // Sahne encoder gerçeğini gösterir, istenen açıyı değil.
      headYawDeg: telemetry.head.actualYawDeg,
      doaDeg: telemetry.audio.doaDeg,
      vad: telemetry.audio.vad,
      faceVisible: telemetry.gaze.visualValid,
    });
  });
});
