/** UUID v4 через expo-crypto (без внешних зависимостей). */

import * as Crypto from "expo-crypto";

export function randomUUID(): string {
  return Crypto.randomUUID();
}
