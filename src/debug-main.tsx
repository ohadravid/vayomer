import React from "react";
import { createRoot } from "react-dom/client";
import { DebugPage } from "./DebugPage";
import "./i18n";
import "../styles.css";

const root = document.getElementById("root");
if (root) {
  createRoot(root).render(
    <React.StrictMode>
      <DebugPage />
    </React.StrictMode>
  );
}
