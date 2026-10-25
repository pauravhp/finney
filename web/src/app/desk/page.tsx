import { Dashboard } from "@/components/dashboard";
import { publicConfig } from "@/lib/config";
import { serverSupabase } from "@/lib/supabase/server";
import { financeApiUrl } from "@/lib/connectors";

export const dynamic = "force-dynamic";

export default async function Home() {
  const configured = Boolean(publicConfig());
  const supabase = await serverSupabase();
  const user = supabase ? (await supabase.auth.getUser()).data.user : null;
  return (
    <Dashboard
      configured={configured}
      gmailAvailable={Boolean(financeApiUrl())}
      user={
        user ? { id: user.id, email: user.email ?? "Signed-in member" } : null
      }
    />
  );
}
