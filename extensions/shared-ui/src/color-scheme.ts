export interface ColorSchemeTarget {
  classList: Pick<DOMTokenList, "toggle">;
}

const DARK_MODE_QUERY = "(prefers-color-scheme: dark)";

export function watchColorScheme(target: ColorSchemeTarget): () => void {
  const mediaQuery = window.matchMedia(DARK_MODE_QUERY);
  const update = ({ matches }: MediaQueryList | MediaQueryListEvent): void => {
    target.classList.toggle("dark", matches);
  };

  update(mediaQuery);
  mediaQuery.addEventListener("change", update);

  return () => mediaQuery.removeEventListener("change", update);
}
