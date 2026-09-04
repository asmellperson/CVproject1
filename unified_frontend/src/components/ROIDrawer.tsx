import { useState, useRef, useCallback, useEffect } from 'react';
import { Button } from '@/components/ui/button';
import { Card, CardContent } from '@/components/ui/card';
import { Badge } from '@/components/ui/badge';
import {
  Check,
  X,
  RotateCcw,
  Save,
  Trash2,
  Edit3,
  CheckSquare
} from 'lucide-react';

export interface Point {
  x: number;
  y: number;
}

export interface ROIPolygon {
  name: string;
  points: Point[];
  color: string;
  closed: boolean;
}

interface ROIDrawerProps {
  width?: number;
  height?: number;
  initialROIs?: ROIPolygon[];
  onChange?: (rois: ROIPolygon[]) => void;
  backgroundImage?: string;
}

const DEFAULT_COLORS = [
  '#00ffff',
  '#00ff00',
  '#ff00ff',
  '#ffff00',
  '#ff6600',
];

const DEFAULT_ROIS: ROIPolygon[] = [
  { name: 'post_roi', points: [], color: DEFAULT_COLORS[0], closed: false },
  { name: 'desk_roi', points: [], color: DEFAULT_COLORS[1], closed: false },
  { name: 'phone_use_roi', points: [], color: DEFAULT_COLORS[2], closed: false },
];

