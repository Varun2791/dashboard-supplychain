import { LIFECYCLE_STEPS, stepForState } from "@/lib/lifecycle-map";
import type { LifecycleMap } from "@/lib/lifecycle-map";

/**
 * Session lifecycle display (Slice D, DESIGN.md §13).
 *
 * Presentation only: a literal segmented process line grounded in the
 * actual backend state machine via `stepForState`. Segments carry their
 * own borders (never text-arrow glyphs that break mid-wrap); the current
 * segment takes an accent edge plus `aria-current="step"`, done segments
 * stay muted with check marks. Terminal FAILED / EXPIRED render as a
 * separate status line, never as further pipeline stages. The literal
 * backend state stays visible alongside (UploadSession keeps its
 * "Session state: X" line). No percentages, no progress bars, no
 * animation, no BLOCKED lifecycle state, no waiver or override actions.
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
      <ol aria-label="Session pipeline" className="lifecycle-segments">
        {LIFECYCLE_STEPS.map((step) => {
          const tone = stepTone(step, map);
          return (
            <li key={step} data-tone={tone}>
              <span aria-current={tone === "current" ? "step" : undefined}>
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
      </ol>
      {map.status === "failed" ? (
        <p role="status" className="lifecycle-status" data-status="failed">
          Failed <span>— terminal session status, not a pipeline stage.</span>
        </p>
      ) : null}
      {map.status === "expired" ? (
        <p role="status" className="lifecycle-status" data-status="expired">
          Expired{" "}
          <span>— session status, not a pipeline stage or a data failure.</span>
        </p>
      ) : null}
    </div>
  );
}
