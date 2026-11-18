window.DecorThemeConfig = Object.freeze({
  defaultTheme: "original",
  storageKey: "decor.theme.v1",
  themes: [
    { id: "original", label: "原版", stylesheets: [] },
    { id: "studio", label: "Studio（试验）", stylesheets: ["./studio/theme.css?v=20261110-modular"] },
  ],
});
