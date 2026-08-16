import { useState } from "react";
import EventsView from "./components/EventsView";
import VideosView from "./components/VideosView";

type Tab = "events" | "videos";

export default function App() {
  const [tab, setTab] = useState<Tab>("events");

  return (
    <div className="app-shell">
      <header className="topbar">
        <div className="brand">
          <span className="brand-mark" aria-hidden="true">
            🐒
          </span>
          <div className="brand-text">
            <span className="brand-title">Primate Event Intelligence</span>
            <span className="brand-subtitle">Chimp behavior monitoring &amp; flagged-event review</span>
          </div>
        </div>
        <nav className="tabs" role="tablist">
          <button
            role="tab"
            aria-selected={tab === "events"}
            className={tab === "events" ? "tab active" : "tab"}
            onClick={() => setTab("events")}
          >
            Flagged Events
          </button>
          <button
            role="tab"
            aria-selected={tab === "videos"}
            className={tab === "videos" ? "tab active" : "tab"}
            onClick={() => setTab("videos")}
          >
            Videos
          </button>
        </nav>
      </header>
      <main className="content">{tab === "events" ? <EventsView /> : <VideosView />}</main>
    </div>
  );
}
