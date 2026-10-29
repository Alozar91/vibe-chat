const KEY = "vibe.seq.v1";

export function loadSeqSnapshot(): Record<string, number> {
  try {
    const raw = localStorage.getItem(KEY);
    if (!raw) return {};
    const parsed = JSON.parse(raw) as Record<string, number>;
    return typeof parsed === "object" && parsed !== null ? parsed : {};
  } catch {
    return {};
  }
}

export function updateSeqSnapshot(chatId: string, lastSeq: number) {
  const snapshot = loadSeqSnapshot();
  if ((snapshot[chatId] || 0) >= lastSeq) return;
  snapshot[chatId] = lastSeq;
  try {
    localStorage.setItem(KEY, JSON.stringify(snapshot));
  } catch {
    return;
  }
}

export function collectSyncChats(): { chat_id: string; last_seq: number }[] {
  return Object.entries(loadSeqSnapshot()).map(([chat_id, last_seq]) => ({
    chat_id,
    last_seq,
  }));
}
