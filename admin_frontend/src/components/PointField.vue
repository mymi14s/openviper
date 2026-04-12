<script setup lang="ts">
import { ref, computed, watch, onMounted, onUnmounted, nextTick } from 'vue'
import L from 'leaflet'
import 'leaflet/dist/leaflet.css'

interface PointValue {
  longitude: number | null
  latitude: number | null
}

const props = defineProps<{
  modelValue: string | PointValue | null
  disabled?: boolean
  required?: boolean
  srid?: number
}>()

const emit = defineEmits<{
  'update:modelValue': [value: string | null]
}>()

// ── Parse incoming value into { longitude, latitude } ─────────────────────

function parsePoint(raw: string | PointValue | null): PointValue {
  if (!raw) return { longitude: null, latitude: null }

  if (typeof raw === 'object' && 'longitude' in raw) {
    return { longitude: raw.longitude, latitude: raw.latitude }
  }

  if (typeof raw === 'string') {
    const stripped = raw.trim()

    // EWKT: 'SRID=4326;POINT(lon lat)'
    const ewktMatch = stripped.match(/^SRID=\d+;POINT\(\s*([-\d.]+)\s+([-\d.]+)\s*\)$/i)
    if (ewktMatch) {
      return { longitude: parseFloat(ewktMatch[1]), latitude: parseFloat(ewktMatch[2]) }
    }

    // WKT: 'POINT(lon lat)'
    const wktMatch = stripped.match(/^POINT\(\s*([-\d.]+)\s+([-\d.]+)\s*\)$/i)
    if (wktMatch) {
      return { longitude: parseFloat(wktMatch[1]), latitude: parseFloat(wktMatch[2]) }
    }

    // GeoJSON string
    try {
      const gj = JSON.parse(stripped)
      if (gj.type === 'Point' && Array.isArray(gj.coordinates) && gj.coordinates.length >= 2) {
        return { longitude: parseFloat(gj.coordinates[0]), latitude: parseFloat(gj.coordinates[1]) }
      }
    } catch {
      // not JSON
    }
  }

  return { longitude: null, latitude: null }
}

// ── SVG pin icon — avoids Vite asset-URL issues with Leaflet's default PNGs ──

const PIN_ICON = L.divIcon({
  html: `<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 24 36" width="24" height="36">
    <path d="M12 0C5.373 0 0 5.373 0 12c0 9 12 24 12 24S24 21 24 12C24 5.373 18.627 0 12 0z" fill="#4F46E5"/>
    <circle cx="12" cy="12" r="5" fill="white"/>
  </svg>`,
  className: '',
  iconSize: [24, 36],
  iconAnchor: [12, 36],
  popupAnchor: [0, -36],
})

// ── Internal state ───────────────────────────────────────────────────────────

const point = ref<PointValue>(parsePoint(props.modelValue))
const lonError = ref('')
const latError = ref('')
const mapContainer = ref<HTMLElement | null>(null)
const locating = ref(false)
let leafletMap: L.Map | null = null
let marker: L.Marker | null = null

// ── Serialise & validate ─────────────────────────────────────────────────────

function toEWKT(lon: number, lat: number): string {
  return `SRID=${props.srid ?? 4326};POINT(${lon} ${lat})`
}

function validateLon(val: number | null): string {
  if (val === null) return props.required ? 'Longitude is required.' : ''
  if (isNaN(val)) return 'Must be a number.'
  if (val < -180 || val > 180) return 'Must be between −180 and 180.'
  return ''
}

function validateLat(val: number | null): string {
  if (val === null) return props.required ? 'Latitude is required.' : ''
  if (isNaN(val)) return 'Must be a number.'
  if (val < -90 || val > 90) return 'Must be between −90 and 90.'
  return ''
}

function emitValue() {
  const { longitude: lon, latitude: lat } = point.value
  if (lon === null && lat === null) {
    emit('update:modelValue', null)
    return
  }
  lonError.value = validateLon(lon)
  latError.value = validateLat(lat)
  if (!lonError.value && !latError.value && lon !== null && lat !== null) {
    emit('update:modelValue', toEWKT(lon, lat))
  }
}

// ── Map helpers ──────────────────────────────────────────────────────────────

