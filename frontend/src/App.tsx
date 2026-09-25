import UploadSession from "@/components/UploadSession";

function App() {
  return (
    <main className="mx-auto flex min-h-svh w-full max-w-2xl flex-col items-start justify-center gap-4 p-8">
      <h1 className="text-3xl font-semibold tracking-tight">
        Supply Chain Analytics Dashboard
      </h1>
      <p className="text-muted-foreground">
        Local-first supply-chain CSV analytics. All processing stays on this
        machine. No uploaded data leaves the device.
      </p>
      <UploadSession />
    </main>
  );
}

export default App;
