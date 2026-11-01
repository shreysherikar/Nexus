/**
 * NEXUS Native WebSocket Client Abstraction.
 *
 * Implements:
 * - Connection lifecycle states (CONNECTING, CONNECTED, DISCONNECTED, RECONNECTING)
 * - Exponential backoff reconnection with bounded delay and retry ceiling
 * - Duplicate connection prevention
 * - Safe JSON message parsing and strict envelope validation:
 *     { type: string (non-empty), timestamp: string (valid string), payload: unknown }
 * - Typed event subscription and listener cleanup
 * - Reconnection snapshot callback hook with safe async rejection handling
 * - Stale socket protection & clean disconnection
 */

import { WsConnectionStatus, WsEventListener, WsEventEnvelope, WsOptions } from '@/types/websocket';

export type StatusListener = (status: WsConnectionStatus) => void;

export class NexusWebSocketClient {
  private url: string;
  private ws: WebSocket | null = null;
  private status: WsConnectionStatus = 'DISCONNECTED';
  private reconnectAttempts = 0;
  private reconnectTimer: ReturnType<typeof setTimeout> | null = null;
  private isExplicitlyClosed = false;

  private readonly reconnectInterval: number;
  private readonly maxReconnectInterval: number;
  private readonly reconnectDecay: number;
  private readonly maxReconnectAttempts: number;
  private readonly onReconnectSnapshot?: () => Promise<void> | void;

  private listeners: Map<string, Set<WsEventListener<unknown>>> = new Map();
  private statusListeners: Set<StatusListener> = new Set();

  constructor(options: WsOptions = {}) {
    const defaultWsUrl =
      typeof window !== 'undefined' && window.location.host
        ? `${window.location.protocol === 'https:' ? 'wss:' : 'ws:'}//${window.location.host}/ws/live`
        : '';
    const envWsUrl =
      (typeof import.meta !== 'undefined' && import.meta.env?.VITE_WS_URL) ||
      defaultWsUrl;
    this.url = options.url || envWsUrl;
    this.reconnectInterval = options.reconnectInterval ?? 1000;
    this.maxReconnectInterval = options.maxReconnectInterval ?? 30000;
    this.reconnectDecay = options.reconnectDecay ?? 1.5;
    this.maxReconnectAttempts = options.maxReconnectAttempts ?? 20;
    this.onReconnectSnapshot = options.onReconnectSnapshot;

    if (options.autoConnect && this.url) {
      this.connect();
    }
  }

  public getStatus(): WsConnectionStatus {
    return this.status;
  }

  public getUrl(): string {
    return this.url;
  }

  public setUrl(newUrl: string): void {
    if (this.url !== newUrl) {
      this.url = newUrl;
      if (this.status === 'CONNECTED' || this.status === 'CONNECTING' || this.status === 'RECONNECTING') {
        this.disconnect();
        this.connect();
      }
    }
  }

  public addStatusListener(listener: StatusListener): () => void {
    this.statusListeners.add(listener);
    listener(this.status);
    return () => {
      this.statusListeners.delete(listener);
    };
  }

  private setStatus(newStatus: WsConnectionStatus): void {
    if (this.status !== newStatus) {
      this.status = newStatus;
      this.statusListeners.forEach((fn) => {
        try {
          fn(newStatus);
        } catch (err) {
          console.error('[NEXUS WS] Status listener error:', err);
        }
      });
    }
  }

  public connect(): void {
    // Avoid duplicate connections or invalid URLs
    if (!this.url || this.url.trim() === '') {
      this.setStatus('DISCONNECTED');
      return;
    }

    if (this.ws && (this.ws.readyState === WebSocket.OPEN || this.ws.readyState === WebSocket.CONNECTING)) {
      return;
    }

    this.isExplicitlyClosed = false;
    this.clearReconnectTimer();

    if (this.reconnectAttempts > 0) {
      this.setStatus('RECONNECTING');
    } else {
      this.setStatus('CONNECTING');
    }

    try {
      this.ws = new WebSocket(this.url);
      this.setupSocketEvents(this.ws);
    } catch (err) {
      console.warn('[NEXUS WS] Connection instantiation failed:', err);
      this.handleSocketClose();
    }
  }

  private setupSocketEvents(socket: WebSocket): void {
    socket.onopen = () => {
      if (this.ws !== socket) return;
      const wasReconnecting = this.reconnectAttempts > 0;
      this.reconnectAttempts = 0;
      this.setStatus('CONNECTED');

      // If reconnected after disconnection, invoke snapshot synchronization safely
      if (wasReconnecting && this.onReconnectSnapshot) {
        try {
          const result = this.onReconnectSnapshot();
          if (result && typeof (result as Promise<void>).catch === 'function') {
            (result as Promise<void>).catch((err) => {
              console.error('[NEXUS WS] Asynchronous onReconnectSnapshot rejected:', err);
            });
          }
        } catch (err) {
          console.error('[NEXUS WS] onReconnectSnapshot failed synchronously:', err);
        }
      }
    };

    socket.onmessage = (event: MessageEvent) => {
      if (this.ws !== socket) return;
      this.handleMessage(event.data);
    };

    socket.onerror = (error: Event) => {
      if (this.ws !== socket) return;
      console.warn('[NEXUS WS] Socket error:', error);
    };

    socket.onclose = () => {
      if (this.ws !== socket) return;
      this.handleSocketClose();
    };
  }

