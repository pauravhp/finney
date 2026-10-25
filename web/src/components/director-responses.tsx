import { ReadableText } from "@/components/readable-text";

type Reply = Record<string, unknown> & { message: string };

export const RESPONSE_DETAILS_MARKER = "\n\nDetails:\n";

// Only an explicitly authored boundary may hide supplementary explanation.
// The legacy flag remains accepted by callers, but never truncates legacy text.
export function currentReplyParts(
  message: string,
  _legacyCollapseLong?: boolean,
) {
  const boundary = message.indexOf(RESPONSE_DETAILS_MARKER);
  if (boundary < 0) return null;
  const lead = message.slice(0, boundary);
  const rest = message.slice(boundary + RESPONSE_DETAILS_MARKER.length);
  if (!lead.trim() || !rest.trim()) return null;
  return { lead, rest };
}

function ReplyText({ message }: { message: string }) {
  const parts = currentReplyParts(message);
  if (!parts)
    return (
      <ReadableText
        className="director-response-text director-response-primary"
        text={message}
      />
    );
  return (
    <div className="director-response-text">
      <ReadableText className="director-response-primary" text={parts.lead} />
      <details className="record-details reply-full-response">
        <summary>Details</summary>
        <ReadableText className="director-response-details" text={parts.rest} />
      </details>
    </div>
  );
}

export function DirectorResponses({
  responses,
  heading = "Finney’s replies",
}: {
  responses: unknown;
  heading?: string;
  collapseLong?: boolean;
}) {
  const replies = Array.isArray(responses)
    ? responses.filter((value): value is Reply =>
        Boolean(
          value &&
          typeof value === "object" &&
          typeof value.message === "string" &&
          value.message.trim(),
        ),
      )
    : [];
  if (!replies.length) return null;
  return (
    <section className="director-responses">
      {heading && <h3>{heading}</h3>}
      {replies.map((reply, index) => (
        <article
          className="director-response"
          key={
            typeof reply.id === "string"
              ? reply.id
              : `${String(reply.actor_trace_id ?? reply.job_id ?? "reply")}:${index}`
          }
        >
          <ReplyText message={reply.message} />
        </article>
      ))}
    </section>
  );
}