function placeMarker(lat: number, lng: number) {
  if (!leafletMap) return
  if (marker) {
    marker.setLatLng([lat, lng])
  } else {
    marker = L.marker([lat, lng], { icon: PIN_ICON, draggable: !props.disabled })
      .addTo(leafletMap)
      .on('dragend', (e: L.DragEndEvent) => {
        const ll = (e.target as L.Marker).getLatLng()
        point.value = {
          longitude: parseFloat(ll.lng.toFixed(6)),
          latitude: parseFloat(ll.lat.toFixed(6)),
        }
        lonError.value = ''
        latError.value = ''
        emitValue()
      })
  }
  const currentZoom = leafletMap.getZoom()
  leafletMap.setView([lat, lng], currentZoom < 5 ? 13 : currentZoom)
}

function removeMarker() {
  if (marker && leafletMap) {
    leafletMap.removeLayer(marker)
    marker = null
  }
}

// ── Input handlers ───────────────────────────────────────────────────────────

function handleLonInput(raw: string) {
  const val = raw === '' ? null : parseFloat(raw)
  point.value = { ...point.value, longitude: val }
  lonError.value = validateLon(val)
  const { longitude: lon, latitude: lat } = point.value
  if (lon !== null && lat !== null && !lonError.value && !validateLat(lat)) {
    placeMarker(lat, lon)
  }
  emitValue()
}

function handleLatInput(raw: string) {
  const val = raw === '' ? null : parseFloat(raw)
  point.value = { ...point.value, latitude: val }
  latError.value = validateLat(val)
  const { longitude: lon, latitude: lat } = point.value
  if (lon !== null && lat !== null && !validateLon(lon) && !latError.value) {
    placeMarker(lat, lon)
  }
  emitValue()
}

function clearPoint() {
  point.value = { longitude: null, latitude: null }
  lonError.value = ''
  latError.value = ''
  removeMarker()
  emit('update:modelValue', null)
}

// ── Geolocation ──────────────────────────────────────────────────────────────

function locateMe() {
  if (!navigator.geolocation || props.disabled) return
  locating.value = true
  navigator.geolocation.getCurrentPosition(
    (pos) => {
      locating.value = false
      const lon = parseFloat(pos.coords.longitude.toFixed(6))
      const lat = parseFloat(pos.coords.latitude.toFixed(6))
      point.value = { longitude: lon, latitude: lat }
      lonError.value = ''
      latError.value = ''
      placeMarker(lat, lon)
      emitValue()
    },
    () => { locating.value = false },
    { enableHighAccuracy: true, timeout: 8000 },
  )
}

// ── Display value ────────────────────────────────────────────────────────────

const displayValue = computed(() => {
  const { longitude: lon, latitude: lat } = point.value
  if (lon === null || lat === null) return null
  return `${lat.toFixed(6)}°, ${lon.toFixed(6)}°`
})

// ── Sync external modelValue changes ────────────────────────────────────────

watch(
  () => props.modelValue,
  (newVal) => {
    const parsed = parsePoint(newVal)
    if (parsed.longitude === point.value.longitude && parsed.latitude === point.value.latitude) return
    point.value = parsed
    if (parsed.longitude !== null && parsed.latitude !== null) {
      placeMarker(parsed.latitude, parsed.longitude)
    } else {
      removeMarker()
    }
  },
)

// ── Lifecycle ────────────────────────────────────────────────────────────────

onMounted(async () => {
  await nextTick()
  if (!mapContainer.value) return

  leafletMap = L.map(mapContainer.value, { zoomControl: true, attributionControl: true })
  L.tileLayer('https://tile.openstreetmap.org/{z}/{x}/{y}.png', {
    maxZoom: 19,
    attribution: '© <a href="https://www.openstreetmap.org/copyright">OpenStreetMap</a>',
  }).addTo(leafletMap)

  const { longitude: lon, latitude: lat } = point.value
  if (lon !== null && lat !== null) {
    leafletMap.setView([lat, lon], 13)
    placeMarker(lat, lon)
  } else {
    leafletMap.setView([20, 0], 2)
  }

  if (!props.disabled) {
    leafletMap.on('click', (e: L.LeafletMouseEvent) => {
      const lng = parseFloat(e.latlng.lng.toFixed(6))
      const lt = parseFloat(e.latlng.lat.toFixed(6))
      point.value = { longitude: lng, latitude: lt }
      lonError.value = ''
      latError.value = ''
      placeMarker(lt, lng)
      emitValue()
    })
  }
})

onUnmounted(() => {
  leafletMap?.remove()
  leafletMap = null
  marker = null
})
</script>

