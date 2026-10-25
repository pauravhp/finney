import { randomUUID } from "node:crypto";
import {
  ApiError,
  apiError,
  authenticated,
  json,
  requestOrigin,
  rpcFailure,
} from "@/lib/api";
import { scopeSchema } from "@/lib/contracts";

export async function POST(request: Request) {
  try {
    if (request.headers.get("origin") !== requestOrigin(request))
      throw new ApiError(403, "Upload from this application.");
    const length = Number(request.headers.get("content-length"));
    if (
      !Number.isFinite(length) ||
      length <= 0 ||
      length > 3 * 1024 * 1024 + 16384
    )
      throw new ApiError(413, "Choose a document up to 3 MiB.");
    const { supabase } = await authenticated();
    const data = await request.formData();
    const scope = scopeSchema.parse({
      organization_id: data.get("organization_id"),
      run_id: data.get("run_id"),
    });
    const file = data.get("file");
    if (
      !(file instanceof File) ||
      file.size < 1 ||
      file.size > 3 * 1024 * 1024 ||
      file.name.length > 200
    )
      throw new ApiError(400, "Choose a nonempty document up to 3 MiB.");
    const allowed = new Set([
      "application/pdf",
      "text/plain",
      "text/csv",
      "text/markdown",
      "image/png",
      "image/jpeg",
      "image/webp",
      "image/gif",
    ]);
    if (!allowed.has(file.type))
      throw new ApiError(415, "Choose a PDF, text, CSV or receipt image.");
    const uploadId = randomUUID();
    const path = `${scope.organization_id}/${scope.run_id}/uploads/${uploadId}`;
    const upload = await supabase.storage
      .from("finance-artifacts")
      .upload(path, file, { contentType: file.type, upsert: false });
    if (upload.error)
      throw new ApiError(
        403,
        "The upload was not accepted. Check event access and document size.",
      );
    const payload = {
      source: "upload",
      artifact_path: path,
      filename: file.name,
      content_type: file.type,
      size: file.size,
    };
    const queued = await supabase.rpc("enqueue_finance_command", {
      p_organization_id: scope.organization_id,
      p_run_id: scope.run_id,
      p_command_type: "intake",
      p_payload: payload,
      p_idempotency_key: `upload:${uploadId}`,
    });
    // Keep the immutable upload on queue failure. Return its exact retry request;
    // the authenticated commands endpoint can retry without another Storage copy.
    if (queued.error)
      return json(
        {
          error: "Document stored; review could not be queued. Retry review.",
          retry_command: {
            ...scope,
            command_type: "intake",
            payload,
            idempotency_key: `upload:${uploadId}`,
          },
        },
        503,
      );
    return json({ job_id: queued.data, status: "queued" }, 202);
  } catch (error) {
    return apiError(error);
  }
}
