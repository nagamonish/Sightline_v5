import { useMemo, useRef, useState } from "react";

function nextSlotId(slots) {
  return `A${slots.length + 1}`;
}

function defaultPolygon(slots) {
  const offset = slots.length * 18;
  return [
    [300 + offset, 320],
    [500 + offset, 320],
    [540 + offset, 650],
    [260 + offset, 650],
  ];
}

function pointFromSvgEvent(svg, event) {
  const point = svg.createSVGPoint();
  point.x = event.clientX;
  point.y = event.clientY;
  const transformed = point.matrixTransform(svg.getScreenCTM().inverse());
  return [Number(transformed.x.toFixed(1)), Number(transformed.y.toFixed(1))];
}

export function CalibrationWizard({ apiUrl, onComplete }) {
  const svgRef = useRef(null);
  const [cameraId, setCameraId] = useState("cam1");
  const [name, setName] = useState("North Lot");
  const [rtspUrl, setRtspUrl] = useState("");
  const [status, setStatus] = useState("idle");
  const [slots, setSlots] = useState([]);
  const [selectedSlotId, setSelectedSlotId] = useState(null);
  const [dragTarget, setDragTarget] = useState(null);
  // Previously these were hardcoded to 1920x1080, which produced wrong
  // perspective transforms for any stream that wasn't full HD. Both are now
  // populated from the preview image's natural dimensions once it loads.
  const [previewSize, setPreviewSize] = useState(null);
  const [homography, setHomography] = useState(null);
  // Point-picking mode: when active, clicks on the preview stage drop
  // homography corners instead of editing slots. picking === null disables
  // the picker; otherwise it's the field being populated and the index of
  // the next corner (0..3, in TL, TR, BR, BL order).
  const [picking, setPicking] = useState(null);

  const PICK_LABELS = ["top-left", "top-right", "bottom-right", "bottom-left"];

  const base = apiUrl.replace(/\/$/, "");
  const previewStatuses = new Set([
    "preview",
    "calibrating",
    "needs-frame",
    "editing",
    "loading-sample",
    "sample-missing",
    "enter-rtsp",
    "saving",
    "saving-homography",
    "complete",
  ]);
  const streamUrl =
    cameraId && previewStatuses.has(status)
      ? `${base}/cameras/${cameraId}/stream`
      : "";
  const selectedSlot = slots.find((slot) => slot.slot_id === selectedSlotId);
  const viewBox = useMemo(() => {
    // Before the preview image has loaded we don't yet know the real frame
    // size, so fall back to a 16:9 1920x1080 viewport for the empty SVG.
    const width = previewSize?.width ?? 1920;
    const height = previewSize?.height ?? 1080;
    const points = slots.flatMap((slot) => slot.polygon);
    if (!points.length) {
      return `0 0 ${width} ${height}`;
    }
    const maxX = Math.max(width, ...points.map((point) => point[0]));
    const maxY = Math.max(height, ...points.map((point) => point[1]));
    return `0 0 ${maxX} ${maxY}`;
  }, [previewSize, slots]);

  async function testConnection() {
    setStatus("connecting");
    const response = await fetch(`${base}/cameras`, {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({
        camera_id: cameraId,
        name,
        rtsp_url: rtspUrl,
        slots: [],
      }),
    });
    if (!response.ok) {
      setStatus("error");
      return;
    }
    setStatus("preview");
  }

  async function captureEmptyLot() {
    setStatus("calibrating");
    const response = await fetch(`${base}/cameras/${cameraId}/calibrate`, {
      method: "POST",
    });
    if (!response.ok) {
      setStatus("needs-frame");
      return;
    }
    const payload = await response.json();
    setSlots(payload.slots || []);
    setSelectedSlotId(payload.slots?.[0]?.slot_id || null);
    setStatus("editing");
  }

  async function ensureCameraForSample() {
    if (!rtspUrl) {
      setStatus("enter-rtsp");
      return false;
    }

    const response = await fetch(`${base}/cameras`, {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({
        camera_id: cameraId,
        name,
        rtsp_url: rtspUrl,
        slots: [],
      }),
    });
    if (!response.ok) {
      setStatus("error");
      return false;
    }
    return true;
  }

  async function loadPklotSample() {
    setStatus("loading-sample");
    let response = await fetch(`${base}/cameras/${cameraId}/samples/pklot`, {
      method: "POST",
    });
    if (response.status === 404) {
      const payload = await response.json().catch(() => ({}));
      if (String(payload.detail || "").includes("camera")) {
        const cameraReady = await ensureCameraForSample();
        if (!cameraReady) {
          return;
        }
        response = await fetch(`${base}/cameras/${cameraId}/samples/pklot`, {
          method: "POST",
        });
      }
    }
    if (!response.ok) {
      setStatus(response.status === 404 ? "sample-missing" : "error");
      return;
    }
    const payload = await response.json();
    setSlots(payload.slots || []);
    setSelectedSlotId(payload.slots?.[0]?.slot_id || null);
    setStatus("editing");
  }

  async function confirmSlots() {
    setStatus("saving");
    const response = await fetch(`${base}/cameras/${cameraId}/slots`, {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({
        slots: slots.map(({ slot_id, polygon }) => ({ slot_id, polygon })),
      }),
    });
    setStatus(response.ok ? "complete" : "error");
    if (response.ok) {
      onComplete?.(cameraId);
    }
  }

  async function saveHomography() {
    setStatus("saving-homography");
    const response = await fetch(`${base}/cameras/${cameraId}/homography`, {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify(homography),
    });
    setStatus(response.ok ? "editing" : "error");
  }

  function updateDraggedPoint(event) {
    if (!dragTarget || !svgRef.current) {
      return;
    }
    const point = pointFromSvgEvent(svgRef.current, event);
    setSlots((current) =>
      current.map((slot) => {
        if (slot.slot_id !== dragTarget.slotId) {
          return slot;
        }
        return {
          ...slot,
          polygon: slot.polygon.map((corner, index) =>
            index === dragTarget.pointIndex ? point : corner,
          ),
        };
      }),
    );
  }

  function addSlot() {
    const slot = {
      slot_id: nextSlotId(slots),
      polygon: defaultPolygon(slots),
    };
    setSlots((current) => [...current, slot]);
    setSelectedSlotId(slot.slot_id);
    setStatus("editing");
  }

  function deleteSelectedSlot() {
    setSlots((current) =>
      current.filter((slot) => slot.slot_id !== selectedSlotId),
    );
    setSelectedSlotId(null);
  }

  function clearSlots() {
    setSlots([]);
    setSelectedSlotId(null);
    setStatus("editing");
  }

  function updateHomographyPoint(group, pointIndex, axis, value) {
    setHomography((current) => ({
      ...current,
      [group]: current[group].map((point, index) =>
        index === pointIndex
          ? point.map((coordinate, coordinateIndex) =>
              coordinateIndex === axis ? Number(value) : coordinate,
            )
          : point,
      ),
    }));
  }

  function startPicking(group) {
    if (!previewSize) {
      return; // can't pick without knowing the real frame size
    }
    setPicking({ group, index: 0 });
  }

  function cancelPicking() {
    setPicking(null);
  }

  function handleStageClick(event) {
    if (!picking || !svgRef.current || !homography) {
      return;
    }
    const point = pointFromSvgEvent(svgRef.current, event);
    const { group, index } = picking;
    setHomography((current) => ({
      ...current,
      [group]: current[group].map((existing, i) => (i === index ? point : existing)),
    }));
    if (index < 3) {
      setPicking({ group, index: index + 1 });
    } else {
      setPicking(null);
    }
  }

  return (
    <aside className="calibration-panel">
      <div className="panel-heading">
        <span className="eyebrow">Setup</span>
        <h2>Calibration</h2>
        <small>{status.replace("-", " ")}</small>
      </div>

      <div className="wizard-fields">
        <label>
          Camera ID
          <input value={cameraId} onChange={(event) => setCameraId(event.target.value)} />
        </label>
        <label>
          Name
          <input value={name} onChange={(event) => setName(event.target.value)} />
        </label>
        <label>
          RTSP URL
          <input
            placeholder="rtsp://user:pass@host/stream"
            value={rtspUrl}
            onChange={(event) => setRtspUrl(event.target.value)}
          />
        </label>
      </div>

      <div className="wizard-actions">
        <button disabled={!cameraId || !rtspUrl} onClick={testConnection} type="button">
          Test
        </button>
        <button disabled={status === "idle"} onClick={captureEmptyLot} type="button">
          Capture
        </button>
        <button disabled={!cameraId} onClick={loadPklotSample} type="button">
          Load PKLot
        </button>
        <button disabled={!slots.length} onClick={confirmSlots} type="button">
          Confirm
        </button>
      </div>

      <div
        className={`calibration-stage${picking ? " picking" : ""}`}
        onPointerMove={updateDraggedPoint}
        onPointerUp={() => setDragTarget(null)}
        onClick={picking ? handleStageClick : undefined}
        style={picking ? { cursor: "crosshair" } : undefined}
      >
        {picking ? (
          <div className="picking-banner">
            Click the <strong>{PICK_LABELS[picking.index]}</strong> corner of the{" "}
            <strong>{picking.group === "src_points" ? "source" : "destination"}</strong>{" "}
            quad ({picking.index + 1} of 4) ·{" "}
            <button onClick={cancelPicking} type="button">
              cancel
            </button>
          </div>
        ) : null}
        {streamUrl ? (
          <img
            alt=""
            aria-hidden="true"
            onLoad={(event) => {
              const width = event.currentTarget.naturalWidth;
              const height = event.currentTarget.naturalHeight;
              if (!width || !height) {
                return;
              }
              setPreviewSize({ width, height });
              // Seed the homography to an identity transform on the actual
              // frame the user is looking at. Only do this on first load so
              // any edits the user has already made aren't blown away.
              setHomography((current) =>
                current ?? {
                  src_points: [
                    [0, 0],
                    [width, 0],
                    [width, height],
                    [0, height],
                  ],
                  dst_points: [
                    [0, 0],
                    [width, 0],
                    [width, height],
                    [0, height],
                  ],
                },
              );
            }}
            src={streamUrl}
          />
        ) : null}
        {!streamUrl ? <div className="calibration-placeholder">Preview</div> : null}
        <svg ref={svgRef} viewBox={viewBox}>
          {slots.map((slot) => (
            <g key={slot.slot_id}>
              <polygon
                className={slot.slot_id === selectedSlotId ? "selected" : ""}
                onClick={() => setSelectedSlotId(slot.slot_id)}
                points={slot.polygon.map((point) => point.join(",")).join(" ")}
              />
              {slot.slot_id === selectedSlotId
                ? slot.polygon.map((point, pointIndex) => (
                    <circle
                      cx={point[0]}
                      cy={point[1]}
                      key={`${slot.slot_id}-${pointIndex}`}
                      onPointerDown={(event) => {
                        event.currentTarget.setPointerCapture(event.pointerId);
                        setDragTarget({ slotId: slot.slot_id, pointIndex });
                        setSelectedSlotId(slot.slot_id);
                      }}
                      r="14"
                    />
                  ))
                : null}
              {slot.slot_id === selectedSlotId ? (
                <text x={slot.polygon[0][0]} y={slot.polygon[0][1] - 18}>
                  {slot.slot_id}
                </text>
              ) : null}
            </g>
          ))}

          {/* Homography quad overlays. Render the source quad as a closed
              polyline plus numbered handles so users can see exactly which
              corners they've placed. Destination quad rendered the same way
              when its been edited away from identity. */}
          {homography
            ? ["src_points", "dst_points"].map((group) => (
                <g
                  className={`homography-quad ${group}`}
                  key={group}
                  pointerEvents="none"
                >
                  <polygon
                    fill="none"
                    points={homography[group]
                      .map((point) => point.join(","))
                      .join(" ")}
                    stroke={group === "src_points" ? "#3ad29f" : "#f5a623"}
                    strokeDasharray={group === "dst_points" ? "8 6" : undefined}
                    strokeWidth={3}
                  />
                  {homography[group].map((point, index) => (
                    <g key={`${group}-${index}`}>
                      <circle
                        cx={point[0]}
                        cy={point[1]}
                        fill={group === "src_points" ? "#3ad29f" : "#f5a623"}
                        r="10"
                      />
                      <text
                        fill="#0b0b16"
                        fontSize="14"
                        fontWeight="700"
                        textAnchor="middle"
                        x={point[0]}
                        y={point[1] + 5}
                      >
                        {index + 1}
                      </text>
                    </g>
                  ))}
                </g>
              ))
            : null}
        </svg>
      </div>

      <div className="editor-actions">
        <button onClick={addSlot} type="button">
          Add space
        </button>
        <button disabled={!selectedSlot} onClick={deleteSelectedSlot} type="button">
          Delete
        </button>
        <button disabled={!slots.length} onClick={clearSlots} type="button">
          Clear
        </button>
        <span>{slots.length} spaces</span>
      </div>

      <div className="homography-grid">
        <span>Homography</span>
        <div className="homography-pickers">
          <button
            disabled={!previewSize || picking !== null}
            onClick={() => startPicking("src_points")}
            type="button"
          >
            Pick source corners
          </button>
          <button
            disabled={!previewSize || picking !== null}
            onClick={() => startPicking("dst_points")}
            type="button"
          >
            Pick destination corners
          </button>
          {picking ? (
            <small>
              picking {picking.group === "src_points" ? "source" : "destination"}{" "}
              · corner {picking.index + 1} of 4
            </small>
          ) : (
            <small>or fine-tune the numeric inputs below</small>
          )}
        </div>
        {homography ? (
          [0, 1, 2, 3].map((index) => (
            <div className="homography-row" key={index}>
              <input
                aria-label={`Source x ${index + 1}`}
                value={homography.src_points[index][0]}
                onChange={(event) =>
                  updateHomographyPoint("src_points", index, 0, event.target.value)
                }
              />
              <input
                aria-label={`Source y ${index + 1}`}
                value={homography.src_points[index][1]}
                onChange={(event) =>
                  updateHomographyPoint("src_points", index, 1, event.target.value)
                }
              />
              <input
                aria-label={`Destination x ${index + 1}`}
                value={homography.dst_points[index][0]}
                onChange={(event) =>
                  updateHomographyPoint("dst_points", index, 0, event.target.value)
                }
              />
              <input
                aria-label={`Destination y ${index + 1}`}
                value={homography.dst_points[index][1]}
                onChange={(event) =>
                  updateHomographyPoint("dst_points", index, 1, event.target.value)
                }
              />
            </div>
          ))
        ) : (
          <div className="homography-placeholder">
            Waiting for preview frame to determine real dimensions…
          </div>
        )}
        <button
          disabled={!cameraId || !homography || !previewSize}
          onClick={saveHomography}
          type="button"
        >
          Apply transform
        </button>
      </div>
    </aside>
  );
}