<template>
  <div class="space-y-3">

    <!-- Coordinate inputs -->
    <div class="grid grid-cols-2 gap-3">
      <div>
        <label class="block text-xs font-medium text-gray-600 dark:text-gray-400 mb-1">
          Longitude
          <span class="font-normal text-gray-400 dark:text-gray-500">&nbsp;(−180 to 180)</span>
        </label>
        <input
          type="number"
          step="any"
          min="-180"
          max="180"
          :value="point.longitude ?? ''"
          :disabled="disabled"
          :required="required"
          placeholder="e.g. −0.1276"
          class="w-full px-3 py-2 text-sm border rounded-md bg-white dark:bg-gray-700 text-gray-900 dark:text-gray-100 placeholder-gray-400 focus:outline-none focus:ring-2 focus:ring-indigo-500"
          :class="lonError ? 'border-red-400 dark:border-red-500' : 'border-gray-300 dark:border-gray-600'"
          @input="handleLonInput(($event.target as HTMLInputElement).value)"
        />
        <p v-if="lonError" class="mt-1 text-xs text-red-500">{{ lonError }}</p>
      </div>

      <div>
        <label class="block text-xs font-medium text-gray-600 dark:text-gray-400 mb-1">
          Latitude
          <span class="font-normal text-gray-400 dark:text-gray-500">&nbsp;(−90 to 90)</span>
        </label>
        <input
          type="number"
          step="any"
          min="-90"
          max="90"
          :value="point.latitude ?? ''"
          :disabled="disabled"
          :required="required"
          placeholder="e.g. 51.5074"
          class="w-full px-3 py-2 text-sm border rounded-md bg-white dark:bg-gray-700 text-gray-900 dark:text-gray-100 placeholder-gray-400 focus:outline-none focus:ring-2 focus:ring-indigo-500"
          :class="latError ? 'border-red-400 dark:border-red-500' : 'border-gray-300 dark:border-gray-600'"
          @input="handleLatInput(($event.target as HTMLInputElement).value)"
        />
        <p v-if="latError" class="mt-1 text-xs text-red-500">{{ latError }}</p>
      </div>
    </div>

    <!-- Action bar -->
    <div class="flex items-center justify-between text-xs text-gray-500 dark:text-gray-400">
      <span>{{ displayValue ?? 'No location set' }}</span>
      <div class="flex items-center gap-2">
        <!-- Geolocation button -->
        <button
          v-if="!disabled"
          type="button"
          :disabled="locating"
          title="Use my current location"
          class="flex items-center gap-1 px-2 py-1 rounded border border-gray-300 dark:border-gray-600 hover:bg-gray-100 dark:hover:bg-gray-700 transition-colors disabled:opacity-50"
          @click="locateMe"
        >
          <svg v-if="!locating" class="w-3.5 h-3.5" fill="none" stroke="currentColor" stroke-width="2" viewBox="0 0 24 24">
            <circle cx="12" cy="12" r="3" />
            <path stroke-linecap="round" d="M12 2v3M12 19v3M2 12h3M19 12h3" />
          </svg>
          <svg v-else class="w-3.5 h-3.5 animate-spin" fill="none" viewBox="0 0 24 24">
            <circle class="opacity-25" cx="12" cy="12" r="10" stroke="currentColor" stroke-width="4" />
            <path class="opacity-75" fill="currentColor" d="M4 12a8 8 0 018-8V0C5.373 0 0 5.373 0 12h4z" />
          </svg>
          My location
        </button>

        <!-- Clear button -->
        <button
          v-if="!disabled && (point.longitude !== null || point.latitude !== null)"
          type="button"
          title="Clear coordinates"
          class="flex items-center gap-1 px-2 py-1 rounded border border-gray-300 dark:border-gray-600 hover:bg-gray-100 dark:hover:bg-gray-700 transition-colors text-red-500 dark:text-red-400"
          @click="clearPoint"
        >
          <svg class="w-3.5 h-3.5" fill="none" stroke="currentColor" stroke-width="2" viewBox="0 0 24 24">
            <path stroke-linecap="round" d="M6 18L18 6M6 6l12 12" />
          </svg>
          Clear
        </button>
      </div>
    </div>

    <!-- Interactive Leaflet map -->
    <div
      ref="mapContainer"
      class="w-full rounded-md overflow-hidden border border-gray-200 dark:border-gray-700"
      style="height: 280px;"
    />

    <p v-if="!disabled" class="text-xs text-gray-400 dark:text-gray-500">
      Click the map to place a pin · Drag the pin to adjust position
    </p>

  </div>
</template>
