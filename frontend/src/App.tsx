import { useState } from "react";
import { Button } from "@/components/ui/button";

function App() {
  const [stackChecked, setStackChecked] = useState(false);

  return (
    <main className="mx-auto flex min-h-svh w-full max-w-2xl flex-col items-start justify-center gap-4 p-8">
      <h1 className="text-3xl font-semibold tracking-tight">
        Supply Chain Analytics Dashboard
      </h1>
      <p className="text-muted-foreground">
        Local-first supply-chain CSV analytics. Foundation shell only —
        dashboard implementation is in early phases (see PLAN.md).
      </p>
      <p className="text-muted-foreground">
        All processing stays on this machine. No uploaded data leaves the
        device.
      </p>
      <Button type="button" onClick={() => setStackChecked(true)}>
        Run stack check
      </Button>
      {stackChecked ? (
        <p role="status">
          Stack check passed: React, TypeScript, and styles are active.
        </p>
      ) : null}
    </main>
  );
}

export default App;
