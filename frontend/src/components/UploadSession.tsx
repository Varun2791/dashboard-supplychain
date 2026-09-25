import { useEffect, useRef, useState } from "react";
import { Button } from "@/components/ui/button";
import {
  ApiRequestError,
  deleteSession,
  fetchSessionStatus,
  uploadSession,
} from "@/lib/api";
import type { UploadAcceptedData } from "@/lib/api";

const MAX_UPLOAD_MB = 250;
const MAX_UPLOAD_BYTES = MAX_UPLOAD_MB * 1024 * 1024;
const MAX_STATUS_POLLS = 6;
const POLL_INTERVAL_MS = 1500;
/** States that keep the status check running (bounded by MAX_STATUS_POLLS). */
const CONTINUING_STATES = new Set(["UPLOADING", "VALIDATING"]);

const ERROR_GUIDANCE: Record<string, string> = {
  EMPTY_FILE:
    "Check that the file has a header row and at least one data row, then try again.",
  INVALID_EXTENSION:
    "Choose a file with a .csv extension that is saved as CSV.",
  MALFORMED_HEADER: "Open the file and fix the first (header) row.",
  UNREADABLE_HEADER: "Add usable column names to the first row.",
  DUPLICATE_HEADERS:
    "Rename the duplicated columns so every column name is unique.",
  FILE_TOO_LARGE: `The limit is ${MAX_UPLOAD_MB} MB. Use a smaller file.`,
  UNSUPPORTED_ENCODING: "Resave the file as UTF-8 or Latin-1 CSV.",
  MALFORMED_CSV:
    "Open the file and fix broken quoting, or export it again as CSV.",
  SESSION_NOT_FOUND: "Upload the file again to start a new session.",
  SESSION_EXPIRED: "Upload the file again to start a new session.",
  INTERNAL_STAGE_ERROR:
    "Try again. If it keeps failing, try a freshly exported CSV file.",
};

interface Failure {
  message: string;
  guidance: string | null;
  code: string | null;
}

function formatBytes(bytes: number): string {
  if (bytes < 1024) {
    return `${bytes} B`;
  }
  if (bytes < 1024 * 1024) {
    return `${(bytes / 1024).toFixed(1)} KB`;
  }
  return `${(bytes / (1024 * 1024)).toFixed(1)} MB`;
}

function toFailure(error: unknown): Failure {
  if (error instanceof ApiRequestError) {
    const guidance =
      error.code !== null && error.code in ERROR_GUIDANCE
        ? ERROR_GUIDANCE[error.code]
        : null;
    return { message: error.message, guidance, code: error.code };
  }
  return {
    message: "Something went wrong. Please try again.",
    guidance: null,
    code: null,
  };
}

type Phase = "idle" | "uploading" | "active";

