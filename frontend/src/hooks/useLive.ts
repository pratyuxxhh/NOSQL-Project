import { useEffect, useRef, useState } from "react";
import { accessToken, API_URL } from "../api/client";

export interface LiveEvent {
  event: "alert" | "alert_updated" | "transaction" | "ring";
  data: Record<string, unknown>;
}

/** Subscribe to the backend WebSocket; reconnects automatically. */
export function useLive(onEvent: (event: LiveEvent) => void): boolean {
  const [connected, setConnected] = useState(false);
  const handler = useRef(onEvent);
  handler.current = onEvent;

  useEffect(() => {
    let ws: WebSocket | null = null;
    let closed = false;
    let retry: ReturnType<typeof setTimeout>;
    let ping: ReturnType<typeof setInterval>;

    const connect = () => {
      const token = accessToken();
      if (!token || closed) return;
      ws = new WebSocket(`${API_URL.replace(/^http/, "ws")}/ws?token=${encodeURIComponent(token)}`);
      ws.onopen = () => {
        setConnected(true);
        ping = setInterval(() => ws?.readyState === WebSocket.OPEN && ws.send("ping"), 25000);
      };
      ws.onmessage = (msg) => {
        try {
          handler.current(JSON.parse(msg.data) as LiveEvent);
        } catch {
          /* ignore malformed */
        }
      };
      ws.onclose = () => {
        setConnected(false);
        clearInterval(ping);
        if (!closed) retry = setTimeout(connect, 3000);
      };
    };
    connect();
    return () => {
      closed = true;
      clearTimeout(retry);
      clearInterval(ping);
      ws?.close();
    };
  }, []);

  return connected;
}
