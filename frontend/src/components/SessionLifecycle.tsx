import { LIFECYCLE_STEPS, stepForState } from "@/lib/lifecycle-map";
import type { LifecycleMap } from "@/lib/lifecycle-map";

/**
 * Session lifecycle display (governance slice 4, DESIGN.md §13).
 *
 * Presentation only: a compact conceptual pipeline grounded in the actual
 * backend state machine via `stepForState`. The literal backend state stays
 * visible alongside (UploadSession keeps its "Session state: X" line). No
 * percentages, no progress bars, no animation, no BLOCKED lifecycle state,
 * no waiver or override actions.
 */

function stepTone(
  step: string,
  map: LifecycleMap,
): "done" | "current" | "todo" {
  if (map.complete.includes(step)) {
    return "done";
  }
  if (map.current === step) {
    return "current";
  }
  return "todo";
}

export default function SessionLifecycle({ state }: { state: string | null }) {
  const map = stepForState(state);
  return (
    <div>
      <ol
        aria-label="Session pipeline"
        className="flex flex-wrap items-center gap-x-2 gap-y-1"
      >
        {LIFECYCLE_STEPS.map((step, index) => {
          const tone = stepTone(step, map);
          return (
            <li key={step} className="flex items-center gap-2">
              {index > 0 ? (
                <span aria-hidden="true" className="text-muted-foreground">
                  →
                </span>
              ) : null}
              <span
                aria-current={tone === "current" ? "step" : undefined}
                className={
                  tone === "done"
                    ? "font-analytical text-[11px] font-medium text-muted-foreground"
                    : tone === "current"
                      ? "font-analytical text-[11px] font-semibold text-foreground"
                      : "font-analytical text-[11px] text-muted-foreground"
                }
              >
                {tone === "done" ? (
                  <>
                    <span aria-hidden="true">✓ </span>
                    {step}
                  </>
                ) : (
                  step
                )}
              </span>
            </li>
          );
        })}
        {map.status === "failed" ? (
          <li className="font-analytical text-[11px] font-semibold text-foreground">
            · Failed
          </li>
        ) : null}
        {map.status === "expired" ? (
          <li className="font-analytical text-[11px] font-semibold text-foreground">
            · Expired
          </li>
        ) : null}
      </ol>
    </div>
  );
}
