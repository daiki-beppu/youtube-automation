import React from "react";
import ReactDOM from "react-dom/client";
import { App } from "./App";
import "./style.css";

const root = document.getElementById("root");
if (root === null) {
  throw new Error("popup root element (#root) が見つかりません");
}

ReactDOM.createRoot(root).render(
  <React.StrictMode>
    <App />
  </React.StrictMode>,
);
