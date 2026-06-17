import { useEffect, useMemo, useState } from "react";

import { CalibrationWizard } from "../components/CalibrationWizard.jsx";
import { SlotGrid } from "../components/SlotGrid.jsx";
import { SlotMapCanvas } from "../components/SlotMapCanvas.jsx";
import { StatCards } from "../components/StatCards.jsx";
import { useCameraStream } from "../hooks/useCameraStream.js";
import { useWebSocket } from "../hooks/useWebSocket.js";

const API_URL = import.meta.env.VITE_API_URL || "http://localhost:8000";

// Derive the WebSocket URL at *runtime* (not build time) so the same
// production bundle works for any viewer, regardless of which host they
// loaded the page from. Falls back to API_URL-based derivation when the
// API URL is absolute (dev with the Vite dev server on :5173 talking to
// the backend on :8000). VITE_WS_URL is still honored as an explicit
// override for unusual setups.
function deriveWsUrl() {
  if (import.meta.env.VITE_WS_URL) {
    return import.meta.env.VITE_WS_URL;
  }
  if (/^https?:\/\//i.test(API_URL)) {
    return API_URL.replace(/^http/i, "ws").replace(/\/+$/, "") + "/ws";
  }
  // Relative API (e.g. production behind nginx). Use the page's own host
  // and auto-select ws/wss based on the page protocol.
  if (typeof window !== "undefined" && window.location) {
    const proto = window.location.protocol === "https:" ? "wss:" : "ws:";
    return `${proto}//${window.location.host}/ws`;
  }
  return "ws://localhost/ws";
}

const WS_URL = deriveWsUrl();

function mergeChangedSlots(currentSlots, changedSlots) {
  const byId = new Map(currentSlots.map((slot) => [slot.slot_id, slot]));
  changedSlots.forEach((slot) => {
    byId.set(slot.slot_id, { ...byId.get(slot.slot_id), ...slot });
  });
  return [...byId.values()].sort((a, b) => a.slot_id.localeCompare(b.slot_id));
}

function cameraStatusClass(status) {
  if (status === "connected") {
    return "connected";
  }
  if (status === "reconnecting" || status === "connecting") {
    return "reconnecting";
  }
  return "offline";
}

