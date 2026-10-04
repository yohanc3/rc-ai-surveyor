import { useCallback, useEffect, useRef, useState } from 'react';

/**
 * Narration playback.
 *
 * Browsers block unprompted audio, so nothing plays until the viewer enables it
 * once (design document section 2). Per section 7 a clip that is already
 * playing is never interrupted: a newer clip replaces whatever is queued and
 * unplayed, and only the newest queued clip is kept.
 */
export function useNarrationAudio(latestAudio) {
  const audioRef = useRef(null);
  const queuedRef = useRef(null);
  // Bumped whenever a play attempt is deliberately superseded — by a newer
  // clip, by muting, or by the unlock tap. Changing `src` or calling pause()
  // rejects a play() promise that is still pending, and that rejection is
  // expected rather than a failure the viewer should be told about.
  const attemptRef = useRef(0);
  const [enabled, setEnabled] = useState(false);
  const [playing, setPlaying] = useState(false);
  const [error, setError] = useState(null);
  const [playedId, setPlayedId] = useState(null);

  if (audioRef.current === null && typeof Audio !== 'undefined') {
    audioRef.current = new Audio();
  }

  const play = useCallback((clip) => {
    const audio = audioRef.current;
    if (!audio || !clip) return;
    const attempt = (attemptRef.current += 1);
    audio.src = clip.audio_url;
    setError(null);

    const started = audio.play();
    // Older browsers return undefined rather than a promise.
    if (!started || typeof started.then !== 'function') {
      setPlaying(true);
      setPlayedId(clip.analysis_id);
      return;
    }

    started
      .then(() => {
        if (attempt !== attemptRef.current) return;
        setPlaying(true);
        setPlayedId(clip.analysis_id);
      })
      .catch((err) => {
        // A superseded attempt always rejects. Say nothing: this is the
        // newest-clip-wins rule working, not a playback failure.
        if (attempt !== attemptRef.current) return;
        if (err && err.name === 'AbortError') return;
        setPlaying(false);
        setError(err.message);
      });
  }, []);

  // When a clip ends, release whatever is queued behind it.
  useEffect(() => {
    const audio = audioRef.current;
    if (!audio) return undefined;
    const onEnded = () => {
      setPlaying(false);
      const queued = queuedRef.current;
      queuedRef.current = null;
      if (queued && enabled) play(queued);
    };
    audio.addEventListener('ended', onEnded);
    return () => audio.removeEventListener('ended', onEnded);
  }, [enabled, play]);

  useEffect(() => {
    if (!latestAudio || !enabled) return;
    if (latestAudio.analysis_id === playedId) return;
    if (playing) {
      // Replace only the queued, unplayed clip.
      queuedRef.current = latestAudio;
      return;
    }
    play(latestAudio);
  }, [latestAudio, enabled, playing, playedId, play]);

  const enable = useCallback(() => {
    const audio = audioRef.current;
    setEnabled(true);
    // Unlock playback inside the click handler, which is what browsers require.
    if (audio) {
      attemptRef.current += 1;
      audio.muted = true;
      audio
        .play()
        .catch(() => {})
        .finally(() => {
          audio.pause();
          audio.muted = false;
          audio.currentTime = 0;
        });
    }
  }, []);

  const disable = useCallback(() => {
    setEnabled(false);
    queuedRef.current = null;
    const audio = audioRef.current;
    if (audio) {
      attemptRef.current += 1;
      audio.pause();
      setPlaying(false);
    }
  }, []);

  return { enabled, enable, disable, playing, error };
}
