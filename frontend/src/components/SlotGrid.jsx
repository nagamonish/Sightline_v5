function occupiedDuration(slot) {
  if (!slot.occupied || !slot.occupied_since) {
    return "Free";
  }

  const seconds = Math.max(0, Math.floor(Date.now() / 1000 - slot.occupied_since));
  if (seconds < 60) {
    return `${seconds}s`;
  }
  const minutes = Math.floor(seconds / 60);
  if (minutes < 60) {
    return `${minutes}m`;
  }
  return `${Math.floor(minutes / 60)}h ${minutes % 60}m`;
}

export function SlotGrid({ slots }) {
  if (!slots.length) {
    return (
      <section className="slot-grid-shell">
        <div className="empty-slots">No calibrated spaces</div>
      </section>
    );
  }

  return (
    <section className="slot-grid-shell" aria-label="Parking slots">
      <div className="slot-grid">
        {slots.map((slot) => {
          const recent =
            slot.last_changed && Date.now() / 1000 - slot.last_changed < 4;
          return (
            <button
              className={`slot-pill ${slot.occupied ? "occupied" : "free"} ${
                recent ? "changed" : ""
              }`}
              key={slot.slot_id}
              type="button"
              title={`${slot.slot_id} ${slot.occupied ? "occupied" : "free"}`}
            >
              <span>{slot.slot_id}</span>
              <small>{occupiedDuration(slot)}</small>
            </button>
          );
        })}
      </div>
    </section>
  );
}
