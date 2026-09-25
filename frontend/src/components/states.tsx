import type { ReactNode } from "react";

/** Reusable loading indicator with meaningful text (never a bare spinner). */
export function LoadingState({ label }: { label: string }) {
  return (
    <p role="status" className="text-sm text-muted-foreground">
      {label}
    </p>
  );
}

interface ErrorStateProps {
  title?: string;
  message: string;
  guidance?: string | null;
}

/** Reusable API-error block: message plus actionable guidance, no raw data. */
export function ErrorState({ title, message, guidance }: ErrorStateProps) {
  return (
    <div role="alert" className="flex flex-col gap-1 rounded-lg border p-4">
      <p className="text-sm font-medium">{title ?? "Something went wrong."}</p>
      <p className="text-sm text-muted-foreground">{message}</p>
      {guidance !== undefined && guidance !== null && guidance !== "" ? (
        <p className="text-sm text-muted-foreground">{guidance}</p>
      ) : null}
    </div>
  );
}

interface EmptyStateProps {
  title: string;
  body: string;
  action?: ReactNode;
}

/** Reusable empty state: honest about what is missing and what comes next. */
export function EmptyState({ title, body, action }: EmptyStateProps) {
  return (
    <div className="flex flex-col items-start gap-2 rounded-lg border p-6">
      <p className="text-sm font-medium">{title}</p>
      <p className="text-sm text-muted-foreground">{body}</p>
      {action}
    </div>
  );
}