  public handleMessage(data: unknown): void {
    if (typeof data !== 'string') {
      return;
    }

    let parsed: unknown;
    try {
      parsed = JSON.parse(data);
    } catch {
      console.warn('[NEXUS WS] Received unparseable non-JSON payload:', data);
      return;
    }

    if (!parsed || typeof parsed !== 'object' || Array.isArray(parsed)) {
      console.warn('[NEXUS WS] Payload is not a JSON object envelope:', parsed);
      return;
    }

    const envelope = parsed as Record<string, unknown>;

    // 1. type must be a non-empty string
    if (typeof envelope.type !== 'string' || envelope.type.trim() === '') {
      console.warn('[NEXUS WS] Envelope missing valid non-empty "type":', parsed);
      return;
    }

    // 2. timestamp must be a valid string
    if (typeof envelope.timestamp !== 'string' || envelope.timestamp.trim() === '') {
      console.warn('[NEXUS WS] Envelope missing valid "timestamp" string:', parsed);
      return;
    }

    // 3. Envelope must contain "payload" key
    if (!('payload' in envelope)) {
      console.warn('[NEXUS WS] Envelope missing "payload" property:', parsed);
      return;
    }

    const validEnvelope = parsed as WsEventEnvelope;
    const eventType = validEnvelope.type;

    // Dispatch to exact-match listeners
    const matched = this.listeners.get(eventType);
    if (matched) {
      matched.forEach((fn) => {
        try {
          fn(validEnvelope.payload, validEnvelope);
        } catch (err) {
          console.error(`[NEXUS WS] Error executing listener for "${eventType}":`, err);
        }
      });
    }

    // Dispatch to wildcard listeners
    const wildcard = this.listeners.get('*');
    if (wildcard) {
      wildcard.forEach((fn) => {
        try {
          fn(validEnvelope.payload, validEnvelope);
        } catch (err) {
          console.error('[NEXUS WS] Error executing wildcard listener:', err);
        }
      });
    }
  }

  private handleSocketClose(): void {
    this.ws = null;

    if (this.isExplicitlyClosed) {
      this.setStatus('DISCONNECTED');
      return;
    }

    if (this.reconnectAttempts >= this.maxReconnectAttempts) {
      console.warn(
        `[NEXUS WS] Max reconnection attempts (${this.maxReconnectAttempts}) reached. Disconnecting.`
      );
      this.setStatus('DISCONNECTED');
      return;
    }

    this.setStatus('RECONNECTING');
    this.scheduleReconnect();
  }

  private scheduleReconnect(): void {
    this.clearReconnectTimer();

    const delay = Math.min(
      this.reconnectInterval * Math.pow(this.reconnectDecay, this.reconnectAttempts),
      this.maxReconnectInterval
    );
    this.reconnectAttempts++;

    this.reconnectTimer = setTimeout(() => {
      this.connect();
    }, delay);
  }

  private clearReconnectTimer(): void {
    if (this.reconnectTimer !== null) {
      clearTimeout(this.reconnectTimer);
      this.reconnectTimer = null;
    }
  }

  public subscribe<T = unknown>(eventType: string, listener: WsEventListener<T>): () => void {
    if (!this.listeners.has(eventType)) {
      this.listeners.set(eventType, new Set());
    }
    const set = this.listeners.get(eventType)!;
    set.add(listener as WsEventListener<unknown>);

    return () => {
      set.delete(listener as WsEventListener<unknown>);
      if (set.size === 0) {
        this.listeners.delete(eventType);
      }
    };
  }

  public send(type: string, payload: unknown): boolean {
    if (!this.ws || this.ws.readyState !== WebSocket.OPEN) {
      console.warn('[NEXUS WS] Cannot send message: socket is not open');
      return false;
    }
    const envelope: WsEventEnvelope = {
      type,
      timestamp: new Date().toISOString(),
      payload,
    };
    try {
      this.ws.send(JSON.stringify(envelope));
      return true;
    } catch (err) {
      console.error('[NEXUS WS] Failed to send message:', err);
      return false;
    }
  }

  public disconnect(): void {
    this.isExplicitlyClosed = true;
    this.clearReconnectTimer();
    this.reconnectAttempts = 0;

    if (this.ws) {
      try {
        this.ws.close();
      } catch {
        // Ignored
      }
      this.ws = null;
    }

    this.setStatus('DISCONNECTED');
  }

  public destroy(): void {
    this.disconnect();
    this.listeners.clear();
    this.statusListeners.clear();
  }
}

// Global default singleton WebSocket client
export const wsClient = new NexusWebSocketClient({ autoConnect: false });