export default function UploadSession() {
  const [selected, setSelected] = useState<File | null>(null);
  const [clientNotice, setClientNotice] = useState<string | null>(null);
  const [dragActive, setDragActive] = useState(false);
  const [phase, setPhase] = useState<Phase>("idle");
  const [progress, setProgress] = useState<number | null>(null);
  const [session, setSession] = useState<UploadAcceptedData | null>(null);
  const [sessionState, setSessionState] = useState<string | null>(null);
  const [pollCount, setPollCount] = useState(0);
  const [pollSettled, setPollSettled] = useState(false);
  const [failure, setFailure] = useState<Failure | null>(null);
  const inputRef = useRef<HTMLInputElement | null>(null);

  // Bounded status check: confirm the stored session state, then stop.
  // Later processing stages do not exist yet, so polling never continues
  // indefinitely waiting for them.
  useEffect(() => {
    if (phase !== "active" || session === null || pollSettled) {
      return;
    }
    let cancelled = false;
    let timer = 0;
    const check = async (attempt: number): Promise<void> => {
      try {
        const status = await fetchSessionStatus(session.sessionId);
        if (cancelled) {
          return;
        }
        setSessionState(status.state);
        setPollCount(attempt);
        if (
          !CONTINUING_STATES.has(status.state) ||
          attempt >= MAX_STATUS_POLLS
        ) {
          setPollSettled(true);
          return;
        }
        timer = window.setTimeout(() => {
          void check(attempt + 1);
        }, POLL_INTERVAL_MS);
      } catch (error) {
        if (cancelled) {
          return;
        }
        setFailure(toFailure(error));
        setPollSettled(true);
      }
    };
    void check(1);
    return () => {
      cancelled = true;
      window.clearTimeout(timer);
    };
  }, [phase, session, pollSettled]);

  function chooseFile(candidate: File | null): void {
    setFailure(null);
    if (candidate === null) {
      return;
    }
    if (!candidate.name.toLowerCase().endsWith(".csv")) {
      setSelected(null);
      setClientNotice("Only .csv files are accepted. Choose a CSV file.");
      return;
    }
    if (candidate.size > MAX_UPLOAD_BYTES) {
      setSelected(null);
      setClientNotice(
        `“${candidate.name}” is ${formatBytes(candidate.size)}, over the ${MAX_UPLOAD_MB} MB limit. Choose a smaller file.`,
      );
      return;
    }
    setClientNotice(null);
    setSelected(candidate);
  }

  function clearSelection(): void {
    setSelected(null);
    setClientNotice(null);
    if (inputRef.current !== null) {
      inputRef.current.value = "";
    }
  }

  async function startUpload(): Promise<void> {
    if (selected === null || phase === "uploading") {
      return;
    }
    setPhase("uploading");
    setProgress(null);
    setFailure(null);
    setSessionState(null);
    setPollCount(0);
    setPollSettled(false);
    try {
      const accepted = await uploadSession(selected, (update) => {
        setProgress(update.fraction);
      });
      setSession(accepted);
      setPhase("active");
    } catch (error) {
      setFailure(toFailure(error));
      setPhase("idle");
    }
  }

  async function resetSession(): Promise<void> {
    if (session !== null) {
      try {
        await deleteSession(session.sessionId);
      } catch (error) {
        if (error instanceof ApiRequestError && error.status === 404) {
          // Already gone server-side: still safe to return to empty state.
        } else {
          setFailure(toFailure(error));
          return;
        }
      }
    }
    clearSelection();
    setSession(null);
    setSessionState(null);
    setPollCount(0);
    setPollSettled(false);
    setFailure(null);
    setProgress(null);
    setPhase("idle");
  }

  return (
    <section
      aria-labelledby="upload-heading"
      className="flex w-full flex-col gap-4 rounded-xl border p-6"
    >
      <h2 id="upload-heading" className="text-xl font-semibold tracking-tight">
        Upload a supply-chain CSV
      </h2>
      <p className="text-muted-foreground text-sm">
        Files are processed only on this machine. Nothing is sent to any
        external service.
      </p>
      <p className="text-muted-foreground text-sm">
        Choose a DataCo-compatible .csv file. Maximum {MAX_UPLOAD_MB} MB. The
        reference file is about 95.9 MB with 180,519 rows.
      </p>

      {session === null ? (
        <>
          <div
            data-testid="dropzone"
            onDragOver={(event) => {
              event.preventDefault();
              setDragActive(true);
            }}
            onDragLeave={() => setDragActive(false)}
            onDrop={(event) => {
              event.preventDefault();
              setDragActive(false);
              const dropped = event.dataTransfer.files;
              chooseFile(dropped.length > 0 ? dropped[0] : null);
            }}
            className={
              dragActive
                ? "rounded-lg border-2 border-dashed border-primary p-6 text-center"
                : "rounded-lg border-2 border-dashed p-6 text-center"
            }
          >
            <p className="text-sm">Drag and drop a .csv file here, or</p>
            <div className="mt-2 flex flex-col items-start gap-2">
              <label htmlFor="csv-file-input" className="text-sm font-medium">
                Choose a CSV file
              </label>
              <input
                ref={inputRef}
                id="csv-file-input"
                data-testid="file-input"
                type="file"
                accept=".csv,text/csv"
                onChange={(event) => {
                  const files = event.target.files;
                  chooseFile(
                    files !== null && files.length > 0 ? files[0] : null,
                  );
                }}
              />
            </div>
          </div>

          {clientNotice !== null ? (
            <p role="status" className="text-sm">
              {clientNotice}
            </p>
          ) : null}

          {selected !== null ? (
            <div
              data-testid="selected-file"
              className="flex flex-wrap items-center gap-2 text-sm"
            >
              <span>
                Selected: <strong>{selected.name}</strong> (
                {formatBytes(selected.size)})
              </span>
              <Button
                type="button"
                variant="ghost"
                size="sm"
                onClick={clearSelection}
              >
                Remove
              </Button>
            </div>
          ) : null}

          <div>
            <Button
              type="button"
              data-testid="upload-button"
              disabled={selected === null || phase === "uploading"}
              onClick={() => {
                void startUpload();
              }}
            >
              {phase === "uploading" ? "Uploading…" : "Upload"}
            </Button>
          </div>

          {phase === "uploading" ? (
            <div className="flex flex-col gap-2" aria-live="polite">
              <p role="status" className="text-sm">
                Uploading
                {progress !== null ? ` ${Math.round(progress * 100)}%` : "…"}
              </p>
              <progress
                data-testid="upload-progress"
                className="w-full"
                max={100}
                value={
                  progress !== null ? Math.round(progress * 100) : undefined
                }
              />
            </div>
          ) : null}
        </>
      ) : (
        <div data-testid="success-panel" className="flex flex-col gap-3">
          <p role="status" className="text-sm">
            Your file passed the safety checks and is stored for this session.
          </p>
          <dl className="grid grid-cols-[auto_1fr] gap-x-4 gap-y-1 text-sm">
            <dt className="font-medium">File</dt>
            <dd>{session.filenameSafe}</dd>
            <dt className="font-medium">Size</dt>
            <dd>
              {session.bytes} bytes ({formatBytes(session.bytes)})
            </dd>
            <dt className="font-medium">SHA-256</dt>
            <dd>
              <code title={session.sha256} className="break-all">
                {session.sha256.slice(0, 16)}…
              </code>
            </dd>
            <dt className="font-medium">Encoding</dt>
            <dd>{session.encoding}</dd>
            <dt className="font-medium">Session state</dt>
            <dd>
              {sessionState ?? "VALIDATING"}
              {pollCount > 0 ? ` (checked ${pollCount}x)` : ""}
            </dd>
          </dl>
          {pollSettled ? (
            <p
              data-testid="status-note"
              className="text-muted-foreground text-sm"
            >
              Profiling, cleaning, and analytics are not available in this build
              yet. Your stored file is unchanged and ready for the next
              processing stage once it lands.
            </p>
          ) : null}
          <div>
            <Button
              type="button"
              data-testid="reset-button"
              variant="outline"
              onClick={() => {
                void resetSession();
              }}
            >
              Remove session and start over
            </Button>
          </div>
        </div>
      )}

      {failure !== null ? (
        <div
          data-testid="error-panel"
          role="alert"
          className="flex flex-col gap-1 rounded-lg border border-destructive/40 p-4 text-sm"
        >
          <p className="font-medium">The file could not be accepted.</p>
          <p>{failure.message}</p>
          {failure.guidance !== null ? <p>{failure.guidance}</p> : null}
          {failure.code !== null ? (
            <p className="text-muted-foreground">Code: {failure.code}</p>
          ) : null}
        </div>
      ) : null}
    </section>
  );
}
