import { useMemo } from 'react'

export type CameraDirection = 'north' | 'south' | 'east' | 'west'

export type LightColor = 'red' | 'yellow' | 'green'

export type IntersectionTraffic = {
  vehicles: number
  light: LightColor
  last_update: string
}

function titleFromDirection(direction: CameraDirection) {
  switch (direction) {
    case 'north':
      return 'NORTH DIRECTION'
    case 'south':
      return 'SOUTH DIRECTION'
    case 'east':
      return 'EAST DIRECTION'
    case 'west':
      return 'WEST DIRECTION'
  }
}

type CameraCardProps = {
  direction: CameraDirection
  traffic: IntersectionTraffic
  imageUrl?: string | null
  onImageSelected?: (file: File) => void
  onRemoveImage?: () => void
}

export function CameraCard({ direction, traffic, imageUrl, onImageSelected, onRemoveImage }: CameraCardProps) {
  const densityPct = useMemo(() => Math.min(99, Math.round((traffic.vehicles / 25) * 100)), [traffic.vehicles])
  const priority = useMemo(() => (densityPct > 70 ? 'HIGH' : densityPct > 40 ? 'MED' : 'LOW'), [densityPct])

  return (
    <div className="st-cam">
      <div className="st-cam__top">
        <div className="st-cam__title">{titleFromDirection(direction)}</div>
        <div className="st-cam__badge">VEHICLE DETECTED</div>
      </div>

      <div className="st-cam__frame">
        <div className={`st-cam__light st-cam__light--${traffic.light}`} title={`Light: ${traffic.light}`} />
        <div className="st-cam__actions">
          <label className="st-uploadbtn">
            Upload
            <input
              type="file"
              accept="image/*"
              onChange={(event) => {
                const file = event.target.files?.[0]
                if (file && onImageSelected) {
                  onImageSelected(file)
                }
                event.target.value = ''
              }}
              hidden
            />
          </label>
          {imageUrl && onRemoveImage && (
            <button
              type="button"
              className="st-uploadbtn st-uploadbtn--ghost"
              onClick={onRemoveImage}
            >
              Remove
            </button>
          )}
        </div>
        {imageUrl && (
          <>
            <img
              src={imageUrl}
              alt={`${titleFromDirection(direction)} upload`}
              className="st-cam__img"
            />
            <div className="st-cam__tag">AI CAMERA FEED</div>
          </>
        )}
      </div>

      <div className="st-cam__footer">
        <div className="st-kv">
          <div className="st-kv__k">TRAFFIC DENSITY</div>
          <div className="st-kv__v">{densityPct}%</div>
        </div>
        <div className="st-kv">
          <div className="st-kv__k">PRIORITY SCORE</div>
          <div className={`st-kv__v ${priority === 'HIGH' ? 'st-kv__v--bad' : priority === 'MED' ? 'st-kv__v--warn' : 'st-kv__v--good'}`}>
            {priority}
          </div>
        </div>
        <div className="st-kv">
          <div className="st-kv__k">CURRENT GREEN TIME</div>
          <div className="st-kv__v">45s</div>
        </div>
        <div className="st-kv">
          <div className="st-kv__k">PEDESTRIANS</div>
          <div className="st-kv__v">{Math.max(0, Math.round(traffic.vehicles / 3))}</div>
        </div>
      </div>
    </div>
  )
}

