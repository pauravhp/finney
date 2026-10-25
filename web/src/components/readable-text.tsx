import { Fragment, type ReactNode } from "react";

// Deliberately small Markdown renderer: text is always escaped by React. No HTML,
// images, executable links, or model-authored attributes reach the DOM.
function inline(text: string): ReactNode[] {
  return text
    .split(/(\*\*[^*]+\*\*|`[^`]+`)/g)
    .map((part, index) =>
      part.startsWith("**") && part.endsWith("**") ? (
        <strong key={index}>{part.slice(2, -2)}</strong>
      ) : part.startsWith("`") && part.endsWith("`") ? (
        <code key={index}>{part.slice(1, -1)}</code>
      ) : (
        <Fragment key={index}>{part}</Fragment>
      ),
    );
}
export function ReadableText({
  text,
  className = "",
}: {
  text: string;
  className?: string;
}) {
  const blocks = text.trim().split(/\n\s*\n/);
  return (
    <div className={`readable-text ${className}`}>
      {blocks.map((block, index) => {
        const lines = block.split("\n");
        if (lines.every((line) => /^\s*[-*]\s/.test(line)))
          return (
            <ul key={index}>
              {lines.map((line, i) => (
                <li key={i}>{inline(line.replace(/^\s*[-*]\s/, ""))}</li>
              ))}
            </ul>
          );
        if (lines.every((line) => /^\s*\d+[.)]\s/.test(line)))
          return (
            <ol key={index}>
              {lines.map((line, i) => (
                <li key={i}>{inline(line.replace(/^\s*\d+[.)]\s/, ""))}</li>
              ))}
            </ol>
          );
        if (
          lines.length > 2 &&
          /^\s*\|?\s*:?-{3}/.test(lines[1].replace(/\|/g, " ").trim())
        ) {
          const cells = (line: string) =>
            line.replace(/^\s*\||\|\s*$/g, "").split("|");
          return (
            <div className="table-scroll" key={index}>
              <table>
                <thead>
                  <tr>
                    {cells(lines[0]).map((cell, i) => (
                      <th key={i}>{inline(cell.trim())}</th>
                    ))}
                  </tr>
                </thead>
                <tbody>
                  {lines.slice(2).map((line, i) => (
                    <tr key={i}>
                      {cells(line).map((cell, j) => (
                        <td key={j}>{inline(cell.trim())}</td>
                      ))}
                    </tr>
                  ))}
                </tbody>
              </table>
            </div>
          );
        }
        if (/^#{1,4}\s/.test(block) && lines.length === 1)
          return <h3 key={index}>{inline(block.replace(/^#{1,4}\s/, ""))}</h3>;
        // Preserve every sentence; separate dense single-paragraph model output into
        // readable paragraphs without generating a summary or removing qualifiers.
        const paragraphs =
          block.length > 650 && lines.length === 1
            ? (block
                .split(/(?<=[.!?])(?=\s)/)
                ?.reduce<string[]>((parts, sentence) => {
                  const last = parts.length - 1;
                  if (last >= 0 && parts[last].length < 360)
                    parts[last] += sentence;
                  else parts.push(sentence);
                  return parts;
                }, []) ?? [block])
            : [block];
        return (
          <Fragment key={index}>
            {paragraphs.map((paragraph, i) => (
              <p key={i}>{inline(paragraph)}</p>
            ))}
          </Fragment>
        );
      })}
    </div>
  );
}

export function friendlyTitle(value: string): string {
  return value
    .replace(/^SYNTHETIC demo:\s*/i, "")
    .replace(/^TEST ONLY:\s*/i, "")
    .replace(/^demo_bundle:[^:]+:/, "")
    .replace(/[_]/g, " ");
}

export function sourceDocumentText(value: unknown): string {
  if (typeof value === "string") return value;
  if (value === null || value === undefined) return "";
  if (Array.isArray(value))
    return value.map(sourceDocumentText).filter(Boolean).join("\n\n");
  if (typeof value !== "object") return String(value);
  const row = value as Record<string, unknown>;
  // A bundle's top-level description is an introduction, never the document.
  const technical = new Set([
    "input_kind",
    "source_type",
    "source_kind",
    "provider",
    "metadata",
    "bundle_version",
    "scenario_id",
    "synthetic",
    "content_sha256",
    "artifact_path",
  ]);
  return Object.entries(row)
    .filter(([key]) => !technical.has(key))
    .map(([key, entry]) => {
      const content = sourceDocumentText(entry);
      if (!content) return "";
      if (["documents", "attachments"].includes(key)) return content;
      if (["title", "subject"].includes(key) && typeof entry === "string")
        return `### ${entry}`;
      if (["text", "body", "content", "description"].includes(key))
        return content;
      return `${key.replaceAll("_", " ").replace(/^./, (c) => c.toUpperCase())}:\n${content}`;
    })
    .filter(Boolean)
    .join("\n\n");
}
