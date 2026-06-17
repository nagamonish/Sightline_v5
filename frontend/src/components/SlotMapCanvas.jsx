import { useCallback, useEffect, useMemo, useRef, useState } from "react";

function formatOccupiedTime(slot) {
  if (!slot.occupied || !slot.occupied_since) {
    return "available";
  }
  const seconds = Math.max(0, Math.floor(Date.now() / 1000 - slot.occupied_since));
  if (seconds < 60) {
    return `occupied ${seconds}s`;
  }
  const minutes = Math.floor(seconds / 60);
  if (minutes < 60) {
    return `occupied ${minutes}m`;
  }
  return `occupied ${Math.floor(minutes / 60)}h ${minutes % 60}m`;
}

function pointInPolygon(point, polygon) {
  let inside = false;
  for (let i = 0, j = polygon.length - 1; i < polygon.length; j = i, i += 1) {
    const xi = polygon[i][0];
    const yi = polygon[i][1];
    const xj = polygon[j][0];
    const yj = polygon[j][1];
    const intersects =
      yi > point.y !== yj > point.y &&
      point.x < ((xj - xi) * (point.y - yi)) / (yj - yi || 1) + xi;
    if (intersects) {
      inside = !inside;
    }
  }
  return inside;
}

function polygonCenter(polygon) {
  const total = polygon.reduce(
    (acc, point) => {
      acc.x += point[0];
      acc.y += point[1];
      return acc;
    },
    { x: 0, y: 0 },
  );
  return {
    x: total.x / polygon.length,
    y: total.y / polygon.length,
  };
}

