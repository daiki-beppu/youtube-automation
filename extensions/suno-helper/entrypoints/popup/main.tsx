import { StrictMode } from "react";
import { createRoot } from "react-dom/client";

import { App } from "../../components/App";

import "./style.css";

const root = document.getElementById("root");
if (!root) {
  throw new Error("popup root 要素が見つかりません。");
}

createRoot(root).render(
  <StrictMode>
    <App />
  </StrictMode>
);
