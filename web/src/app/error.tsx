"use client";

export default function ErrorPage({ reset }: { reset: () => void }) {
  return (
    <main className="fatal">
      <h1>Finance could not load</h1>
      <p>
        The service is unavailable. Your recorded financial state has not
        changed.
      </p>
      <button onClick={reset}>Try again</button>
    </main>
  );
}
