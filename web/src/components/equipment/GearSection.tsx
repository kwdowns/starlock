import { useState, type ReactNode } from "react";
import { Check, Pencil, Plus } from "lucide-react";
import { Button, List, ListRow } from "@/components/ui";

interface Item {
  id: string;
  name: string;
}

interface Props<T extends Item> {
  id: string;
  title: string;
  items: T[];
  /** Muted second line of a row. */
  summary: (item: T) => string;
  /** "No eyepieces yet." */
  emptyText: string;
  /** "Add eyepiece" */
  addLabel: string;
  inUseId: string | null;
  /** Tapping a row puts it in use. */
  onSelect: (id: string) => void;
  /** The add / edit dialog; `item` null to add. */
  dialog: (item: T | null, close: () => void) => ReactNode;
}

/**
 * A titled list of saved items: tap a row to use it, the pencil to edit or
 * delete it, Add for a new one.
 */
export function GearSection<T extends Item>({
  id,
  title,
  items,
  summary,
  emptyText,
  addLabel,
  inUseId,
  onSelect,
  dialog,
}: Props<T>) {
  // undefined: closed; null: adding; an item: editing it.
  const [editing, setEditing] = useState<T | null | undefined>(undefined);
  const close = () => setEditing(undefined);

  return (
    <section className="flex flex-col gap-3" aria-labelledby={id}>
      <h2 id={id} className="text-heading">
        {title}
      </h2>
      {items.length === 0 ? (
        <p className="text-label text-muted-foreground">{emptyText}</p>
      ) : (
        <ItemList items={items} summary={summary} inUseId={inUseId} onSelect={onSelect} onEdit={setEditing} />
      )}
      <Button variant="secondary" className="self-start" onClick={() => setEditing(null)}>
        <Plus aria-hidden />
        {addLabel}
      </Button>
      {editing !== undefined && dialog(editing, close)}
    </section>
  );
}

/** Rows with name, summary and an edit button; the one in use is marked. */
export function ItemList<T extends Item>({
  items,
  summary,
  inUseId,
  onSelect,
  onEdit,
}: {
  items: T[];
  summary: (item: T) => string;
  inUseId: string | null;
  onSelect: (id: string) => void;
  onEdit: (item: T) => void;
}) {
  return (
    <List>
      {items.map((item) => {
        const inUse = item.id === inUseId;
        return (
          <ListRow
            key={item.id}
            title={item.name}
            subtitle={summary(item)}
            // A check, not the words: a phone row has no room beside the summary.
            meta={
              inUse ? (
                <>
                  <Check className="size-5" aria-hidden />
                  <span className="sr-only">In use</span>
                </>
              ) : undefined
            }
            selected={inUse}
            onPress={() => {
              if (!inUse) onSelect(item.id);
            }}
            action={
              <Button variant="ghost" size="icon-sm" aria-label={`Edit ${item.name}`} onClick={() => onEdit(item)}>
                <Pencil />
              </Button>
            }
          />
        );
      })}
    </List>
  );
}
