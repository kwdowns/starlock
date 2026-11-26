import { Field, Input } from "@/components/ui";
import { LIMITS, type Parsed } from "@/lib/equipment";

interface Props {
  label: string;
  value: string;
  onChange: (v: string) => void;
  parsed: Parsed<unknown>;
  placeholder?: string;
  hint?: string;
  /** Numeric keyboard on phones. */
  numeric?: boolean;
  autoFocus?: boolean;
}

/** A form field that shows its error once something is typed (empty just disables the submit). */
export function FormField({ label, value, onChange, parsed, placeholder, hint, numeric, autoFocus }: Props) {
  return (
    <Field label={label} hint={hint} error={value.trim() !== "" && !parsed.ok ? parsed.error : undefined}>
      <Input
        type="text"
        inputMode={numeric ? "decimal" : "text"}
        autoComplete="off"
        autoFocus={autoFocus}
        maxLength={numeric ? 40 : LIMITS.name.max + 20}
        placeholder={placeholder}
        value={value}
        onChange={(e) => onChange(e.target.value)}
      />
    </Field>
  );
}
