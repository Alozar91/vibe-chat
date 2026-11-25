/**
 * Ринг-звук (§3.12): луп ring.wav через expo-audio + вибрация.
 * Веб делает гудки WebAudio; на мобиле — ассет (создаётся скриптом,
 * 2-тональный European ring, 5 c с паузой). Императивный синглтон —
 * стор вызывает start/stop из anywhere, не привязывая к React-жизненному циклу.
 */

import { createAudioPlayer, setAudioModeAsync, type AudioPlayer } from "expo-audio";
import { Vibration } from "react-native";

// require-ассет (не URI) — Metro вшивает файл в бандл
// eslint-disable-next-line @typescript-eslint/no-require-imports
const RING_SOURCE = require("../../assets/sounds/ring.wav") as number;

let player: AudioPlayer | null = null;
let playing = false;

export const ringPlayer = {
  async start(): Promise<void> {
    if (playing) return;
    playing = true;
    try {
      // звонок важнее музыки: аудиофокус на время ринга (усечённая громкость медиа)
      await setAudioModeAsync({ interruptionMode: "doNotMix", playsInSilentMode: true });
      player = player ?? createAudioPlayer(RING_SOURCE);
      player.loop = true;
      player.volume = 1;
      player.seekTo(0);
      player.play();
      Vibration.vibrate([0, 500, 800, 500, 800, 500, 1500], true);
    } catch {
      // нет аудио-выхода (редко) — вибрация уже запущена
    }
  },
  stop(): void {
    if (!playing) return;
    playing = false;
    try {
      player?.pause();
    } catch {
      // плеер уже мёртв
    }
    Vibration.cancel();
  },
};
