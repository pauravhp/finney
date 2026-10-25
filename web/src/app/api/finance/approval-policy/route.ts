import { authenticated } from "@/lib/api";
import { updateApprovalPolicy } from "@/lib/approval-policy-server";

export async function POST(request: Request) {
  return updateApprovalPolicy(request, authenticated);
}
