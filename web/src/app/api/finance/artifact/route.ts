import { apiError, authenticated, ApiError, json } from "@/lib/api";
import { scopeSchema } from "@/lib/contracts";

export async function GET(request: Request) {
  try {
    const params = new URL(request.url).searchParams;
    const scope = scopeSchema.parse({
      organization_id: params.get("organization_id"),
      run_id: params.get("run_id"),
    });
    const path = params.get("path") ?? "";
    if (
      !path.startsWith(`${scope.organization_id}/${scope.run_id}/`) ||
      path.includes("..")
    )
      throw new ApiError(400, "Document path does not belong to this event.");
    const { supabase } = await authenticated();
    // Signed URL creation uses the actual user's JWT and private Storage RLS.
    const { data, error } = await supabase.storage
      .from("finance-artifacts")
      .createSignedUrl(path, 60, { download: true });
    if (error || !data)
      throw new ApiError(
        404,
        "Document is unavailable or you do not have access.",
      );
    return json({ download_url: data.signedUrl, expires_in: 60 });
  } catch (error) {
    return apiError(error);
  }
}
