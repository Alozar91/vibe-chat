import { mediaApi } from "../../api/endpoints";
import { ApiError } from "../../api/client";

export const MAX_FILE_SIZE = 100 * 1024 * 1024;
export const MAX_ATTACHMENTS = 10;

export interface UploadResult {
  file_id: string;
  name: string;
  mime_type: string;
  size_bytes: number;
}

export function validateFile(file: File, existingCount: number): string | null {
  if (existingCount >= MAX_ATTACHMENTS) return `Не более ${MAX_ATTACHMENTS} вложений на сообщение`;
  if (file.size > MAX_FILE_SIZE) return `Файл «${file.name}» больше 100 МБ`;
  if (file.size === 0) return `Файл «${file.name}» пуст`;
  return null;
}

export function uploadFile(
  file: File,
  onProgress: (percent: number) => void,
  signal?: AbortSignal,
): Promise<UploadResult> {
  return (async () => {
    const intent = await mediaApi.uploadIntent(file.name, file.type || "application/octet-stream", file.size);
    await putToPresigned(intent.upload_url, file, intent.headers, onProgress, signal);
    await mediaApi.uploadComplete(intent.file_id);
    return {
      file_id: intent.file_id,
      name: file.name,
      mime_type: file.type || "application/octet-stream",
      size_bytes: file.size,
    };
  })();
}

function putToPresigned(
  url: string,
  file: File,
  headers: Record<string, string>,
  onProgress: (percent: number) => void,
  signal?: AbortSignal,
): Promise<void> {
  return new Promise((resolve, reject) => {
    const xhr = new XMLHttpRequest();
    xhr.open("PUT", url);
    for (const [key, value] of Object.entries(headers)) {
      try {
        xhr.setRequestHeader(key, value);
      } catch {
        return reject(new ApiError(0, "upload_error", "Не удалось задать заголовок загрузки"));
      }
    }
    xhr.upload.onprogress = (event) => {
      if (event.lengthComputable) {
        onProgress(Math.round((event.loaded / event.total) * 100));
      }
    };
    xhr.onload = () => {
      if (xhr.status >= 200 && xhr.status < 300) resolve();
      else reject(new ApiError(xhr.status, "upload_error", `Ошибка загрузки файла (${xhr.status})`));
    };
    xhr.onerror = () => reject(new ApiError(0, "network_error", "Нет связи с хранилищем"));
    xhr.onabort = () => reject(new DOMException("Upload aborted", "AbortError"));
    if (signal) {
      signal.addEventListener("abort", () => xhr.abort(), { once: true });
    }
    xhr.send(file);
  });
}

export function toAttachmentMeta(result: UploadResult, thumbnailUrl: string | null = null) {
  return {
    file_id: result.file_id,
    name: result.name,
    mime_type: result.mime_type,
    size_bytes: result.size_bytes,
    width: null,
    height: null,
    thumbnail_url: thumbnailUrl,
    url: `/v1/media/${result.file_id}/url`,
  };
}
