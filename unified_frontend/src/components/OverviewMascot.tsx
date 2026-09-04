import { useRef, useState } from 'react'

export function OverviewMascot() {
  const videoRef = useRef<HTMLVideoElement | null>(null)
  const [isPlaying, setIsPlaying] = useState(true)

  const replay = () => {
    const video = videoRef.current
    if (!video) return
    video.currentTime = 0
    setIsPlaying(true)
    void video.play().catch(() => setIsPlaying(false))
  }

  return (
    <div className="pointer-events-none absolute left-0 top-0 z-[4] h-full aspect-[600/544] opacity-50">
      <img
        src="/assets/overview/overview-mascot-final.png"
        alt=""
        aria-hidden
        className="block h-full w-full select-none object-contain object-left md:hidden"
        draggable={false}
      />
      <button
        type="button"
        className="overview-mascot-trigger pointer-events-auto hidden md:block h-full w-full cursor-pointer border-0 bg-transparent p-0"
        aria-label="重新播放平台吉祥物动画"
        onClick={replay}
      >
        <div className="relative h-full w-full">
          <video
            ref={videoRef}
            className={`overview-mascot-media absolute inset-0 block h-full w-full select-none object-contain object-left transition-opacity duration-150 ${isPlaying ? 'opacity-100' : 'opacity-0'}`}
            autoPlay
            muted
            playsInline
            preload="auto"
            onEnded={() => setIsPlaying(false)}
            onError={() => setIsPlaying(false)}
          >
            <source src="/assets/overview/overview-mascot-alpha.webm" type="video/webm" media="(min-width: 768px)" />
          </video>
          <img
            src="/assets/overview/overview-mascot-final.png"
            alt=""
            aria-hidden
            className={`absolute inset-0 block h-full w-full select-none object-contain object-left transition-opacity duration-150 ${isPlaying ? 'opacity-0' : 'opacity-100'}`}
            draggable={false}
          />
        </div>
      </button>
    </div>
  )
}
