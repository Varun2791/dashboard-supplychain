export type DashboardView =
  | "upload"
  | "data-quality"
  | "overview"
  | "delivery"
  | "commercial"
  | "diagnostics";

export interface ViewMeta {
  id: DashboardView;
  label: string;
  phase: number;
  question: string;
}

/**
 * Governed view registry (product-spec §4 routes). Order here is nav order.
 * Analytical views land in their owning phases; until then each renders an
 * honest empty state — never a fake completed page.
 */
export const VIEWS: readonly ViewMeta[] = [
  { id: "upload", label: "Upload", phase: 10, question: "" },
  {
    id: "data-quality",
    label: "Data Quality",
    phase: 11,
    question:
      "What is risky in this file, what changed, and what remains flagged?",
  },
  {
    id: "overview",
    label: "Overview",
    phase: 12,
    question: "What happened across commercial value and shipment performance?",
  },
  {
    id: "delivery",
    label: "Delivery",
    phase: 13,
    question:
      "Where and under which shipping conditions do schedule failures occur?",
  },
  {
    id: "commercial",
    label: "Commercial",
    phase: 14,
    question:
      "Which products and geographies are associated with value, profit, discount, and loss?",
  },
  {
    id: "diagnostics",
    label: "Diagnostics",
    phase: 15,
    question: "Which combinations and orders are associated with a poor KPI?",
  },
];
