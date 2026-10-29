import { fileExt, formatBytes, isAudioMime, isImageMime, isVideoMime } from "../../lib/format";
import { useUiStore } from "../../stores/ui";
import { useMediaUrl } from "./useMediaUrl";
import type { Attachment } from "../../api/types";

export function AttachmentView({ attachment }: { attachment: Attachment }) {
  const url = useMediaUrl(attachment.url);
  const thumb = useMediaUrl(attachment.thumbnail_url);
  const openLightbox = useUiStore((state) => state.openLightbox);

  if (!url) {
    return (
      <div className="att-file" style={{ opacity: 0.6 }}>
        <span className="att-icon">{fileExt(attachment.name)}</span>
        <span style={{ flex: 1 }}>
          <span className="att-name">{attachment.name}</span>
          <span className="att-size" style={{ display: "block" }}>
            {formatBytes(attachment.size_bytes)}
          </span>
        </span>
      </div>
    );
  }

  if (isImageMime(attachment.mime_type)) {
    return (
      <img
        className="att-image"
        src={thumb || url}
        alt={attachment.name}
        loading="lazy"
        onClick={() => openLightbox([{ url, name: attachment.name }], 0)}
      />
    );
  }

  if (isVideoMime(attachment.mime_type)) {
    return <video className="att-video" src={url} controls preload="metadata" />;
  }

  if (isAudioMime(attachment.mime_type)) {
    return <audio src={url} controls preload="metadata" style={{ maxWidth: 320 }} />;
  }

  return (
    <a className="att-file" href={url} target="_blank" rel="noopener noreferrer">
      <span className="att-icon">{fileExt(attachment.name)}</span>
      <span style={{ flex: 1, minWidth: 0 }}>
        <span className="att-name">{attachment.name}</span>
        <span className="att-size" style={{ display: "block" }}>
          {formatBytes(attachment.size_bytes)}
        </span>
      </span>
      <span aria-hidden>⬇</span>
    </a>
  );
}

export function AttachmentGrid({ attachments }: { attachments: Attachment[] }) {
  if (!attachments.length) return null;
  return (
    <div className="att-grid">
      {attachments.map((attachment) => (
        <AttachmentView key={attachment.file_id} attachment={attachment} />
      ))}
    </div>
  );
}
