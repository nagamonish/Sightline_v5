import { useCallback, useEffect, useRef, useState } from "react";

const DEFAULT_RECONNECT_MS = 1200;
const MAX_RECONNECT_MS = 10000;

export function useWebSocket(url) {
  const [status, setStatus] = useState("connecting");
  const [lastMessage, setLastMessage] = useState(null);
  const socketRef = useRef(null);
  const reconnectTimerRef = useRef(null);
  const retryRef = useRef(0);
  const shouldReconnectRef = useRef(true);

  const connect = useCallback(() => {
    if (!url) {
      setStatus("idle");
      return;
    }

    setStatus((current) => (current === "connected" ? current : "connecting"));
    const socket = new WebSocket(url);
    socketRef.current = socket;

    socket.onopen = () => {
      retryRef.current = 0;
      setStatus("connected");
    };

    socket.onmessage = (event) => {
      try {
        setLastMessage(JSON.parse(event.data));
      } catch {
        setLastMessage({ type: "raw", data: event.data });
      }
    };

    socket.onerror = () => {
      if (socketRef.current !== socket) {
        return;
      }
      setStatus("error");
    };

    socket.onclose = () => {
      if (socketRef.current !== socket) {
        return;
      }
      socketRef.current = null;
      if (!shouldReconnectRef.current) {
        setStatus("closed");
        return;
      }

      setStatus("reconnecting");
      const delay = Math.min(
        DEFAULT_RECONNECT_MS * 2 ** retryRef.current,
        MAX_RECONNECT_MS,
      );
      retryRef.current += 1;
      reconnectTimerRef.current = window.setTimeout(connect, delay);
    };
  }, [url]);

  useEffect(() => {
    shouldReconnectRef.current = true;
    connect();

    return () => {
      shouldReconnectRef.current = false;
      if (reconnectTimerRef.current) {
        window.clearTimeout(reconnectTimerRef.current);
      }
      socketRef.current?.close();
    };
  }, [connect]);

  const send = useCallback((payload) => {
    if (socketRef.current?.readyState === WebSocket.OPEN) {
      socketRef.current.send(
        typeof payload === "string" ? payload : JSON.stringify(payload),
      );
      return true;
    }
    return false;
  }, []);

  return { status, lastMessage, send };
}
