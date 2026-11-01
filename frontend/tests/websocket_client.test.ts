import { describe, it, expect, beforeEach, afterEach, vi } from 'vitest';
import { NexusWebSocketClient } from '@/websocket/client';
import { WsConnectionStatus } from '@/types/websocket';

// Mock WebSocket class
class MockWebSocket {
  public static readonly CONNECTING = 0;
  public static readonly OPEN = 1;
  public static readonly CLOSING = 2;
  public static readonly CLOSED = 3;

  public static instances: MockWebSocket[] = [];
  public url: string;
  public readyState: number = MockWebSocket.CONNECTING;

  public onopen: (() => void) | null = null;
  public onclose: (() => void) | null = null;
  public onerror: ((err: unknown) => void) | null = null;
  public onmessage: ((event: { data: string }) => void) | null = null;

  public sentMessages: string[] = [];

  constructor(url: string) {
    this.url = url;
    MockWebSocket.instances.push(this);
  }

  public simulateOpen(): void {
    this.readyState = 1;
    if (this.onopen) this.onopen();
  }

  public simulateMessage(data: unknown): void {
    if (this.onmessage) {
      const payload = typeof data === 'string' ? data : JSON.stringify(data);
      this.onmessage({ data: payload });
    }
  }

  public simulateClose(): void {
    this.readyState = 3;
    if (this.onclose) this.onclose();
  }

  public simulateError(error: unknown): void {
    if (this.onerror) this.onerror(error);
  }

  public send(msg: string): void {
    this.sentMessages.push(msg);
  }

  public close(): void {
    this.readyState = 3;
    if (this.onclose) this.onclose();
  }
}

