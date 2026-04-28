import { useRef, useState } from 'react'
import { Button } from '@/components/ui/button'
import { Badge } from '@/components/ui/badge'
import { Circle, Square, Download } from 'lucide-react'

function buildFilename() {
  const now = new Date()
  const pad = (n: number) => String(n).padStart(2, '0')
  return `guard_record_${now.getFullYear()}${pad(now.getMonth() + 1)}${pad(now.getDate())}_${pad(now.getHours())}${pad(now.getMinutes())}${pad(now.getSeconds())}.webm`
}

export function ScreenRecorder() {
  const [isRecording, setIsRecording] = useState(false)
  const [lastFileName, setLastFileName] = useState('')
  const [error, setError] = useState('')

  const mediaRecorderRef = useRef<MediaRecorder | null>(null)
  const chunksRef = useRef<Blob[]>([])
  const streamRef = useRef<MediaStream | null>(null)

  const stopTracks = () => {
    if (streamRef.current) {
      streamRef.current.getTracks().forEach((track) => track.stop())
      streamRef.current = null
    }
  }

  const stopRecording = () => {
    if (mediaRecorderRef.current && mediaRecorderRef.current.state !== 'inactive') {
      mediaRecorderRef.current.stop()
    } else {
      stopTracks()
      setIsRecording(false)
    }
  }

  const startRecording = async () => {
    try {
      setError('')
      chunksRef.current = []

      const stream = await navigator.mediaDevices.getDisplayMedia({
        video: {
          frameRate: 15,
        },
        audio: false,
      })

      streamRef.current = stream

      const mimeType = MediaRecorder.isTypeSupported('video/webm;codecs=vp9')
        ? 'video/webm;codecs=vp9'
        : 'video/webm'

      const recorder = new MediaRecorder(stream, { mimeType })
      mediaRecorderRef.current = recorder

      recorder.ondataavailable = (event) => {
        if (event.data && event.data.size > 0) {
          chunksRef.current.push(event.data)
        }
      }

      recorder.onstop = () => {
        const blob = new Blob(chunksRef.current, { type: mimeType })
        const url = URL.createObjectURL(blob)
        const filename = buildFilename()
        setLastFileName(filename)

        const a = document.createElement('a')
        a.href = url
        a.download = filename
        a.click()

        URL.revokeObjectURL(url)
        stopTracks()
        setIsRecording(false)
      }

      // 用户通过浏览器共享栏手动停止时
      const [videoTrack] = stream.getVideoTracks()
      if (videoTrack) {
        videoTrack.onended = () => {
          stopRecording()
        }
      }

      recorder.start(1000)
      setIsRecording(true)
    } catch (err: any) {
      console.error(err)
      setError(err?.message || '录屏启动失败')
      stopTracks()
      setIsRecording(false)
    }
  }

  return (
    <div className="flex flex-col gap-2">
      <div className="flex items-center gap-2">
        {!isRecording ? (
          <Button onClick={startRecording} className="gap-2">
            <Circle className="h-4 w-4" />
            开始录屏
          </Button>
        ) : (
          <Button onClick={stopRecording} variant="destructive" className="gap-2">
            <Square className="h-4 w-4" />
            停止录屏
          </Button>
        )}

        {isRecording && <Badge className="bg-red-500">录制中</Badge>}
        {!isRecording && lastFileName && (
          <Badge variant="outline" className="gap-1">
            <Download className="h-3 w-3" />
            已保存
          </Badge>
        )}
      </div>

      {lastFileName ? <div className="text-xs text-slate-500">最近文件：{lastFileName}</div> : null}
      {error ? <div className="text-xs text-red-500">{error}</div> : null}
      <div className="text-xs text-slate-500">
        点击后浏览器会弹出共享选择框，请选择当前标签页或窗口。
      </div>
    </div>
  )
}

export default ScreenRecorder