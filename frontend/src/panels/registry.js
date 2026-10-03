import { LiveVideoPanel } from './LiveVideoPanel';
import { SampledFramePanel } from './SampledFramePanel';
import { ServicesPanel } from './ServicesPanel';
import { TelemetryPanel } from './TelemetryPanel';
import { AnalysisStreamPanel } from './AnalysisStreamPanel';
import { NarrationAudioPanel } from './NarrationAudioPanel';
import { EventLogPanel } from './EventLogPanel';

/**
 * The panel registry — the extension point for this dashboard.
 *
 * To add a panel: write a component that takes
 *   { status, config, analyses, latestAudio, frameUrl, mode }
 * and append an entry here. Nothing else needs to change.
 *
 *   slot: 'stage'  one big panel beside the sidebar (rendered bare, no chrome)
 *         'side'   narrow column to the right of the stage
 *         'row'    full-width grid below; `span-2` in className widens it
 *   enabled: optional (ctx) => boolean, to hide a panel contextually
 */
export const PANELS = [
  { id: 'live-video', slot: 'stage', component: LiveVideoPanel },
  { id: 'connections', slot: 'side', component: ServicesPanel },
  { id: 'sampled-frame', slot: 'side', component: SampledFramePanel },
  { id: 'analysis-stream', slot: 'row', component: AnalysisStreamPanel },
  { id: 'narration-audio', slot: 'row', component: NarrationAudioPanel },
  { id: 'telemetry', slot: 'row', component: TelemetryPanel },
  { id: 'event-log', slot: 'row', component: EventLogPanel },
];

export function panelsFor(slot, ctx) {
  return PANELS.filter(
    (panel) => panel.slot === slot && (!panel.enabled || panel.enabled(ctx)),
  );
}
