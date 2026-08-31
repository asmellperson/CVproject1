# 文件说明：实现感兴趣区域相关的基础能力。
# 数据流：在上层调用方与下层库、外部资源之间传递配置、状态或业务数据。

from __future__ import annotations

import argparse
import json
from typing import List, Tuple

import cv2

points: List[Tuple[int, int]] = []
polygons: List[List[Tuple[int, int]]] = []


# 功能：处理 `on_mouse` 对应的感兴趣区域逻辑；输入由参数提供，处理结果见返回值说明
# 参数：
#   - `event`（未显式标注）：待处理的事件对象
#   - `x`（未显式标注）：`x` 对应的业务输入值
#   - `y`（未显式标注）：`y` 对应的业务输入值
#   - `flags`（未显式标注）：`flags` 对应的业务输入值
#   - `param`（未显式标注）：`param` 对应的业务输入值
# 返回：None；仅执行处理流程，不返回业务数据。
# 调用关系：
#   - 调用方：程序入口 / 无调用者（静态分析未发现直接调用；框架反射、回调或多态调用处待确认）
#   - 内部调用：`points.append`。
# 副作用/注意事项：会修改全局或闭包状态。
def on_mouse(event, x, y, flags, param):
    global points
    if event == cv2.EVENT_LBUTTONDOWN:
        points.append((x, y))


# 功能：实现 `main` 对应的感兴趣区域逻辑；输入由参数提供，处理结果见返回值说明
# 参数：无。
# 返回：None；返回该函数计算、查询或构造得到的结果；具体语义由类型及调用方使用方式确定。
# 调用关系：
#   - 调用方：程序入口 / 无调用者（静态分析未发现直接调用；框架反射、回调或多态调用处待确认）
#   - 内部调用：`argparse.ArgumentParser`、`parser.add_argument`、`parser.parse_args`、`args.source.isdigit`、`int`、`cv2.VideoCapture`、`cap.read`、`RuntimeError`、`cv2.namedWindow`、`cv2.setMouseCallback`
#          等共 25 个调用。
# 副作用/注意事项：会修改全局或闭包状态；可能创建、写入、移动或删除本地文件；校验或执行失败时会主动抛出异常。
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
