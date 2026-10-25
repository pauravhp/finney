import { ReadableText } from "@/components/readable-text";
import { displayRecord } from "@/lib/contracts";

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
      <h3>{heading}</h3>
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
          {Array.isArray(reply.consulted_source_ids) ? (
            reply.consulted_source_ids.filter(
              (id): id is string => typeof id === "string",
            ).length ? (
              <details className="director-response-sources">
                <summary>
                  Sources consulted ({reply.consulted_source_ids.length})
                </summary>
                <ul>
                  {reply.consulted_source_ids
                    .filter((id): id is string => typeof id === "string")
                    .map((id, sourceIndex) => (
                      <li key={`${id}:${sourceIndex}`}>{id}</li>
                    ))}
                </ul>
              </details>
            ) : (
              <p className="muted">
                No source documents were opened for this reply.
              </p>
            )
          ) : (
            <p className="muted">
              Source consultation was not recorded for this reply.
            </p>
          )}
          <details className="record-details">
            <summary>Inspect reply provenance</summary>
            <pre>
              {JSON.stringify(
                displayRecord({
                  job_id: reply.job_id,
                  actor_trace_id: reply.actor_trace_id ?? reply.trace_id,
                  provenance: reply.provenance,
                }),
                null,
                2,
              )}
            </pre>
          </details>
        </article>
      ))}
    </section>
  );
}
