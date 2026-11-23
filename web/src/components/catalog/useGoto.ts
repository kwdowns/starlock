import { useCallback, useState } from "react";
import { api } from "@/lib/api";
import { rememberTargetMagnitude } from "./targetMagnitude";

/**
 * Sets the goto target and tracks the request. Failures are kept in `error`
 * so the UI can show them; they are never swallowed.
 */
export function useGoto(onTargetSet?: () => void) {
  const [pendingKey, setPendingKey] = useState<string | null>(null);
  const [error, setError] = useState<string | null>(null);

  const go = useCallback(
    async (
      key: string, raDeg: number, decDeg: number, name?: string, sizeDeg?: number, magnitude?: number,
    ): Promise<boolean> => {
      setPendingKey(key);
      setError(null);
      // Before the request, so it is there when the engine reports the target.
      rememberTargetMagnitude(raDeg, decDeg, magnitude);
      try {
        await api.setGoto(raDeg, decDeg, name, sizeDeg);
        onTargetSet?.();
        return true;
      } catch (e) {
        setError(e instanceof Error ? e.message : String(e));
        return false;
      } finally {
        setPendingKey(null);
      }
    },
    [onTargetSet],
  );

  const clearError = useCallback(() => setError(null), []);
  return { go, pendingKey, error, clearError };
}
