import { useCallback, useState } from "react";
import type { ReactNode } from "react";
import { EMPTY_SNAPSHOT, SessionContext } from "@/lib/session";
import type { SessionSnapshot } from "@/lib/session";

export function SessionProvider({ children }: { children: ReactNode }) {
  const [snapshot, setSnapshot] = useState<SessionSnapshot>(EMPTY_SNAPSHOT);
  const updateSnapshot = useCallback((next: SessionSnapshot) => {
    setSnapshot(next);
  }, []);
  return (
    <SessionContext.Provider value={{ ...snapshot, updateSnapshot }}>
      {children}
    </SessionContext.Provider>
  );
}