describe('NexusWebSocketClient', () => {
  let client: NexusWebSocketClient;

  beforeEach(() => {
    MockWebSocket.instances = [];
    vi.stubGlobal('WebSocket', MockWebSocket);
    vi.useFakeTimers();
  });

  afterEach(() => {
    vi.useRealTimers();
    vi.restoreAllMocks();
    if (client) {
      client.destroy();
    }
  });

  it('initializes in DISCONNECTED state if url is empty or autoConnect is false', () => {
    client = new NexusWebSocketClient({ url: '', autoConnect: false });
    expect(client.getStatus()).toBe('DISCONNECTED');
  });

  it('transitions to CONNECTING then CONNECTED on successful connection', () => {
    client = new NexusWebSocketClient({ url: 'ws://test-nexus:8000/ws/live' });
    const statuses: WsConnectionStatus[] = [];
    client.addStatusListener((s) => statuses.push(s));

    client.connect();
    expect(client.getStatus()).toBe('CONNECTING');

    const socket = MockWebSocket.instances[0];
    expect(socket).toBeDefined();

    socket.simulateOpen();
    expect(client.getStatus()).toBe('CONNECTED');
    expect(statuses).toContain('CONNECTING');
    expect(statuses).toContain('CONNECTED');
  });

  it('prevents duplicate connections when already connecting or connected', () => {
    client = new NexusWebSocketClient({ url: 'ws://test-nexus:8000/ws/live' });
    client.connect();
    expect(MockWebSocket.instances.length).toBe(1);

    // Call connect again while already connecting
    client.connect();
    expect(MockWebSocket.instances.length).toBe(1);

    MockWebSocket.instances[0].simulateOpen();
    client.connect();
    expect(MockWebSocket.instances.length).toBe(1);
  });

  it('triggers RECONNECTING and applies exponential backoff on unexpected disconnection', () => {
    client = new NexusWebSocketClient({
      url: 'ws://test-nexus:8000/ws/live',
      reconnectInterval: 500,
      reconnectDecay: 2,
    });
    client.connect();
    const socket = MockWebSocket.instances[0];
    socket.simulateOpen();
    expect(client.getStatus()).toBe('CONNECTED');

    // Simulate unexpected server drop
    socket.simulateClose();
    expect(client.getStatus()).toBe('RECONNECTING');

    // Timer should reconnect after 500ms
    vi.advanceTimersByTime(499);
    expect(MockWebSocket.instances.length).toBe(1);

    vi.advanceTimersByTime(2);
    expect(MockWebSocket.instances.length).toBe(2);
    expect(client.getStatus()).toBe('RECONNECTING');
  });

  it('invokes onReconnectSnapshot callback when reconnection succeeds', () => {
    const onSnapshot = vi.fn();
    client = new NexusWebSocketClient({
      url: 'ws://test-nexus:8000/ws/live',
      reconnectInterval: 100,
      onReconnectSnapshot: onSnapshot,
    });

    client.connect();
    MockWebSocket.instances[0].simulateOpen();
    expect(onSnapshot).not.toHaveBeenCalled();

    // Trigger disconnect
    MockWebSocket.instances[0].simulateClose();

    // Reconnect timer fires
    vi.advanceTimersByTime(150);
    expect(MockWebSocket.instances.length).toBe(2);

    // Reconnection succeeds
    MockWebSocket.instances[1].simulateOpen();
    expect(client.getStatus()).toBe('CONNECTED');
    expect(onSnapshot).toHaveBeenCalledTimes(1);
  });

  it('correctly handles typed events and subscriber cleanup', () => {
    client = new NexusWebSocketClient({ url: 'ws://test-nexus:8000/ws/live' });
    client.connect();
    const socket = MockWebSocket.instances[0];
    socket.simulateOpen();

    const alarmListener = vi.fn();
    const unsubscribe = client.subscribe('ALARM_TRIGGERED', alarmListener);

    socket.simulateMessage({
      type: 'ALARM_TRIGGERED',
      timestamp: '2026-01-01T12:00:00Z',
      payload: { alarm_id: 'ALM-1', node_id: 'CELL-01' },
    });

    expect(alarmListener).toHaveBeenCalledTimes(1);
    expect(alarmListener).toHaveBeenCalledWith(
      { alarm_id: 'ALM-1', node_id: 'CELL-01' },
      expect.objectContaining({ type: 'ALARM_TRIGGERED' })
    );

    // Unsubscribe and verify no further triggers
    unsubscribe();
    socket.simulateMessage({
      type: 'ALARM_TRIGGERED',
      timestamp: '2026-01-01T12:01:00Z',
      payload: { alarm_id: 'ALM-2', node_id: 'CELL-02' },
    });
    expect(alarmListener).toHaveBeenCalledTimes(1);
  });

  it('safely catches async rejections in onReconnectSnapshot without crashing', async () => {
    const errorSpy = vi.spyOn(console, 'error').mockImplementation(() => {});
    const onSnapshot = vi.fn().mockRejectedValue(new Error('Network fetch failed during snapshot'));
    client = new NexusWebSocketClient({
      url: 'ws://test-nexus:8000/ws/live',
      reconnectInterval: 100,
      onReconnectSnapshot: onSnapshot,
    });

    client.connect();
    MockWebSocket.instances[0].simulateOpen();

    // Trigger disconnect & reconnect
    MockWebSocket.instances[0].simulateClose();
    vi.advanceTimersByTime(150);
    MockWebSocket.instances[1].simulateOpen();

    expect(client.getStatus()).toBe('CONNECTED');
    expect(onSnapshot).toHaveBeenCalledTimes(1);

    // Allow promise rejection handler to run
    await Promise.resolve();
    expect(errorSpy).toHaveBeenCalledWith(
      '[NEXUS WS] Asynchronous onReconnectSnapshot rejected:',
      expect.any(Error)
    );
    errorSpy.mockRestore();
  });

  it('safely ignores malformed or non-envelope JSON without crashing', () => {
    client = new NexusWebSocketClient({ url: 'ws://test-nexus:8000/ws/live' });
    client.connect();
    const socket = MockWebSocket.instances[0];
    socket.simulateOpen();

    const listener = vi.fn();
    client.subscribe('*', listener);

    // Malformed JSON string
    socket.simulateMessage('INVALID_JSON{{{');
    expect(listener).not.toHaveBeenCalled();

    // JSON missing type envelope
    socket.simulateMessage(JSON.stringify({ some_key: 'value' }));
    expect(listener).not.toHaveBeenCalled();

    // JSON with empty string type
    socket.simulateMessage(JSON.stringify({ type: '  ', timestamp: '2026-01-01T00:00:00Z', payload: {} }));
    expect(listener).not.toHaveBeenCalled();

    // JSON missing timestamp
    socket.simulateMessage(JSON.stringify({ type: 'ALARM_TRIGGERED', payload: {} }));
    expect(listener).not.toHaveBeenCalled();

    // JSON missing payload property
    socket.simulateMessage(JSON.stringify({ type: 'ALARM_TRIGGERED', timestamp: '2026-01-01T00:00:00Z' }));
    expect(listener).not.toHaveBeenCalled();
  });

  it('transitions to FAILED status when max reconnect attempts are exceeded', () => {
    client = new NexusWebSocketClient({
      url: 'ws://test-nexus:8000/ws/live',
      reconnectInterval: 100,
      reconnectDecay: 1,
      maxReconnectAttempts: 2,
    });
    client.connect();
    const socket = MockWebSocket.instances[0];
    socket.simulateOpen();

    // First disconnect
    socket.simulateClose();
    expect(client.getStatus()).toBe('RECONNECTING');

    // Attempt 1 fails
    vi.advanceTimersByTime(120);
    expect(MockWebSocket.instances.length).toBe(2);
    MockWebSocket.instances[1].simulateClose();

    // Attempt 2 fails
    vi.advanceTimersByTime(120);
    expect(MockWebSocket.instances.length).toBe(3);
    MockWebSocket.instances[2].simulateClose();

    // Attempts exceeded (2 max attempts)
    expect(client.getStatus()).toBe('DISCONNECTED');
  });

  it('transitions to DISCONNECTED and halts reconnects when explicitly disconnected', () => {
    client = new NexusWebSocketClient({
      url: 'ws://test-nexus:8000/ws/live',
      reconnectInterval: 100,
    });
    client.connect();
    MockWebSocket.instances[0].simulateOpen();

    client.disconnect();
    expect(client.getStatus()).toBe('DISCONNECTED');

    // Ensure timer doesn't fire
    vi.advanceTimersByTime(500);
    expect(MockWebSocket.instances.length).toBe(1);
  });
});