export function ROIDrawer({
  width = 960,
  height = 540,
  initialROIs,
  onChange,
  backgroundImage
}: ROIDrawerProps) {
  const canvasRef = useRef<HTMLCanvasElement>(null);
  const [rois, setRois] = useState<ROIPolygon[]>(initialROIs || DEFAULT_ROIS);
  const [activeROIIndex, setActiveROIIndex] = useState(0);
  const [isDrawing, setIsDrawing] = useState(false);
  const [hoverPoint, setHoverPoint] = useState<Point | null>(null);
  const [draggedPoint, setDraggedPoint] = useState<{ roiIndex: number; pointIndex: number } | null>(null);

  const scaleX = 1920 / width;
  const scaleY = 1080 / height;

  const draw = useCallback(() => {
    const canvas = canvasRef.current;
    if (!canvas) return;

    const ctx = canvas.getContext('2d');
    if (!ctx) return;

    ctx.clearRect(0, 0, width, height);

    if (backgroundImage) {
      const img = new Image();
      img.onload = () => {
        ctx.drawImage(img, 0, 0, width, height);
      };
      img.src = backgroundImage;
    } else {
      ctx.fillStyle = '#1e293b';
      ctx.fillRect(0, 0, width, height);

      ctx.strokeStyle = '#334155';
      ctx.lineWidth = 1;
      const gridSize = 40;

      for (let x = 0; x <= width; x += gridSize) {
        ctx.beginPath();
        ctx.moveTo(x, 0);
        ctx.lineTo(x, height);
        ctx.stroke();
      }

      for (let y = 0; y <= height; y += gridSize) {
        ctx.beginPath();
        ctx.moveTo(0, y);
        ctx.lineTo(width, y);
        ctx.stroke();
      }
    }

    rois.forEach((roi, roiIndex) => {
      const isActive = roiIndex === activeROIIndex;

      if (roi.points.length > 0) {
        ctx.strokeStyle = roi.color;
        ctx.fillStyle = roi.color + (isActive ? '33' : '1a');
        ctx.lineWidth = isActive ? 3 : 2;

        ctx.beginPath();
        roi.points.forEach((point, i) => {
          if (i === 0) {
            ctx.moveTo(point.x, point.y);
          } else {
            ctx.lineTo(point.x, point.y);
          }
        });

        if (roi.closed) {
          ctx.closePath();
          ctx.fill();
        }
        ctx.stroke();

        roi.points.forEach((point, pointIndex) => {
          ctx.beginPath();
          ctx.arc(point.x, point.y, isActive ? 6 : 4, 0, Math.PI * 2);
          ctx.fillStyle = roi.color;
          ctx.fill();
          ctx.strokeStyle = '#fff';
          ctx.lineWidth = 2;
          ctx.stroke();

          if (isActive) {
            ctx.fillStyle = '#fff';
            ctx.font = '10px sans-serif';
            ctx.textAlign = 'center';
            ctx.textBaseline = 'middle';
            ctx.fillText(String(pointIndex + 1), point.x, point.y);
          }
        });

        if (isActive && hoverPoint && !roi.closed && isDrawing) {
          ctx.beginPath();
          ctx.setLineDash([5, 5]);
          ctx.strokeStyle = roi.color;
          ctx.lineWidth = 1;

          if (roi.points.length > 0) {
            const lastPoint = roi.points[roi.points.length - 1];
            ctx.moveTo(lastPoint.x, lastPoint.y);
            ctx.lineTo(hoverPoint.x, hoverPoint.y);
          }

          if (roi.points.length > 2) {
            const firstPoint = roi.points[0];
            const dist = Math.sqrt(
              Math.pow(hoverPoint.x - firstPoint.x, 2) +
              Math.pow(hoverPoint.y - firstPoint.y, 2)
            );
            if (dist < 20) {
              ctx.moveTo(hoverPoint.x, hoverPoint.y);
              ctx.lineTo(firstPoint.x, firstPoint.y);
            }
          }

          ctx.stroke();
          ctx.setLineDash([]);
        }

        if (roi.points.length > 0) {
          const firstPoint = roi.points[0];
          ctx.fillStyle = roi.color;
          ctx.font = 'bold 12px sans-serif';
          ctx.textAlign = 'left';
          ctx.textBaseline = 'bottom';
          ctx.fillText(roi.name, firstPoint.x, firstPoint.y - 10);
        }
      }
    });
  }, [rois, activeROIIndex, hoverPoint, isDrawing, width, height, backgroundImage]);

  useEffect(() => {
    draw();
  }, [draw]);

  useEffect(() => {
    onChange?.(rois);
  }, [rois, onChange]);

  const getCanvasPoint = (e: React.MouseEvent<HTMLCanvasElement>): Point => {
    const canvas = canvasRef.current;
    if (!canvas) return { x: 0, y: 0 };

    const rect = canvas.getBoundingClientRect();
    return {
      x: (e.clientX - rect.left) * (canvas.width / rect.width),
      y: (e.clientY - rect.top) * (canvas.height / rect.height),
    };
  };

  const handleMouseDown = (e: React.MouseEvent<HTMLCanvasElement>) => {
    const point = getCanvasPoint(e);
    const roi = rois[activeROIIndex];

    for (let i = 0; i < roi.points.length; i++) {
      const p = roi.points[i];
      const dist = Math.sqrt(Math.pow(point.x - p.x, 2) + Math.pow(point.y - p.y, 2));
      if (dist < 10) {
        setDraggedPoint({ roiIndex: activeROIIndex, pointIndex: i });
        return;
      }
    }

    if (!isDrawing || roi.closed) return;

    if (roi.points.length > 2) {
      const firstPoint = roi.points[0];
      const dist = Math.sqrt(
        Math.pow(point.x - firstPoint.x, 2) +
        Math.pow(point.y - firstPoint.y, 2)
      );
      if (dist < 20) {
        closePolygon();
        return;
      }
    }

    const newRois = [...rois];
    newRois[activeROIIndex].points.push(point);
    setRois(newRois);
  };

  const handleMouseMove = (e: React.MouseEvent<HTMLCanvasElement>) => {
    const point = getCanvasPoint(e);
    setHoverPoint(point);

    if (draggedPoint) {
      const newRois = [...rois];
      newRois[draggedPoint.roiIndex].points[draggedPoint.pointIndex] = point;
      setRois(newRois);
    }
  };

  const handleMouseUp = () => {
    setDraggedPoint(null);
  };

  const closePolygon = () => {
    const newRois = [...rois];
    if (newRois[activeROIIndex].points.length >= 3) {
      newRois[activeROIIndex].closed = true;
      setRois(newRois);
      setIsDrawing(false);
    }
  };

  const startDrawing = () => {
    const newRois = [...rois];
    newRois[activeROIIndex].points = [];
    newRois[activeROIIndex].closed = false;
    setRois(newRois);
    setIsDrawing(true);
  };

  const clearActiveROI = () => {
    const newRois = [...rois];
    newRois[activeROIIndex].points = [];
    newRois[activeROIIndex].closed = false;
    setRois(newRois);
    setIsDrawing(false);
  };

  const deleteLastPoint = () => {
    const newRois = [...rois];
    newRois[activeROIIndex].points.pop();
    setRois(newRois);
  };

  const getScaledCoordinates = (roi: ROIPolygon): [number, number][] => {
    return roi.points.map(p => [
      Math.round(p.x * scaleX),
      Math.round(p.y * scaleY),
    ] as [number, number]);
  };

  const exportConfig = () => {
    const config = {
      post_roi: getScaledCoordinates(rois[0]),
      desk_roi: getScaledCoordinates(rois[1]),
      phone_use_roi: getScaledCoordinates(rois[2]),
    };

    const blob = new Blob([JSON.stringify(config, null, 2)], { type: 'application/json' });
    const url = URL.createObjectURL(blob);
    const a = document.createElement('a');
    a.href = url;
    a.download = 'roi_config.json';
    a.click();
    URL.revokeObjectURL(url);
  };

  return (
    <div className="space-y-4">
      <div className="flex flex-wrap gap-2">
        {rois.map((roi, index) => (
          <Button
            key={roi.name}
            variant={activeROIIndex === index ? 'default' : 'outline'}
            size="sm"
            onClick={() => {
              setActiveROIIndex(index);
              setIsDrawing(false);
            }}
            className="gap-2"
            style={{
              borderColor: activeROIIndex === index ? roi.color : undefined,
              backgroundColor: activeROIIndex === index ? roi.color : undefined,
            }}
          >
            <div
              className="w-3 h-3 rounded-full"
              style={{ backgroundColor: roi.color }}
            />
            {roi.name}
            {roi.closed && <CheckSquare className="w-4 h-4" />}
          </Button>
        ))}
      </div>

      <Card className="overflow-hidden">
        <CardContent className="p-0">
          <div className="relative">
            <canvas
              ref={canvasRef}
              width={width}
              height={height}
              onMouseDown={handleMouseDown}
              onMouseMove={handleMouseMove}
              onMouseUp={handleMouseUp}
              onMouseLeave={() => {
                setHoverPoint(null);
                setDraggedPoint(null);
              }}
              className={`w-full h-auto cursor-${isDrawing ? 'crosshair' : 'default'}`}
              style={{
                cursor: isDrawing ? 'crosshair' : draggedPoint ? 'grabbing' : 'grab',
                maxWidth: '100%'
              }}
            />

            <div className="absolute top-4 left-4 bg-black/70 text-white px-3 py-2 rounded-lg text-sm">
              <p className="font-medium">{rois[activeROIIndex].name}</p>
              <p className="text-xs text-slate-300">
                {rois[activeROIIndex].closed
                  ? '点击并拖动顶点可调整位置'
                  : isDrawing
                    ? '点击添加点，靠近首点可闭合'
                    : '点击"开始绘制"创建区域'}
              </p>
            </div>

            {hoverPoint && (
              <div className="absolute bottom-4 left-4 bg-black/70 text-white px-2 py-1 rounded text-xs font-mono">
                ({Math.round(hoverPoint.x * scaleX)}, {Math.round(hoverPoint.y * scaleY)})
              </div>
            )}
          </div>
        </CardContent>
      </Card>

      <div className="flex flex-wrap items-center gap-3">
        {!rois[activeROIIndex].closed ? (
          <>
            {!isDrawing ? (
              <Button onClick={startDrawing} className="gap-2">
                <Edit3 className="w-4 h-4" />
                开始绘制
              </Button>
            ) : (
              <>
                <Button
                  onClick={closePolygon}
                  disabled={rois[activeROIIndex].points.length < 3}
                  variant="default"
                  className="gap-2"
                >
                  <Check className="w-4 h-4" />
                  完成绘制
                </Button>
                <Button
                  onClick={deleteLastPoint}
                  disabled={rois[activeROIIndex].points.length === 0}
                  variant="outline"
                  className="gap-2"
                >
                  <X className="w-4 h-4" />
                  撤销
                </Button>
                <Button
                  onClick={clearActiveROI}
                  variant="outline"
                  className="gap-2 text-red-600 hover:text-red-700"
                >
                  <Trash2 className="w-4 h-4" />
                  清空
                </Button>
              </>
            )}
          </>
        ) : (
          <>
            <Button
              onClick={startDrawing}
              variant="outline"
              className="gap-2"
            >
              <RotateCcw className="w-4 h-4" />
              重新绘制
            </Button>
            <Button
              onClick={clearActiveROI}
              variant="outline"
              className="gap-2 text-red-600 hover:text-red-700"
            >
              <Trash2 className="w-4 h-4" />
              删除
            </Button>
          </>
        )}

        <div className="flex-1" />

        <Button
          onClick={exportConfig}
          variant="secondary"
          className="gap-2"
          disabled={!rois.some(r => r.closed)}
        >
          <Save className="w-4 h-4" />
          导出配置
        </Button>
      </div>

      <Card className="bg-slate-50">
        <CardContent className="p-4">
          <div className="flex items-center justify-between mb-2">
            <span className="text-sm font-medium text-slate-700">配置预览 (1920x1080坐标)</span>
            <Badge variant="outline" className="text-xs">
              实时更新
            </Badge>
          </div>
          <pre className="text-xs bg-slate-900 text-slate-100 p-3 rounded-lg overflow-auto max-h-48">
{JSON.stringify({
  post_roi: getScaledCoordinates(rois[0]),
  desk_roi: getScaledCoordinates(rois[1]),
  phone_use_roi: getScaledCoordinates(rois[2]),
}, null, 2)}
          </pre>
        </CardContent>
      </Card>
    </div>
  );
}
