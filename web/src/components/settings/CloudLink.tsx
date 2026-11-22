import { useCallback, useEffect, useState } from "react";
import { Alert, Button, Field, Input, SettingRow } from "@/components/ui";
import { api, type CloudStatus } from "@/lib/api";

const CODE_RE = /^[A-Za-z0-9]{4}-?[A-Za-z0-9]{4}$/;

function ago(unix: number | null | undefined): string | null {
  if (!unix) return null;
  const s = Math.max(0, Math.round(Date.now() / 1000 - unix));
  if (s < 90) return `${s} s ago`;
  const m = Math.round(s / 60);
  if (m < 90) return `${m} min ago`;
  return new Date(unix * 1000).toLocaleString([], {
    month: "short", day: "numeric", hour: "2-digit", minute: "2-digit",
  });
}

/**
 * Optional Starlock Cloud link: pair with a code from the phone app, see the
 * link status, unlink. Only polls while the Settings sheet is open.
 */
export function CloudLink({ open }: { open: boolean }) {
  const [status, setStatus] = useState<CloudStatus | null>(null);
  const [code, setCode] = useState("");
  const [baseUrl, setBaseUrl] = useState("");
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<string | null>(null);

  const refresh = useCallback(() => {
    api.cloudStatus().then(setStatus).catch(() => setStatus(null));
  }, []);

  useEffect(() => {
    if (!open) return;
    refresh();
    const id = window.setInterval(refresh, 15_000);
    return () => window.clearInterval(id);
  }, [open, refresh]);

  if (!status?.available) return null;

  const needsUrl = !status.default_base_url;
  const codeOk = CODE_RE.test(code.trim());

  async function pair() {
    setBusy(true);
    setError(null);
    try {
      setStatus(await api.cloudPair(code.trim(), needsUrl ? baseUrl.trim() : undefined));
      setCode("");
    } catch (err) {
      setError(err instanceof Error ? err.message : String(err));
    } finally {
      setBusy(false);
    }
  }

  async function unlink() {
    setBusy(true);
    setError(null);
    try {
      await api.cloudUnlink();
      refresh();
    } catch (err) {
      setError(err instanceof Error ? err.message : String(err));
    } finally {
      setBusy(false);
    }
  }

  const problem = status.error ?? status.upload_error ?? status.pointing_error;

  return (
    <section className="flex flex-col gap-3" aria-label="Starlock Cloud">
      <h2 className="text-heading">Starlock Cloud</h2>
      {status.linked ? (
        <>
          <SettingRow
            label={status.name ?? "Linked"}
            description={
              [
                "Linked to your Starlock Cloud account",
                ago(status.last_upload_at) && `log backed up ${ago(status.last_upload_at)}`,
              ]
                .filter(Boolean)
                .join(" · ")
            }
          >
            <Button variant="secondary" size="sm" onClick={unlink} disabled={busy}>
              Unlink
            </Button>
          </SettingRow>
          {problem && <Alert variant="warning">{problem}</Alert>}
          <p className="text-label text-muted-foreground">
            While linked, this Starlock sends what it&apos;s pointing at (for the
            iPhone Live Activity) and backs up the observation log, including
            your observing site&apos;s latitude and longitude, whenever it has
            internet. Everything keeps working without it.
          </p>
        </>
      ) : (
        <>
          <p className="text-label text-muted-foreground">
            Optional. Link to back up the observation log and show what the scope
            points at on your iPhone&apos;s Lock Screen. Get a pairing code in the
            Starlock iPhone app.
          </p>
          {status.error && <Alert variant="info">{status.error}</Alert>}
          <Field label="Pairing code" error={error ?? undefined}>
            <Input
              value={code}
              placeholder="K7P4-QX9M"
              autoCapitalize="characters"
              autoComplete="off"
              spellCheck={false}
              onChange={(e) => setCode(e.target.value.toUpperCase())}
            />
          </Field>
          {needsUrl && (
            <Field label="Cloud address" hint="Until Starlock Cloud has its own address.">
              <Input
                value={baseUrl}
                placeholder="https://…"
                inputMode="url"
                autoComplete="off"
                spellCheck={false}
                onChange={(e) => setBaseUrl(e.target.value)}
              />
            </Field>
          )}
          <Button
            onClick={pair}
            disabled={busy || !codeOk || (needsUrl && !baseUrl.trim().startsWith("https://"))}
          >
            {busy ? "Linking…" : "Link"}
          </Button>
          <p className="text-label text-muted-foreground">
            Linking sends this Starlock&apos;s observation log, including your
            observing site&apos;s location, to your account.
          </p>
        </>
      )}
    </section>
  );
}