export default function Dashboard() {
  const { status: wsStatus, lastMessage } = useWebSocket(WS_URL);
  const [cameras, setCameras] = useState({});
  const [summary, setSummary] = useState([]);
  const [selectedCameraId, setSelectedCameraId] = useState("");
  const [wizardOpen, setWizardOpen] = useState(false);

  const selectedSummary = summary.find(
    (camera) => camera.camera_id === selectedCameraId,
  );
  const selectedSlots = cameras[selectedCameraId] || [];
  const { streamUrl, streamState, markLoaded, markError, reset } =
    useCameraStream(selectedCameraId, API_URL);

  const summaryById = useMemo(
    () => new Map(summary.map((camera) => [camera.camera_id, camera])),
    [summary],
  );

  useEffect(() => {
    let cancelled = false;

    async function loadInitialState() {
      try {
        const response = await fetch(`${API_URL.replace(/\/$/, "")}/cameras`);
        if (!response.ok) {
          return;
        }
        const camerasPayload = await response.json();
        if (cancelled) {
          return;
        }
        setSummary(camerasPayload);
        setSelectedCameraId((current) => current || camerasPayload[0]?.camera_id || "");

        const slotPairs = await Promise.all(
          camerasPayload.map(async (camera) => {
            const slotResponse = await fetch(
              `${API_URL.replace(/\/$/, "")}/cameras/${camera.camera_id}/slots`,
            );
            return [
              camera.camera_id,
              slotResponse.ok ? await slotResponse.json() : [],
            ];
          }),
        );
        if (!cancelled) {
          setCameras(Object.fromEntries(slotPairs));
        }
      } catch {
        setSummary([]);
      }
    }

    loadInitialState();
    return () => {
      cancelled = true;
    };
  }, []);

  useEffect(() => {
    if (!lastMessage) {
      return;
    }

    if (lastMessage.type === "full_state") {
      setCameras(lastMessage.cameras || {});
      setSummary(lastMessage.summary || []);
      setSelectedCameraId(
        (current) =>
          current ||
          lastMessage.summary?.[0]?.camera_id ||
          Object.keys(lastMessage.cameras || {})[0] ||
          "",
      );
      return;
    }

    if (lastMessage.type === "occupancy_update") {
      setCameras((current) => ({
        ...current,
        [lastMessage.camera_id]: mergeChangedSlots(
          current[lastMessage.camera_id] || [],
          lastMessage.slots || [],
        ),
      }));
      setSummary(lastMessage.summary || []);
    }
  }, [lastMessage]);

  useEffect(() => {
    reset();
  }, [reset, selectedCameraId]);

  return (
    <main className="app-shell">
      <style>{styles}</style>
      <aside className="sidebar">
        <div className="brand">
          <div className="brand-mark">P</div>
          <div>
            <strong>ParkIQ</strong>
            <span>AI Parking Ops</span>
          </div>
        </div>

        <div className="sidebar-section">
          <div className="section-title">
            <span>Cameras</span>
            <button onClick={() => setWizardOpen((open) => !open)} type="button">
              {wizardOpen ? "Close" : "Add"}
            </button>
          </div>
          <div className="camera-list">
            {summary.length ? (
              summary.map((camera) => (
                <button
                  className={`camera-row ${
                    selectedCameraId === camera.camera_id ? "active" : ""
                  }`}
                  key={camera.camera_id}
                  onClick={() => setSelectedCameraId(camera.camera_id)}
                  type="button"
                >
                  <span className={`dot ${cameraStatusClass(camera.status)}`} />
                  <span>
                    <strong>{camera.name || camera.camera_id}</strong>
                    <small>
                      {camera.available}/{camera.total} free
                    </small>
                  </span>
                  <em className={cameraStatusClass(camera.status)}>
                    {camera.status}
                  </em>
                </button>
              ))
            ) : (
              <div className="empty-panel">No cameras online</div>
            )}
          </div>
        </div>

        <div className="sidebar-section compact">
          <span className="section-label">Socket</span>
          <strong className={`socket-state ${wsStatus}`}>{wsStatus}</strong>
        </div>
      </aside>

      <section className="dashboard-main">
        <header className="topbar">
          <div>
            <span className="eyebrow">Live Occupancy</span>
            <h1>{selectedSummary?.name || "Parking Control"}</h1>
          </div>
          <div className="topbar-meta">
            <span>{selectedSlots.length} mapped spaces</span>
            <strong className={cameraStatusClass(selectedSummary?.status)}>
              {selectedSummary?.status || "offline"}
            </strong>
          </div>
        </header>

        <StatCards summary={summary} />

        <div className={`workspace ${wizardOpen ? "with-wizard" : ""}`}>
          <div className="primary-column">
            <SlotMapCanvas
              cameraId={selectedCameraId}
              onError={markError}
              onLoad={markLoaded}
              slots={selectedSlots}
              streamState={
                selectedSummary?.status === "reconnecting"
                  ? "reconnecting"
                  : streamState
              }
              streamUrl={streamUrl}
            />
            <SlotGrid slots={selectedSlots} />
          </div>

          {wizardOpen ? (
            <CalibrationWizard
              apiUrl={API_URL}
              onComplete={(cameraId) => {
                setSelectedCameraId(cameraId);
                setWizardOpen(false);
              }}
            />
          ) : null}
        </div>
      </section>
    </main>
  );
}

