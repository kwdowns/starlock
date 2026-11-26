import { useState, type ReactNode } from "react";
import { Trash2 } from "lucide-react";
import {
  Alert,
  Button,
  Dialog,
  DialogContent,
  DialogDescription,
  DialogFooter,
  DialogHeader,
  DialogTitle,
} from "@/components/ui";

interface DeleteAction {
  /** "Delete <name>?" */
  name: string;
  /** A second sentence for the confirmation, e.g. "Its horizon is deleted too." */
  detail?: string;
  onDelete: () => Promise<void>;
}

interface Props {
  title: string;
  description?: string;
  submitLabel: string;
  /** False while a field is empty or out of range: the submit button is disabled. */
  canSubmit: boolean;
  /** Resolves once the engine took it; throws with the engine's short reason. */
  onSubmit: () => Promise<void>;
  onClose: () => void;
  remove?: DeleteAction;
  children: ReactNode;
}

function message(e: unknown): string {
  return e instanceof Error ? e.message : String(e);
}

/**
 * Add / edit form for a site or a piece of equipment. Mounted only while
 * open (so its fields start from the item each time). Delete asks first, in
 * the same dialog. Engine errors show under the form, short.
 */
export function ItemDialog({
  title,
  description,
  submitLabel,
  canSubmit,
  onSubmit,
  onClose,
  remove,
  children,
}: Props) {
  const [busy, setBusy] = useState<"save" | "delete" | null>(null);
  const [error, setError] = useState<{ title: string; text: string } | null>(null);
  const [confirming, setConfirming] = useState(false);

  async function run(kind: "save" | "delete", fn: () => Promise<void>) {
    setBusy(kind);
    setError(null);
    try {
      await fn();
      onClose();
    } catch (e) {
      setError({ title: kind === "save" ? "Couldn't save" : "Couldn't delete", text: message(e) });
      setBusy(null);
    }
  }

  return (
    <Dialog open onOpenChange={(o) => !o && busy === null && onClose()}>
      <DialogContent>
        {confirming && remove ? (
          <>
            <DialogHeader>
              <DialogTitle>Delete {remove.name}?</DialogTitle>
              {remove.detail && <DialogDescription>{remove.detail}</DialogDescription>}
            </DialogHeader>
            {error && (
              <Alert variant="error" title={error.title}>
                {error.text}
              </Alert>
            )}
            <DialogFooter>
              <Button variant="secondary" disabled={busy !== null} onClick={() => setConfirming(false)}>
                Keep
              </Button>
              <Button
                variant="danger"
                loading={busy === "delete"}
                onClick={() => void run("delete", remove.onDelete)}
              >
                <Trash2 aria-hidden />
                Delete
              </Button>
            </DialogFooter>
          </>
        ) : (
          <form
            className="flex flex-col gap-4"
            noValidate
            onSubmit={(e) => {
              e.preventDefault();
              if (canSubmit && busy === null) void run("save", onSubmit);
            }}
          >
            <DialogHeader>
              <DialogTitle>{title}</DialogTitle>
              {description && <DialogDescription>{description}</DialogDescription>}
            </DialogHeader>
            {children}
            {error && (
              <Alert variant="error" title={error.title}>
                {error.text}
              </Alert>
            )}
            <DialogFooter>
              {remove && (
                <Button
                  type="button"
                  variant="danger"
                  className="sm:mr-auto"
                  disabled={busy !== null}
                  onClick={() => {
                    setError(null);
                    setConfirming(true);
                  }}
                >
                  <Trash2 aria-hidden />
                  Delete
                </Button>
              )}
              <Button type="submit" loading={busy === "save"} disabled={!canSubmit}>
                {submitLabel}
              </Button>
            </DialogFooter>
          </form>
        )}
      </DialogContent>
    </Dialog>
  );
}
