import { ReadableText } from "@/components/readable-text";

type Reply = Record<string, unknown> & { message: string };

export function currentReplyParts(message: string, collapseLong: boolean) {
  const boundary = message.match(/\r?\n[ \t]*\r?\n/);
  if (
    !collapseLong ||
    message.length <= 900 ||
    boundary?.index === undefined ||
    !message.slice(0, boundary.index).trim()
  )
    return null;
  return {
    lead: message.slice(0, boundary.index),
    rest: message.slice(boundary.index),
  };
}

function ReplyText({
  message,
  collapseLong,
}: {
  message: string;
  collapseLong: boolean;
}) {
  const parts = currentReplyParts(message, collapseLong);
  if (!parts)
    return <ReadableText className="director-response-text" text={message} />;
  return (
    <div className="director-response-text">
      <ReadableText text={parts.lead} />
      <details className="record-details reply-full-response">
        <summary>Read full response</summary>
        <ReadableText text={parts.rest} />
      </details>
    </div>
  );
}

export function DirectorResponses({
  responses,
  heading = "Finney’s replies",
  collapseLong = false,
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
          <ReplyText message={reply.message} collapseLong={collapseLong} />
        </article>
      ))}
    </section>
  );
}
