import { Fragment, type ReactNode } from "react";

// Text is always escaped by React. Model output cannot introduce HTML, images,
// executable links or DOM attributes. Parse line boundaries, not blank lines:
// actual model replies commonly put headings directly before tables and lists.
function inline(text: string): ReactNode[] {
  return text
    .split(
      /(\*\*[^*\n]+\*\*|`[^`\n]+`|(?<!\*)\*[^*\n]+\*(?!\*)|(?<!\w)_[^_\n]+_(?!\w))/g,
    )
    .map((part, index) => {
      if (part.startsWith("**") && part.endsWith("**"))
        return <strong key={index}>{inline(part.slice(2, -2))}</strong>;
      if (part.startsWith("`") && part.endsWith("`"))
        return <code key={index}>{part.slice(1, -1)}</code>;
      if (
        (part.startsWith("*") && part.endsWith("*")) ||
        (part.startsWith("_") && part.endsWith("_"))
      )
        return <em key={index}>{part.slice(1, -1)}</em>;
      return <Fragment key={index}>{part}</Fragment>;
    });
}
const heading = /^\s{0,3}#{1,6}\s+(.+)$/;
const bullet = /^\s*[-+*]\s+(.+)$/;
const numbered = /^\s*\d+[.)]\s+(.+)$/;
const fence = /^\s*```/;
const rule = /^\s*(?:-{3,}|\*{3,}|_{3,})\s*$/;
function cells(line: string) {
  return line
    .trim()
    .replace(/^\||\|$/g, "")
    .split("|");
}
function tableStarts(lines: string[], index: number) {
  return (
    index + 1 < lines.length &&
    lines[index].includes("|") &&
    lines[index + 1].includes("|") &&
    cells(lines[index + 1]).every((cell) => /^:?-{3,}:?$/.test(cell.trim()))
  );
}
function startsBlock(lines: string[], index: number) {
  return (
    heading.test(lines[index]) ||
    bullet.test(lines[index]) ||
    numbered.test(lines[index]) ||
    fence.test(lines[index]) ||
    rule.test(lines[index]) ||
    tableStarts(lines, index)
  );
}
function paragraph(text: string, key: number) {
  // Lossless splitting: punctuation inside decimal amounts is never a boundary.
  const parts =
    text.length > 650 && !text.includes("\n")
      ? text.split(/(?<=[.!?])(?=\s)/).reduce<string[]>((result, sentence) => {
          const last = result.length - 1;
          if (last >= 0 && result[last].length < 360) result[last] += sentence;
          else result.push(sentence);
          return result;
        }, [])
      : [text];
  return (
    <Fragment key={key}>
      {parts.map((part, index) => (
        <p key={index}>{inline(part)}</p>
      ))}
    </Fragment>
  );
}
export function ReadableText({
  text,
  className = "",
}: {
  text: string;
  className?: string;
}) {
  const lines = text.trim().split(/\r?\n/);
  const blocks: ReactNode[] = [];
  let cursor = 0;
  while (cursor < lines.length) {
    if (!lines[cursor].trim()) {
      cursor++;
      continue;
    }
    const key = cursor;
    const title = lines[cursor].match(heading);
    if (title) {
      blocks.push(<h3 key={key}>{inline(title[1])}</h3>);
      cursor++;
      continue;
    }
    if (fence.test(lines[cursor])) {
      cursor++;
      const code: string[] = [];
      while (cursor < lines.length && !fence.test(lines[cursor]))
        code.push(lines[cursor++]);
      if (cursor < lines.length) cursor++;
      blocks.push(
        <pre key={key}>
          <code>{code.join("\n")}</code>
        </pre>,
      );
      continue;
    }
    if (tableStarts(lines, cursor)) {
      const titles = cells(lines[cursor]);
      cursor += 2;
      const rows: string[][] = [];
      while (
        cursor < lines.length &&
        lines[cursor].trim() &&
        lines[cursor].includes("|") &&
        !heading.test(lines[cursor])
      )
        rows.push(cells(lines[cursor++]));
      blocks.push(
        <div className="table-scroll" key={key}>
          <table>
            <thead>
              <tr>
                {titles.map((title, index) => (
                  <th key={index}>{inline(title.trim())}</th>
                ))}
              </tr>
            </thead>
            <tbody>
              {rows.map((row, index) => (
                <tr key={index}>
                  {row.map((cell, cellIndex) => (
                    <td key={cellIndex}>{inline(cell.trim())}</td>
                  ))}
                </tr>
              ))}
            </tbody>
          </table>
        </div>,
      );
      continue;
    }
    const listPattern = bullet.test(lines[cursor])
      ? bullet
      : numbered.test(lines[cursor])
        ? numbered
        : null;
    if (listPattern) {
      const items: string[] = [];
      while (cursor < lines.length) {
        const item = lines[cursor].match(listPattern);
        if (!item) break;
        items.push(item[1]);
        cursor++;
      }
      const content = items.map((item, index) => (
        <li key={index}>{inline(item)}</li>
      ));
      blocks.push(
        listPattern === bullet ? (
          <ul key={key}>{content}</ul>
        ) : (
          <ol key={key}>{content}</ol>
        ),
      );
      continue;
    }
    if (rule.test(lines[cursor])) {
      blocks.push(<hr key={key} />);
      cursor++;
      continue;
    }
    const prose = [lines[cursor++]];
    while (
      cursor < lines.length &&
      lines[cursor].trim() &&
      !startsBlock(lines, cursor)
    )
      prose.push(lines[cursor++]);
    blocks.push(paragraph(prose.join("\n"), key));
  }
  return <div className={`readable-text ${className}`}>{blocks}</div>;
}
export function friendlyTitle(value: string): string {
  return value
    .replace(/^SYNTHETIC demo:\s*/i, "")
    .replace(/^TEST ONLY:\s*/i, "")
    .replace(/^demo_bundle:[^:]+:/, "")
    .replace(/[_]/g, " ");
}

export function sourceDocumentText(
  value: unknown,
  omitDescription?: string,
): string {
  if (typeof value === "string") return value;
  if (value === null || value === undefined) return "";
  if (Array.isArray(value))
    return value
      .map((entry) => sourceDocumentText(entry))
      .filter(Boolean)
      .join("\n\n");
  if (typeof value !== "object") return String(value);
  const row = value as Record<string, unknown>;
  // Request artifacts are conversation text, never a user/operation dump.
  if (
    typeof row.message === "string" &&
    ("submitted_by" in row ||
      "meaning" in row ||
      row.source_type === "director_message")
  )
    return row.message;
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
    "kind",
    "external_id",
    "meaning",
    "submitted_by",
    "submitted_by_user_id",
  ]);
  return Object.entries(row)
    .filter(
      ([key, entry]) =>
        !technical.has(key) &&
        !(
          omitDescription !== undefined &&
          key === "description" &&
          entry === omitDescription
        ),
    )
    .map(([key, entry]) => {
      const content = sourceDocumentText(entry);
      if (!content) return "";
      if (
        key === "headers" &&
        entry &&
        typeof entry === "object" &&
        !Array.isArray(entry)
      ) {
        return Object.entries(entry as Record<string, unknown>)
          .filter(([header, value]) => {
            // Synthetic packets repeat their description in Subject. Real email
            // addressing and dates remain evidence and are never dropped.
            return !(
              header.toLowerCase() === "subject" &&
              typeof value === "string" &&
              [row.description, row.title].includes(value)
            );
          })
          .map(
            ([header, value]) =>
              `${header.replaceAll("_", " ").replace(/^./, (char) => char.toUpperCase())}: ${sourceDocumentText(value)}`,
          )
          .join("\n");
      }
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