const styles = `
:root {
  color-scheme: dark;
  --bg: #0b0b16;
  --panel: #12131f;
  --panel-strong: #171927;
  --panel-soft: #0f101b;
  --border: rgba(255, 255, 255, 0.09);
  --text: #f7f8ff;
  --muted: #8d93aa;
  --green: #2ee987;
  --green-soft: rgba(46, 233, 135, 0.12);
  --red: #ff5b6f;
  --red-soft: rgba(255, 91, 111, 0.13);
  --yellow: #f4c95d;
  --yellow-soft: rgba(244, 201, 93, 0.14);
  --blue: #6eb7ff;
  --shadow: 0 24px 80px rgba(0, 0, 0, 0.34);
  font-family: Inter, ui-sans-serif, system-ui, -apple-system, BlinkMacSystemFont, "Segoe UI", sans-serif;
}

* {
  box-sizing: border-box;
}

body {
  margin: 0;
  background: var(--bg);
  color: var(--text);
}

button,
input {
  font: inherit;
}

button {
  cursor: pointer;
}

.app-shell {
  min-height: 100vh;
  display: grid;
  grid-template-columns: 280px minmax(0, 1fr);
  background:
    linear-gradient(180deg, rgba(255, 255, 255, 0.025), transparent 34%),
    var(--bg);
}

.sidebar {
  border-right: 1px solid var(--border);
  padding: 24px 18px;
  background: rgba(9, 10, 18, 0.94);
  display: flex;
  flex-direction: column;
  gap: 24px;
}

.brand {
  display: flex;
  gap: 12px;
  align-items: center;
}

.brand-mark {
  width: 42px;
  height: 42px;
  display: grid;
  place-items: center;
  border: 1px solid rgba(46, 233, 135, 0.38);
  background: #102117;
  color: var(--green);
  border-radius: 8px;
  font-weight: 900;
}

.brand strong,
.brand span {
  display: block;
}

.brand span,
.section-label,
.eyebrow,
.stat-label {
  color: var(--muted);
  font-size: 12px;
  line-height: 1.2;
}

.sidebar-section {
  display: grid;
  gap: 12px;
}

.sidebar-section.compact {
  margin-top: auto;
  padding-top: 18px;
  border-top: 1px solid var(--border);
}

.section-title {
  display: flex;
  align-items: center;
  justify-content: space-between;
}

.section-title span {
  font-size: 13px;
  color: var(--muted);
  text-transform: uppercase;
}

.section-title button,
.wizard-actions button,
.editor-actions button,
.homography-grid button {
  min-height: 34px;
  border: 1px solid var(--border);
  color: var(--text);
  background: var(--panel-strong);
  border-radius: 7px;
  padding: 0 12px;
}

.section-title button:hover,
.wizard-actions button:hover,
.editor-actions button:hover,
.homography-grid button:hover {
  border-color: rgba(46, 233, 135, 0.42);
}

.camera-list {
  display: grid;
  gap: 8px;
}

.camera-row {
  width: 100%;
  display: grid;
  grid-template-columns: 10px minmax(0, 1fr) auto;
  gap: 10px;
  align-items: center;
  border: 1px solid transparent;
  background: transparent;
  color: var(--text);
  text-align: left;
  border-radius: 8px;
  padding: 12px 10px;
}

.camera-row.active,
.camera-row:hover {
  background: var(--panel);
  border-color: var(--border);
}

.camera-row strong,
.camera-row small {
  display: block;
  overflow: hidden;
  text-overflow: ellipsis;
  white-space: nowrap;
}

.camera-row small,
.camera-row em {
  color: var(--muted);
  font-size: 12px;
  font-style: normal;
}

.dot {
  width: 8px;
  height: 8px;
  border-radius: 99px;
  background: var(--muted);
}

.dot.connected {
  color: var(--green);
  background: var(--green);
}

.dot.reconnecting {
  color: var(--yellow);
  background: var(--yellow);
}

.dot.offline {
  color: var(--muted);
  background: var(--muted);
}

.camera-row em.connected,
.topbar-meta strong.connected {
  color: var(--green);
}

.camera-row em.reconnecting,
.topbar-meta strong.reconnecting {
  color: var(--yellow);
}

.camera-row em.offline,
.topbar-meta strong.offline {
  color: var(--muted);
}

.socket-state {
  text-transform: capitalize;
}

.socket-state.connected {
  color: var(--green);
}

.socket-state.reconnecting,
.socket-state.connecting {
  color: var(--yellow);
}

.dashboard-main {
  min-width: 0;
  padding: 26px;
  display: grid;
  gap: 18px;
  align-content: start;
}

.topbar,
.stream-toolbar,
.panel-heading {
  display: flex;
  justify-content: space-between;
  align-items: center;
  gap: 16px;
}

.topbar h1,
.stream-toolbar h2,
.panel-heading h2 {
  margin: 4px 0 0;
  font-size: clamp(22px, 2.1vw, 34px);
  line-height: 1.05;
  letter-spacing: 0;
}

.stream-toolbar h2,
.panel-heading h2 {
  font-size: 18px;
}

.topbar-meta {
  display: flex;
  gap: 10px;
  align-items: center;
  color: var(--muted);
  font-size: 13px;
}

.topbar-meta strong {
  border: 1px solid currentColor;
  border-radius: 7px;
  padding: 7px 9px;
  background: rgba(255, 255, 255, 0.03);
  text-transform: capitalize;
}

.stat-grid {
  display: grid;
  grid-template-columns: repeat(4, minmax(0, 1fr));
  gap: 12px;
}

.stat-card {
  min-height: 104px;
  border: 1px solid var(--border);
  border-radius: 8px;
  padding: 16px;
  background: var(--panel);
  display: grid;
  align-content: space-between;
}

.stat-card strong {
  font-size: clamp(28px, 3vw, 42px);
  line-height: 1;
}

.stat-card.available {
  background: linear-gradient(135deg, var(--green-soft), var(--panel));
}

.stat-card.occupied {
  background: linear-gradient(135deg, var(--red-soft), var(--panel));
}

.stat-card.percent {
  background: linear-gradient(135deg, rgba(110, 183, 255, 0.13), var(--panel));
}

.workspace {
  display: grid;
  grid-template-columns: minmax(0, 1fr);
  gap: 16px;
  align-items: start;
}

.workspace.with-wizard {
  grid-template-columns: minmax(0, 1fr) minmax(340px, 400px);
}

.primary-column {
  min-width: 0;
  display: grid;
  gap: 14px;
}

.stream-panel,
.slot-grid-shell,
.calibration-panel {
  border: 1px solid var(--border);
  border-radius: 8px;
  background: var(--panel-soft);
  box-shadow: var(--shadow);
}

.stream-panel {
  padding: 14px;
}

.status-badge {
  border: 1px solid currentColor;
  border-radius: 7px;
  padding: 7px 10px;
  color: var(--muted);
  text-transform: capitalize;
  font-size: 12px;
}

.status-badge.live {
  color: var(--green);
}

.status-badge.reconnecting,
.status-badge.loading {
  color: var(--yellow);
}

.stream-stage {
  position: relative;
  margin-top: 14px;
  min-height: 420px;
  aspect-ratio: 16 / 9;
  overflow: hidden;
  border-radius: 8px;
  background:
    linear-gradient(90deg, rgba(255, 255, 255, 0.035) 1px, transparent 1px),
    linear-gradient(rgba(255, 255, 255, 0.035) 1px, transparent 1px),
    #080910;
  background-size: 48px 48px;
}

.stream-image,
.slot-canvas,
.stream-placeholder {
  position: absolute;
  inset: 0;
}

.stream-image {
  width: 100%;
  height: 100%;
  object-fit: contain;
}

.slot-canvas {
  width: 100%;
  height: 100%;
}

.stream-placeholder {
  display: grid;
  place-items: center;
  color: var(--muted);
}

.slot-tooltip {
  position: absolute;
  top: 0;
  left: 0;
  z-index: 3;
  pointer-events: none;
  border: 1px solid var(--border);
  border-radius: 7px;
  background: rgba(6, 8, 14, 0.92);
  color: var(--text);
  padding: 8px 10px;
  font-size: 12px;
}

.slot-grid-shell {
  padding: 12px;
}

.slot-grid {
  display: grid;
  grid-template-columns: repeat(auto-fill, minmax(86px, 1fr));
  gap: 8px;
}

.slot-pill {
  min-height: 54px;
  border-radius: 8px;
  border: 1px solid var(--border);
  color: var(--text);
  background: var(--panel);
  display: grid;
  gap: 2px;
  justify-items: start;
  padding: 8px 10px;
  transition: transform 180ms ease, border-color 180ms ease;
}

.slot-pill.free {
  border-color: rgba(46, 233, 135, 0.38);
  background: var(--green-soft);
}

.slot-pill.occupied {
  border-color: rgba(255, 91, 111, 0.42);
  background: var(--red-soft);
}

.slot-pill.changed {
  animation: pulseSlot 900ms ease;
}

.slot-pill span {
  font-weight: 800;
}

.slot-pill small {
  color: var(--muted);
}

.empty-panel,
.empty-slots {
  min-height: 88px;
  border: 1px dashed var(--border);
  border-radius: 8px;
  display: grid;
  place-items: center;
  color: var(--muted);
}

.calibration-panel {
  padding: 16px;
  display: grid;
  gap: 14px;
  position: sticky;
  top: 20px;
}

.panel-heading small {
  color: var(--yellow);
  text-transform: capitalize;
}

.wizard-fields {
  display: grid;
  gap: 10px;
}

.wizard-fields label {
  display: grid;
  gap: 6px;
  color: var(--muted);
  font-size: 12px;
}

.wizard-fields input,
.homography-row input {
  min-width: 0;
  width: 100%;
  border: 1px solid var(--border);
  border-radius: 7px;
  background: #090a13;
  color: var(--text);
  padding: 10px 11px;
  outline: none;
}

.wizard-fields input:focus,
.homography-row input:focus {
  border-color: rgba(46, 233, 135, 0.44);
}

.wizard-actions,
.editor-actions {
  display: flex;
  gap: 8px;
  align-items: center;
  flex-wrap: wrap;
}

.wizard-actions button:disabled,
.editor-actions button:disabled,
.homography-grid button:disabled {
  opacity: 0.48;
  cursor: not-allowed;
}

.editor-actions span {
  color: var(--muted);
  font-size: 12px;
  margin-left: auto;
}

.calibration-stage {
  position: relative;
  aspect-ratio: 16 / 10;
  overflow: hidden;
  border-radius: 8px;
  border: 1px solid var(--border);
  background: #080910;
}

.calibration-stage img,
.calibration-stage svg,
.calibration-placeholder {
  position: absolute;
  inset: 0;
  width: 100%;
  height: 100%;
}

.calibration-stage img,
.calibration-stage svg {
  object-fit: contain;
}

.calibration-placeholder {
  display: grid;
  place-items: center;
  color: var(--muted);
  font-size: 13px;
}

.calibration-stage polygon {
  fill: rgba(46, 233, 135, 0.14);
  stroke: var(--green);
  stroke-width: 4;
  cursor: pointer;
  opacity: 0.62;
}

.calibration-stage polygon.selected {
  fill: rgba(244, 201, 93, 0.16);
  stroke: var(--yellow);
  opacity: 1;
}

.calibration-stage circle {
  fill: #ffffff;
  stroke: #090a13;
  stroke-width: 4;
  cursor: grab;
}

.calibration-stage text {
  fill: #ffffff;
  font: 700 42px Inter, sans-serif;
}

.homography-grid {
  display: grid;
  gap: 8px;
}

.homography-grid > span {
  color: var(--muted);
  font-size: 12px;
}

.homography-row {
  display: grid;
  grid-template-columns: repeat(4, minmax(0, 1fr));
  gap: 6px;
}

@keyframes pulseSlot {
  0% {
    transform: scale(1);
  }
  40% {
    transform: scale(1.04);
  }
  100% {
    transform: scale(1);
  }
}

@media (max-width: 1180px) {
  .app-shell {
    grid-template-columns: 1fr;
  }

  .sidebar {
    position: static;
    border-right: 0;
    border-bottom: 1px solid var(--border);
  }

  .workspace.with-wizard {
    grid-template-columns: 1fr;
  }

  .calibration-panel {
    position: static;
  }
}

@media (max-width: 720px) {
  .dashboard-main,
  .sidebar {
    padding: 16px;
  }

  .stat-grid {
    grid-template-columns: repeat(2, minmax(0, 1fr));
  }

  .topbar,
  .stream-toolbar,
  .panel-heading {
    align-items: flex-start;
    flex-direction: column;
  }

  .stream-stage {
    min-height: 280px;
  }
}
`;
