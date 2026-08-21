from __future__ import annotations

import argparse
import json
from typing import List, Tuple

import cv2

points: List[Tuple[int, int]] = []
polygons: List[List[Tuple[int, int]]] = []


def on_mouse(event, x, y, flags, param):
    global points
    if event == cv2.EVENT_LBUTTONDOWN:
        points.append((x, y))


def main() -> None:
    parser = argparse.ArgumentParser(description="手动绘制 ROI")
    parser.add_argument("--source", required=True, help="视频路径或摄像头索引")
    parser.add_argument("--out", default="roi_points.json", help="输出 json")
    args = parser.parse_args()

    source = int(args.source) if args.source.isdigit() else args.source
    cap = cv2.VideoCapture(source)
    ok, frame = cap.read()
    if not ok:
        raise RuntimeError("无法读取视频首帧")

    cv2.namedWindow("draw-roi")
    cv2.setMouseCallback("draw-roi", on_mouse)

    global points, polygons
    while True:
        canvas = frame.copy()
        for pt in points:
            cv2.circle(canvas, pt, 4, (0, 255, 255), -1)
        if len(points) >= 2:
            for i in range(1, len(points)):
                cv2.line(canvas, points[i - 1], points[i], (0, 255, 255), 2)
        for poly in polygons:
            for i in range(len(poly)):
                cv2.line(canvas, poly[i], poly[(i + 1) % len(poly)], (0, 255, 0), 2)
        cv2.putText(canvas, "LClick: add point | n: save polygon | c: clear current | q: quit", (16, 30), cv2.FONT_HERSHEY_SIMPLEX, 0.7, (0, 0, 255), 2)
        cv2.imshow("draw-roi", canvas)
        key = cv2.waitKey(20) & 0xFF
        if key == ord("c"):
            points = []
        elif key == ord("n"):
            if len(points) >= 3:
                polygons.append(points[:])
                points = []
        elif key == ord("q"):
            break

    with open(args.out, "w", encoding="utf-8") as f:
        json.dump(polygons, f, ensure_ascii=False, indent=2)
    cap.release()
    cv2.destroyAllWindows()
    print(f"Saved to {args.out}")


if __name__ == "__main__":
    main()
