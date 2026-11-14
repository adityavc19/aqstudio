// Router: hash-based so the server serves one static page.
import { closeEvidence } from "./evidence.js";
import { briefView } from "./views/brief.js";
import { citizenView } from "./views/citizen.js";
import { homeView } from "./views/home.js";
import { reviewView } from "./views/review.js";

function route() {
  closeEvidence();
  const [path, query = ""] = location.hash.replace(/^#/, "").split("?");
  const parts = path.split("/").filter(Boolean);
  if (parts[0] === "review" && parts[1]) return reviewView(parts[1]);
  if (parts[0] === "brief" && parts[1]) return briefView(parts[1], new URLSearchParams(query).get("against"));
  if (parts[0] === "c" && parts[1]) return citizenView(parts[1]);
  return homeView();
}

window.addEventListener("hashchange", route);
route();
