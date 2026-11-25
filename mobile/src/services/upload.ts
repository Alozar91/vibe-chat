/**
 * Upload-флоу Silo (§3.4, §8 концепции): upload-url → presigned PUT → complete.
 * PUT напрямую в Silo (без проксирования); прогресс + отмена через XMLHttpRequest.
 * Лимит размера проверяется ДО запроса upload-url (DoD этапа 5).
 */

import * as FileSystem from "expo-file-system";
import { filesApi } from "../api/endpoints";
import { apiClient } from "./api-client";
import { Sha256 } from "./sha256";

export const MAX_FILE_BYTES = 100 * 1024 * 1024; // MVP: 100 МБ (§12, конфиг бэкенда)

const CHUNK_BYTES = 512 * 1024; // чанки чтения файла для sha256

export interface PickedFileInfo {
  /** локальный uri (file://) из expo-image-picker / DocumentPicker */
  uri: string;
  size: number;
  fileName: string;
  mimeType: string;
}

export interface UploadResult {
  fileId: string;
  realMimeType: string | null;
  thumbKey: string | null;
  blurhash: string | null;
}

export interface UploadHandle {
  promise: Promise<UploadResult>;
  abort: () => void;
}

export class FileTooLargeError extends Error {}

/** MIME по расширению — ориентир для presign; сервер пересматривает sniffing'ом (§8). */
function guessMime(fileName: string): string {
  const ext = fileName.split(".").pop()?.toLowerCase() ?? "";
  const map: Record<string, string> = {
    jpg: "image/jpeg",
    jpeg: "image/jpeg",
    png: "image/png",
    gif: "image/gif",
    webp: "image/webp",
    heic: "image/heic",
    mp4: "video/mp4",
    mov: "video/quicktime",
    pdf: "application/pdf",
    txt: "text/plain",
    zip: "application/zip",
  };
  return map[ext] ?? "application/octet-stream";
}

/** SHA-256 (hex) файла — чанковое чтение, инкрементальный хэш (не грузим файл целиком). */
async function sha256FileHex(uri: string): Promise<string> {
  const info = await FileSystem.getInfoAsync(uri);
  if (!info.exists) throw new Error("file not found");
  const hasher = new Sha256();
  for (let position = 0; position < info.size; position += CHUNK_BYTES) {
    const b64 = await FileSystem.readAsStringAsync(uri, {
      encoding: FileSystem.EncodingType.Base64,
      position,
      length: CHUNK_BYTES,
    });
    // base64 → байты (RuntimeJS: atob нет в Hermes, декодируем вручную)
    hasher.update(base64ToBytes(b64));
  }
  return hasher.finishHex();
}

function base64ToBytes(b64: string): Uint8Array {
  const clean = b64.replace(/[\r\n]/g, "");
  const len = clean.length;
  const bytes = new Uint8Array(Math.floor((len * 3) / 4));
  let out = 0;
  let buf = 0;
  let bits = 0;
  for (let i = 0; i < len; i++) {
    const c = clean.charCodeAt(i);
    let v: number;
    if (c >= 65 && c <= 90) v = c - 65;
    else if (c >= 97 && c <= 122) v = c - 71;
    else if (c >= 48 && c <= 57) v = c + 4;
    else if (c === 43) v = 62;
    else if (c === 47) v = 63;
    else continue; // '=' и мусор
    buf = (buf << 6) | v;
    bits += 6;
    if (bits >= 8) {
      bits -= 8;
      bytes[out++] = (buf >> bits) & 0xff;
    }
  }
  return bytes.subarray(0, out);
}

/**
 * Полный upload-флоу. onProgress — 0..100 (по байтам PUT).
 * > 100 МБ → FileTooLargeError до upload-url (DoD: отклонение до PUT).
 */
export function uploadFile(
  info: PickedFileInfo,
  onProgress?: (percent: number) => void,
): UploadHandle {
  let abortXhr: (() => void) | null = null;
  const promise = (async (): Promise<UploadResult> => {
    // Лимит ДО чтения файла: fetch(content://) на >100 МБ падает в RN (Blob
    // memory-backed → OOM, «Network request failed») — отклоняем по данным
    // пикера ещё до fetch (DoD этапа 5); точная проверка — по blob.size ниже
    if (info.size > MAX_FILE_BYTES) {
      throw new FileTooLargeError(
        `Файл ${info.size} байт превышает лимит ${MAX_FILE_BYTES}`,
      );
    }
    // Blob сначала: asset.fileSize из пикера врёт (content:// → blob другого размера),
    // а подпись S3v4 требует точного Content-Length → size берём только из blob.size
    const blob = await (await fetch(info.uri)).blob();
    if (blob.size <= 0 || blob.size > MAX_FILE_BYTES) {
      throw new FileTooLargeError(
        `Файл ${blob.size} байт превышает лимит ${MAX_FILE_BYTES}`,
      );
    }

    const sha256 = await sha256FileHex(info.uri);
    const mime = info.mimeType || guessMime(info.fileName);
    const { file_id, upload_url } = await filesApi.uploadUrl(blob.size, mime, sha256);

    // PUT через XHR: Blob из fetch(file://) стримится с диска (не в память JS);
    // upload.onprogress + abort() — прогресс и отмена (DoD этапа 5)
    await new Promise<void>((resolve, reject) => {
      const xhr = new XMLHttpRequest();
      xhr.open("PUT", upload_url);
      xhr.setRequestHeader("Content-Type", mime);
      xhr.upload.onprogress = (e) => {
        if (e.lengthComputable && onProgress) {
          onProgress(Math.round((e.loaded / e.total) * 100));
        }
      };
      xhr.onload = () => {
        if (xhr.status >= 200 && xhr.status < 300) resolve();
        else reject(new Error(`Silo PUT failed: ${xhr.status}`));
      };
      xhr.onerror = () => reject(new Error("Silo PUT network error"));
      xhr.onabort = () => reject(new Error("upload aborted"));
      abortXhr = () => xhr.abort();
      xhr.send(blob);
    });

    // complete: сервер делает HEAD + sniffing + thumbnail/blurhash (§8)
    const file = await filesApi.complete(file_id);
    return {
      fileId: file.id,
      realMimeType: file.real_mime_type,
      thumbKey: file.thumb_key,
      blurhash: file.blurhash,
    };
  })();

  return {
    promise,
    abort: () => {
      abortXhr?.();
      // отмена до PUT: rejecting promise
      abortXhr = null;
    },
  };
}

/** Свежий presigned GET (URL из сообщений TTL-ограничены, §8). */
export function fileUrl(fileId: string): Promise<string> {
  return apiClient.get<{ url: string; expires_in: number }>(`/files/${fileId}/url`).then((r) => r.url);
}
