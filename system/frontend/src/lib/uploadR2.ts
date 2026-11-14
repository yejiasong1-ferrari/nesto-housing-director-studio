/** Browser → Cloudflare R2 PUT with progress + timeout (XHR). */

export const MAX_UPLOAD_BYTES = 100 * 1024 * 1024; // 100MB
export const MAX_DURATION_SEC = 5 * 60; // 5 minutes
export const UPLOAD_TIMEOUT_MS = 300_000; // 5 minutes

export class UploadCancelledError extends Error {
  constructor(message = "Upload cancelled") {
    super(message);
    this.name = "UploadCancelledError";
  }
}

export function assertVideoFileSize(file: File): void {
  if (file.size > MAX_UPLOAD_BYTES) {
    throw new Error("Video size must be less than 100MB");
  }
  if (file.size <= 0) {
    throw new Error("Empty video file");
  }
}

/** Read duration via a temporary <video> element (browser metadata). */
export function readVideoDuration(file: File): Promise<number> {
  return new Promise((resolve, reject) => {
    const url = URL.createObjectURL(file);
    const video = document.createElement("video");
    video.preload = "metadata";
    const cleanup = () => {
      URL.revokeObjectURL(url);
      video.removeAttribute("src");
      video.load();
    };
    video.onloadedmetadata = () => {
      const duration = Number(video.duration);
      cleanup();
      if (!Number.isFinite(duration) || duration <= 0) {
        reject(new Error("Could not read video duration"));
        return;
      }
      resolve(duration);
    };
    video.onerror = () => {
      cleanup();
      reject(new Error("Could not read video duration"));
    };
    video.src = url;
  });
}

export async function assertVideoLimits(file: File): Promise<void> {
  assertVideoFileSize(file);
  try {
    const duration = await readVideoDuration(file);
    if (duration > MAX_DURATION_SEC + 0.5) {
      throw new Error("Video must be 5 minutes or shorter");
    }
  } catch (e) {
    if (e instanceof Error && /5 minutes|duration/i.test(e.message) && !/Could not read/.test(e.message)) {
      throw e;
    }
    // If metadata is unreadable, Worker will enforce duration after download.
  }
}

/**
 * PUT ``file`` to a presigned R2 URL.
 * ``contentType`` must match the value used when the URL was signed.
 * Pass ``signal`` to allow the user to cancel mid-upload.
 */
export function uploadToR2(
  uploadUrl: string,
  file: File,
  contentType: string,
  onProgress?: (percent: number) => void,
  signal?: AbortSignal
): Promise<void> {
  return new Promise((resolve, reject) => {
    if (signal?.aborted) {
      reject(new UploadCancelledError());
      return;
    }

    const xhr = new XMLHttpRequest();
    xhr.open("PUT", uploadUrl, true);
    xhr.setRequestHeader("Content-Type", contentType || file.type || "video/mp4");
    xhr.timeout = UPLOAD_TIMEOUT_MS;

    const onAbort = () => {
      xhr.abort();
    };
    signal?.addEventListener("abort", onAbort);

    const cleanup = () => {
      signal?.removeEventListener("abort", onAbort);
    };

    xhr.upload.onprogress = (event) => {
      if (!event.lengthComputable || !onProgress) return;
      const percent = Math.round((event.loaded / event.total) * 100);
      onProgress(Math.min(100, Math.max(0, percent)));
    };

    xhr.onload = () => {
      cleanup();
      if (xhr.status >= 200 && xhr.status < 300) {
        onProgress?.(100);
        resolve();
        return;
      }
      reject(new Error(`R2 upload failed: ${xhr.status}`));
    };

    xhr.onerror = () => {
      cleanup();
      reject(new Error("Network error while uploading video"));
    };

    xhr.ontimeout = () => {
      cleanup();
      reject(
        new Error("Upload timeout. Please check your network connection.")
      );
    };

    xhr.onabort = () => {
      cleanup();
      reject(new UploadCancelledError());
    };

    xhr.send(file);
  });
}
