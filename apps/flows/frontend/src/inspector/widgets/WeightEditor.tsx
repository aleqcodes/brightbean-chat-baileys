/**
 * `randomizer.paths` — an id and a weight per path, with a running total.
 *
 * A total other than 100 is a hint, not an error: the schema does not require
 * it, and the runtime normalises, so refusing to save would be the builder
 * inventing a rule the server does not have. `minItems: 2` is enforced, because
 * that one is real.
 */
import { newItemId } from "../../schema/ids";
import { deref } from "../../schema/resolve";
import { formatPath } from "../../store/paths";
import { useField } from "../FieldContext";
import type { FieldProps } from "../fields";

export function WeightEditor(props: FieldProps) {
  const { set, readOnly } = useField();
  const { schema, path, value } = props;
  const paths = Array.isArray(value) ? (value as Record<string, unknown>[]) : [];
  const min = schema.minItems ?? 2;
  const max = schema.maxItems;
  const weight = deref(schema.items)?.properties?.["weight"];
  const total = paths.reduce((sum, entry) => sum + (Number(entry["weight"]) || 0), 0);

  const write = (next: Record<string, unknown>[]) => set(path, next, `paths:${formatPath(path)}`);

  return (
    <div className="fb-field">
      <span className="fb-field-label">
        Caminhos <span className="fb-empty">{paths.length}{max !== undefined ? `/${max}` : ""}</span>
      </span>

      {paths.map((entry, index) => (
        <div key={index} className="flex items-center gap-2 mb-1">
          <span className="fb-pill">{String(entry["id"] ?? "")}</span>
          <input
            type="number"
            className="form-input-styled w-24"
            aria-label={`Peso do caminho ${index + 1}`}
            value={typeof entry["weight"] === "number" ? entry["weight"] : ""}
            min={deref(weight)?.minimum ?? 0}
            max={deref(weight)?.maximum ?? 100}
            disabled={readOnly}
            onChange={(event) =>
              write(paths.map((path_, at) => (at === index ? { ...path_, weight: Number(event.target.value) } : path_)))
            }
          />
          <span className="fb-empty">%</span>
          {readOnly ? null : (
            <button
              type="button"
              className="btn-link text-xs ml-auto"
              aria-label={`Remover caminho ${index + 1}`}
              disabled={paths.length <= min}
              onClick={() => write(paths.filter((_unused, at) => at !== index))}
            >
              Remover
            </button>
          )}
        </div>
      ))}

      <p className={total === 100 ? "fb-field-help" : "fb-empty"}>
        Total {total}%{total === 100 ? "" : ". Os pesos são proporções e não precisam somar 100."}
      </p>

      {readOnly || (max !== undefined && paths.length >= max) ? null : (
        <button
          type="button"
          className="btn-outline-sm mt-1"
          onClick={() => write([...paths, { id: newItemId(), weight: 50 }])}
        >
          Adicionar caminho
        </button>
      )}

    </div>
  );
}
