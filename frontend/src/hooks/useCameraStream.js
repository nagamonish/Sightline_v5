import { useCallback, useMemo, useState } from "react";

export function useCameraStream(cameraId, apiUrl) {
  const [streamState, setStreamState] = useState("loading");

  const streamUrl = useMemo(() => {
    if (!cameraId || !apiUrl) {
      return "";
    }
    const base = apiUrl.replace(/\/$/, "");
    return `${base}/cameras/${encodeURIComponent(cameraId)}/stream`;
  }, [apiUrl, cameraId]);

  return {
    streamUrl,
    streamState,
    markLoaded: useCallback(() => setStreamState("live"), []),
    markError: useCallback(() => setStreamState("reconnecting"), []),
    reset: useCallback(() => setStreamState("loading"), []),
  };
}
