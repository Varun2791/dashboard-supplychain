import { SessionProvider } from "@/lib/session-context";
import { useSession } from "@/lib/session";
import AppShell from "@/components/AppShell";

function ShellHost() {
  const { updateSnapshot } = useSession();
  return <AppShell onSessionChange={updateSnapshot} />;
}

function App() {
  return (
    <SessionProvider>
      <ShellHost />
    </SessionProvider>
  );
}

export default App;
