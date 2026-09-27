/**
 * Backend-state → conceptual-step mapping (governance slice 4).
 *
 * Pure mapping, no presentation: every actual frontend-observable session
 * state maps explicitly to completed/current conceptual steps. Conceptual
 * steps are NOT backend state names. Unknown states claim nothing (no step
 * current) so the literal backend state line speaks alone.
 *
 * Honest mapping notes (backend order, not label order):
 * - VALIDATING still shows Upload as current: upload acceptance (cheap
 *   guards + header validation) completes only when profiling starts.
 * - CANONICALIZING shows Analyze as current: the canonical build is
 *   analysis-pipeline work; a quality gate parks it recoverably, which is
 *   never terminal and never a generic BLOCKED state.
 * - FAILED / EXPIRED render no step as current; terminal markers plus the
 *   existing error panel carry the distinction.
 */

export const LIFECYCLE_STEPS = [
  "Upload",
  "Profile",
  "Validate",
  "Clean",
  "Analyze",
  "Dashboard",
] as const;

export type LifecycleStatus = "pending" | "active" | "failed" | "expired";

export interface LifecycleMap {
  complete: readonly string[];
  current: string | null;
  status: LifecycleStatus;
}

export function stepForState(state: string | null): LifecycleMap {
  switch (state) {
    case null:
    case "UPLOADING":
    case "VALIDATING":
      return { complete: [], current: "Upload", status: "active" };
    case "PROFILING":
      return {
        complete: ["Upload", "Validate"],
        current: "Profile",
        status: "active",
      };
    case "CLEANING":
      return {
        complete: ["Upload", "Validate", "Profile"],
        current: "Clean",
        status: "active",
      };
    case "CANONICALIZING":
    case "ANALYZING":
      return {
        complete: ["Upload", "Validate", "Profile", "Clean"],
        current: "Analyze",
        status: "active",
      };
    case "READY":
      return {
        complete: [...LIFECYCLE_STEPS],
        current: null,
        status: "active",
      };
    case "FAILED":
      return { complete: [], current: null, status: "failed" };
    case "EXPIRED":
      return { complete: [], current: null, status: "expired" };
    default:
      return { complete: [], current: null, status: "pending" };
  }
}
