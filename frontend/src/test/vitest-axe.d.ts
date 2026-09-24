/* eslint-disable @typescript-eslint/no-empty-object-type -- augmentation-only interfaces */
import type { AxeMatchers } from "vitest-axe/matchers";

declare module "vitest" {
  // Vitest 5 no longer exposes Assertion through the Vi namespace that
  // vitest-axe's bundled extend-expect types target, so augment here.
  // eslint-disable-next-line @typescript-eslint/no-unused-vars
  interface Assertion<T = unknown> extends AxeMatchers {}
  interface AsymmetricMatchersContaining extends AxeMatchers {}
}
