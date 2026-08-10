export interface MarkdownWithTitle {
  readonly text: string;
  readonly title: string;
}

export const extractMarkdownTitle = (markdown: string): MarkdownWithTitle => {
  const heading = /^#[ \t]+([^\r\n]*)(?:\r?\n|$)/u.exec(markdown);
  const title = heading?.[1].trim();
  if (!heading || !title) {
    throw new Error("Markdown must start with a non-empty leading H1");
  }
  const text = markdown.slice(heading[0].length).replace(/^\r?\n/u, "");
  return { text, title };
};
