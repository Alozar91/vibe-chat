/**
 * Токены — только в защищённом хранилище (Docs/android.md §3.2):
 * react-native-keychain → Android Keystore. Никогда в MMKV/AsyncStorage.
 */

import * as Keychain from "react-native-keychain";

const SERVICE = "ru.vibe.chat.app.session";

export interface StoredTokens {
  access_token: string;
  refresh_token: string;
  /** epoch ms, когда access истекает (оценка KC exp_in) */
  access_expires_at: number;
}

export async function saveTokens(tokens: StoredTokens): Promise<void> {
  await Keychain.setGenericPassword(
    SERVICE,
    JSON.stringify(tokens),
    {
      service: SERVICE,
      accessible: Keychain.ACCESSIBLE.WHEN_UNLOCKED,
      securityLevel: Keychain.SECURITY_LEVEL.ANY,
    }
  );
}

export async function loadTokens(): Promise<StoredTokens | null> {
  const creds = await Keychain.getGenericPassword({ service: SERVICE });
  if (!creds || !creds.password) return null;
  try {
    return JSON.parse(creds.password) as StoredTokens;
  } catch {
    return null;
  }
}

export async function clearTokens(): Promise<void> {
  await Keychain.resetGenericPassword({ service: SERVICE });
}
