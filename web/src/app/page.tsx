import { Landing } from "@/components/landing";
import { redirect } from "next/navigation";

export default async function Home({
  searchParams,
}: {
  searchParams: Promise<Record<string, string | string[] | undefined>>;
}) {
  const search = await searchParams;
  // Preserve older authenticated event and OAuth links after the landing rollout.
  if (
    search.organization_id ||
    search.run_id ||
    search.auth_error ||
    search.signin
  ) {
    const query = new URLSearchParams();
    for (const key of ["organization_id", "run_id", "auth_error"]) {
      if (typeof search[key] === "string") query.set(key, search[key]);
    }
    redirect(`/desk${query.size ? `?${query}` : ""}`);
  }
  return <Landing />;
}