export function SlotMapCanvas({
  cameraId,
  slots,
  streamUrl,
  streamState,
  onLoad,
  onError,
}) {
  const canvasRef = useRef(null);
  const imageRef = useRef(null);
  const wrapperRef = useRef(null);
  const [size, setSize] = useState({ width: 0, height: 0 });
  const [hoveredSlotId, setHoveredSlotId] = useState(null);
  const [tooltip, setTooltip] = useState(null);

  const bounds = useMemo(() => {
    const points = slots.flatMap((slot) => slot.polygon || []);
    if (!points.length) {
      return { width: 1920, height: 1080 };
    }
    return {
      width: Math.max(1, Math.max(...points.map((point) => point[0]))),
      height: Math.max(1, Math.max(...points.map((point) => point[1]))),
    };
  }, [slots]);

  const getTransform = useCallback(() => {
    const image = imageRef.current;
    const naturalWidth = image?.naturalWidth || bounds.width;
    const naturalHeight = image?.naturalHeight || bounds.height;
    const scale = Math.min(
      size.width / naturalWidth || 1,
      size.height / naturalHeight || 1,
    );
    const renderWidth = naturalWidth * scale;
    const renderHeight = naturalHeight * scale;
    return {
      scale,
      offsetX: (size.width - renderWidth) / 2,
      offsetY: (size.height - renderHeight) / 2,
      naturalWidth,
      naturalHeight,
    };
  }, [bounds.height, bounds.width, size.height, size.width]);

  const toCanvasPoint = useCallback(
    (point) => {
      const transform = getTransform();
      return {
        x: point[0] * transform.scale + transform.offsetX,
        y: point[1] * transform.scale + transform.offsetY,
      };
    },
    [getTransform],
  );

  const toImagePoint = useCallback(
    (point) => {
      const transform = getTransform();
      return {
        x: (point.x - transform.offsetX) / transform.scale,
        y: (point.y - transform.offsetY) / transform.scale,
      };
    },
    [getTransform],
  );

  useEffect(() => {
    const wrapper = wrapperRef.current;
    if (!wrapper) {
      return undefined;
    }

    const observer = new ResizeObserver(([entry]) => {
      setSize({
        width: Math.round(entry.contentRect.width),
        height: Math.round(entry.contentRect.height),
      });
    });
    observer.observe(wrapper);
    return () => observer.disconnect();
  }, []);

  useEffect(() => {
    const canvas = canvasRef.current;
    if (!canvas || !size.width || !size.height) {
      return;
    }

    const ratio = window.devicePixelRatio || 1;
    canvas.width = size.width * ratio;
    canvas.height = size.height * ratio;
    canvas.style.width = `${size.width}px`;
    canvas.style.height = `${size.height}px`;

    const context = canvas.getContext("2d");
    context.setTransform(ratio, 0, 0, ratio, 0, 0);
    context.clearRect(0, 0, size.width, size.height);

    slots.forEach((slot) => {
      const polygon = slot.polygon || [];
      if (polygon.length < 3) {
        return;
      }

      const points = polygon.map(toCanvasPoint);
      const color = slot.occupied ? "#ff5b6f" : "#2ee987";
      const fill = slot.occupied
        ? "rgba(255, 91, 111, 0.20)"
        : "rgba(46, 233, 135, 0.17)";

      context.beginPath();
      points.forEach((point, index) => {
        if (index === 0) {
          context.moveTo(point.x, point.y);
        } else {
          context.lineTo(point.x, point.y);
        }
      });
      context.closePath();
      context.fillStyle = fill;
      context.strokeStyle = hoveredSlotId === slot.slot_id ? "#ffffff" : color;
      context.lineWidth = hoveredSlotId === slot.slot_id ? 3 : 2;
      context.fill();
      context.stroke();

      const center = toCanvasPoint([
        polygonCenter(polygon).x,
        polygonCenter(polygon).y,
      ]);
      context.font = "700 13px Inter, ui-sans-serif, system-ui";
      context.textAlign = "center";
      context.textBaseline = "middle";
      context.fillStyle = "#f7fbff";
      context.shadowColor = "rgba(0, 0, 0, 0.55)";
      context.shadowBlur = 4;
      context.fillText(slot.slot_id, center.x, center.y);
      context.shadowBlur = 0;
    });
  }, [hoveredSlotId, size.height, size.width, slots, toCanvasPoint]);

  const handlePointerMove = (event) => {
    const canvas = canvasRef.current;
    if (!canvas) {
      return;
    }
    const rect = canvas.getBoundingClientRect();
    const canvasPoint = {
      x: event.clientX - rect.left,
      y: event.clientY - rect.top,
    };
    const imagePoint = toImagePoint(canvasPoint);
    const match = slots.find((slot) =>
      pointInPolygon(imagePoint, slot.polygon || []),
    );

    setHoveredSlotId(match?.slot_id || null);
    setTooltip(
      match
        ? {
            x: canvasPoint.x,
            y: canvasPoint.y,
            label: `${match.slot_id} · ${formatOccupiedTime(match)}`,
          }
        : null,
    );
  };

  return (
    <section className="stream-panel">
      <div className="stream-toolbar">
        <div>
          <span className="eyebrow">Camera</span>
          <h2>{cameraId || "No camera selected"}</h2>
        </div>
        <span className={`status-badge ${streamState}`}>{streamState}</span>
      </div>

      <div
        className="stream-stage"
        onPointerLeave={() => {
          setHoveredSlotId(null);
          setTooltip(null);
        }}
        onPointerMove={handlePointerMove}
        ref={wrapperRef}
      >
        {streamUrl ? (
          <img
            alt={`${cameraId} live stream`}
            className="stream-image"
            onError={onError}
            onLoad={onLoad}
            ref={imageRef}
            src={streamUrl}
          />
        ) : (
          <div className="stream-placeholder">Select a camera</div>
        )}
        <canvas aria-hidden="true" className="slot-canvas" ref={canvasRef} />
        {tooltip ? (
          <div
            className="slot-tooltip"
            style={{
              transform: `translate(${tooltip.x + 14}px, ${tooltip.y + 14}px)`,
            }}
          >
            {tooltip.label}
          </div>
        ) : null}
      </div>
    </section>
  );
}
