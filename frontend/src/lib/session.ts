import { createContext, useContext } from "react";
import type { UploadAcceptedData } from "@/lib/api";

/** Minimal global session snapshot shared by the shell and future views. */
export interface SessionSnapshot {
  session: UploadAcceptedData | null;
  sessionState: string | null;
}

export const EMPTY_SNAPSHOT: SessionSnapshot = {
  session: null,
  sessionState: null,
};

interface SessionContextValue extends SessionSnapshot {
  updateSnapshot: (snapshot: SessionSnapshot) => void;
}

export const SessionContext = createContext<SessionContextValue>({
  ...EMPTY_SNAPSHOT,
  updateSnapshot: () => {},
});

/** Global dataset/session context (Phase 10 shell; later views reuse it). */
export function useSession(): SessionContextValue {
  return useContext(SessionContext);
}
