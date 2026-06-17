#!/usr/bin/env python3
from __future__ import annotations

import argparse
import json
import urllib.request
from pathlib import Path
from typing import Any

import cv2
import numpy as np


HF_DATASET_BASE = "https://huggingface.co/datasets/Voxel51/PKLot/resolve/main"
HF_SAMPLES_URL = f"{HF_DATASET_BASE}/samples.json"


def download(url: str, destination: Path, force: bool = False) -> None:
    if destination.exists() and not force:
        return
    destination.parent.mkdir(parents=True, exist_ok=True)
    request = urllib.request.Request(url, headers={"User-Agent": "ParkIQ sample setup"})
    with urllib.request.urlopen(request, timeout=45) as response:
        destination.write_bytes(response.read())


def ensure_pklot_image(url: str, destination: Path, force: bool) -> None:
    if destination.exists() and not force:
        image = cv2.imread(str(destination), cv2.IMREAD_COLOR)
        if image is not None and image.shape[:2] == (720, 1280):
            return
    download(url, destination, force=True)


def first_hf_sample(samples_url: str = HF_SAMPLES_URL) -> dict[str, Any]:
    """Stream just the first sample object from the large Hugging Face metadata file."""
    request = urllib.request.Request(
        samples_url,
        headers={"User-Agent": "ParkIQ sample setup"},
    )
    with urllib.request.urlopen(request, timeout=60) as response:
        started = False
        saw_array = False
        depth = 0
        in_string = False
        escaped = False
        buffer: list[str] = []

        while True:
            chunk = response.read(8192)
            if not chunk:
                break

            for char in chunk.decode("utf-8"):
                if not started:
                    if char == "[":
                        saw_array = True
                    elif saw_array and char == "{":
                        started = True
                        depth = 1
                        buffer.append(char)
                    continue

                buffer.append(char)

                if escaped:
                    escaped = False
                    continue
                if char == "\\" and in_string:
                    escaped = True
                    continue
                if char == '"':
                    in_string = not in_string
                    continue
                if in_string:
                    continue

                if char == "{":
                    depth += 1
                elif char == "}":
                    depth -= 1
                    if depth == 0:
                        return json.loads("".join(buffer))

    raise RuntimeError("could not read the first PKLot sample from Hugging Face")


def slots_from_sample(sample: dict[str, Any], image_path: Path) -> list[dict[str, Any]]:
    image = cv2.imread(str(image_path), cv2.IMREAD_COLOR)
    if image is None:
        raise RuntimeError(f"could not read sample image: {image_path}")

    image_height, image_width = image.shape[:2]
    polylines = sample.get("parking_spaces", {}).get("polylines", [])

    slots: list[dict[str, Any]] = []
    for index, polyline in enumerate(sorted(polylines, key=lambda item: item.get("space_id", 0)), 1):
        normalized_points = polyline.get("points", [[]])[0]
        if len(normalized_points) < 3:
            continue
        polygon = [
            [round(point[0] * image_width, 2), round(point[1] * image_height, 2)]
            for point in normalized_points
        ]
        occupied = polyline.get("occupancy_status") == "occupied"
        slots.append(
            {
                "slot_id": f"PK{index:03d}",
                "polygon": polygon,
                "expected_occupied": occupied,
                "source_space_id": polyline.get("space_id", index),
            }
        )

    return slots


def write_overlay(image_path: Path, overlay_path: Path, slots: list[dict[str, Any]]) -> None:
    image = cv2.imread(str(image_path), cv2.IMREAD_COLOR)
    if image is None:
        raise RuntimeError(f"could not read sample image: {image_path}")

    for slot in slots:
        points = np.array(slot["polygon"], dtype=np.int32)
        color = (72, 92, 255) if slot["expected_occupied"] else (113, 233, 46)
        cv2.polylines(image, [points], isClosed=True, color=color, thickness=2)
        center = points.mean(axis=0).astype(int)
        cv2.putText(
            image,
            slot["slot_id"],
            tuple(center),
            cv2.FONT_HERSHEY_SIMPLEX,
            0.42,
            color,
            1,
            cv2.LINE_AA,
        )

    cv2.imwrite(str(overlay_path), image)


def write_outputs(output_dir: Path, force: bool = False) -> None:
    image_path = output_dir / "preview.jpg"
    overlay_path = output_dir / "overlay.jpg"
    slots_path = output_dir / "slots.json"
    manifest_path = output_dir / "manifest.json"

    sample = first_hf_sample()
    image_url = f"{HF_DATASET_BASE}/{sample['filepath']}"
    ensure_pklot_image(image_url, image_path, force)
    slots = slots_from_sample(sample, image_path)
    if not slots:
        raise RuntimeError("no slots were extracted from the PKLot sample metadata")

    write_overlay(image_path, overlay_path, slots)

    payload = {
        "dataset": "PKLot via Voxel51/Hugging Face",
        "source": "PKLot sample with official parking-space polygon annotations",
        "image_url": image_url,
        "image_path": str(image_path),
        "overlay_path": str(overlay_path),
        "sample_filepath": sample.get("filepath"),
        "parking_lot": sample.get("source"),
        "parking_timestamp": sample.get("parking_timestamp", {}).get("$date"),
        "slots": slots,
        "summary": {
            "total": len(slots),
            "expected_occupied": sum(1 for slot in slots if slot["expected_occupied"]),
            "expected_available": sum(1 for slot in slots if not slot["expected_occupied"]),
        },
    }

    slots_path.write_text(json.dumps(payload, indent=2) + "\n", encoding="utf-8")
    manifest_path.write_text(
        json.dumps(
            {
                **payload["summary"],
                "slots_json": str(slots_path),
                "preview_image": str(image_path),
                "overlay_image": str(overlay_path),
                "ffmpeg_command": (
                    "ffmpeg -re -loop 1 -framerate 5 -i "
                    f"{image_path} -vf \"format=yuv420p\" -an "
                    "-c:v libx264 -preset ultrafast -tune zerolatency -r 5 -g 10 "
                    "-f rtsp -rtsp_transport tcp rtsp://127.0.0.1:8554/parkiq"
                ),
            },
            indent=2,
        )
        + "\n",
        encoding="utf-8",
    )

    print(f"Wrote {image_path}")
    print(f"Wrote {overlay_path}")
    print(f"Wrote {slots_path}")
    print(
        "Extracted "
        f"{payload['summary']['total']} slots "
        f"({payload['summary']['expected_occupied']} expected occupied, "
        f"{payload['summary']['expected_available']} expected available)."
    )
    print()
    print("Loop this image into MediaMTX with:")
    print(json.loads(manifest_path.read_text(encoding="utf-8"))["ffmpeg_command"])
    print()
    print("Then load the polygons into ParkIQ with:")
    print("curl -X POST http://localhost:8000/cameras/cam1/samples/pklot")


def main() -> None:
    parser = argparse.ArgumentParser(description="Prepare a small PKLot fixture for ParkIQ.")
    parser.add_argument(
        "--output-dir",
        default="sample-data/pklot",
        help="Directory where the sample image, overlay, and slots JSON will be written.",
    )
    parser.add_argument(
        "--force",
        action="store_true",
        help="Re-download the sample image even if it already exists.",
    )
    args = parser.parse_args()
    write_outputs(Path(args.output_dir), force=args.force)


if __name__ == "__main__":
    main()
