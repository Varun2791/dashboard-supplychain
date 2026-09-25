import { EmptyState } from "@/components/states";
import { useSession } from "@/lib/session";
import type { SessionSnapshot } from "@/lib/session";
import { VIEWS } from "@/lib/view-registry";
import type { DashboardView, ViewMeta } from "@/lib/view-registry";
import UploadSession from "@/components/UploadSession";

function FutureView({ meta }: { meta: ViewMeta }) {
  const { session, sessionState } = useSession();
  const body =
    session === null
      ? `Upload a CSV on the Upload view first. The ${meta.label} view arrives in Phase ${meta.phase}.`
      : `Session ${session.sessionId.slice(0, 8)} is ${sessionState ?? "starting"}. The ${meta.label} view arrives in Phase ${meta.phase}.`;
  return (
    <section aria-labelledby={`${meta.id}-heading`}>
      <h2
        id={`${meta.id}-heading`}
        className="text-xl font-semibold tracking-tight"
      >
        {meta.label}
      </h2>
      <p className="mt-1 text-sm text-muted-foreground">{meta.question}</p>
      <div className="mt-4">
        <EmptyState
          title={`${meta.label} is not part of this build yet`}
          body={body}
        />
      </div>
    </section>
  );
}

export function ActiveView({
  view,
  onSessionChange,
}: {
  view: DashboardView;
  onSessionChange: (snapshot: SessionSnapshot) => void;
}) {
  const meta = VIEWS.find((entry) => entry.id === view);
  return (
    <>
      {/* UploadSession is the single owner of the upload/session lifecycle.
        It stays mounted for the life of the shell and is only visually
        hidden (`hidden` removes it from layout, focus order, and the
        accessibility tree) so navigation never cancels polling or wipes
        the global snapshot with a fresh null state. */}
      <div hidden={view !== "upload"} className="mx-auto w-full max-w-2xl">
        <UploadSession onSessionChange={onSessionChange} />
      </div>
      {view !== "upload" && meta !== undefined ? (
        <FutureView meta={meta} />
      ) : null}
    </>
  );
}
