export interface ColorSchemeTarget {
  classList: Pick<DOMTokenList, "add" | "remove">;
}

const DARK_MODE_QUERY = "(prefers-color-scheme: dark)";

export function watchColorScheme(target: ColorSchemeTarget): () => void {
  const mediaQuery = window.matchMedia(DARK_MODE_QUERY);
  const update = ({ matches }: MediaQueryList | MediaQueryListEvent): void => {
    target.classList.remove("light", "dark");
    target.classList.add(matches ? "dark" : "light");
  };

  update(mediaQuery);
  mediaQuery.addEventListener("change", update);

  return () => mediaQuery.removeEventListener("change", update);
}
