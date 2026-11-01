import { useEffect, useState } from 'react';
import { WsConnectionStatus, WsEventListener } from '@/types/websocket';
import { wsClient } from './client';

export function useWebSocketStatus(): WsConnectionStatus {
  const [status, setStatus] = useState<WsConnectionStatus>(wsClient.getStatus());

  useEffect(() => {
    const unsubscribe = wsClient.addStatusListener((newStatus) => {
      setStatus(newStatus);
    });
    return unsubscribe;
  }, []);

  return status;
}

export function useWebSocketSubscription<T = unknown>(
  eventType: string,
  handler: WsEventListener<T>
): void {
  useEffect(() => {
    const unsubscribe = wsClient.subscribe<T>(eventType, handler);
    return unsubscribe;
  }, [eventType, handler]);
}
