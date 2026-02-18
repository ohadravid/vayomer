import React from "react";
import { createRoot } from "react-dom/client";
import { PreviewPage } from "./PreviewPage";
import "./i18n";
import "../styles.css";
import "./preview.css";

const root = document.getElementById("root");
if (root) {
  createRoot(root).render(
    <React.StrictMode>
      <PreviewPage />
    </React.StrictMode>
  );
}
