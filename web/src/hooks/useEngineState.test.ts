import { act, renderHook } from "@testing-library/react";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import { useEngineState } from "./useEngineState";

class FakeSocket {
  static OPEN = 1;
  static CONNECTING = 0;
  static all: FakeSocket[] = [];
  readyState = FakeSocket.CONNECTING;
  onopen: (() => void) | null = null;
  onmessage: ((ev: { data: string }) => void) | null = null;
  onclose: (() => void) | null = null;
  onerror: (() => void) | null = null;
  url: string;
  constructor(url: string) {
    this.url = url;
    FakeSocket.all.push(this);
  }
  open() {
    this.readyState = FakeSocket.OPEN;
    this.onopen?.();
  }
  close() {
    this.readyState = 3;
    this.onclose?.();
  }
}

describe("useEngineState", () => {
  beforeEach(() => {
    FakeSocket.all = [];
    vi.useFakeTimers();
    vi.stubGlobal("WebSocket", FakeSocket);
  });

  afterEach(() => {
    vi.unstubAllGlobals();
    vi.useRealTimers();
  });

  it("calls onConnect on the first connect and on every reconnect", () => {
    const onConnect = vi.fn();
    const { result, unmount } = renderHook(() => useEngineState(onConnect));
    expect(FakeSocket.all).toHaveLength(1);
    expect(onConnect).not.toHaveBeenCalled();

    act(() => FakeSocket.all[0].open());
    expect(onConnect).toHaveBeenCalledTimes(1);
    act(() => FakeSocket.all[0].onmessage?.({ data: JSON.stringify({ state: "SETUP" }) }));
    expect(result.current?.state).toBe("SETUP");

    // The socket drops: the hook retries after a second and reports again.
    act(() => FakeSocket.all[0].close());
    act(() => vi.advanceTimersByTime(1000));
    expect(FakeSocket.all).toHaveLength(2);
    act(() => FakeSocket.all[1].open());
    expect(onConnect).toHaveBeenCalledTimes(2);
    // The last payload is kept while reconnecting.
    expect(result.current?.state).toBe("SETUP");
    unmount();
  });
});
